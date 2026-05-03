"""Invoice PDF generator.

Builds a PDF representation of a BillingDocument suitable for export to
international customers. Three layout variants are selected based on the
relationship to the customer:

    intercompany - For group-internal transfer (e.g. JP HQ -> TW subsidiary).
                   Adds a 'INTERCOMPANY TRANSFER' watermark and transfer-pricing
                   notice. Smaller header.
    distributor  - Standard commercial invoice with reseller markings.
    enduser      - Standard commercial invoice with end-user license notice.

These are content-only differences; the structural backbone (lines/totals)
is identical.

The generator does not assume a specific persistence layer - it returns
PDF bytes. The router decides whether to stream them as Response or
attach to a file.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


# ==================================================================
# Layout-variant config
# ==================================================================
INVOICE_VARIANTS = {
    "intercompany": {
        "header_bar_color": colors.HexColor("#374151"),  # dark slate
        "title": "INTERCOMPANY INVOICE",
        "subtitle": "(Internal Transfer - Transfer Pricing Applied)",
        "watermark": "INTERCOMPANY",
        "footer_note": (
            "This invoice represents an intercompany transfer. "
            "Pricing reflects arm's-length transfer pricing policy."
        ),
    },
    "distributor": {
        "header_bar_color": colors.HexColor("#1d4ed8"),  # blue
        "title": "COMMERCIAL INVOICE",
        "subtitle": "(For Authorized Distributor)",
        "watermark": None,
        "footer_note": (
            "Goods are sold to an authorized distributor. "
            "Re-export to restricted destinations is prohibited."
        ),
    },
    "enduser": {
        "header_bar_color": colors.HexColor("#047857"),  # green
        "title": "COMMERCIAL INVOICE",
        "subtitle": "(End-User Direct Sale)",
        "watermark": None,
        "footer_note": (
            "Goods are sold for end use only. Re-sale or re-export "
            "without prior written consent is prohibited."
        ),
    },
}


# ==================================================================
# Generator
# ==================================================================
class InvoicePdfGenerator:
    """Render a BillingDocument as PDF bytes."""

    def __init__(self, variant: str = "enduser"):
        if variant not in INVOICE_VARIANTS:
            raise ValueError(f"Unknown invoice variant: {variant}. "
                            f"Choose from: {list(INVOICE_VARIANTS.keys())}")
        self.variant = variant
        self.cfg = INVOICE_VARIANTS[variant]
        self.styles = getSampleStyleSheet()

    def render(self, *, billing, customer, seller_company,
               material_descriptions: dict[str, str] | None = None) -> bytes:
        """Render a PDF.

        Args:
            billing: BillingDocument ORM instance with `items`.
            customer: BusinessPartner ORM instance.
            seller_company: Company ORM instance (issuing entity).
            material_descriptions: optional {material_code: description} map
              for richer line descriptions.
        """
        material_descriptions = material_descriptions or {}
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=18 * mm, rightMargin=18 * mm,
            topMargin=15 * mm, bottomMargin=15 * mm,
            title=f"Invoice {billing.document_number}",
        )

        story = []
        story += self._build_header(seller_company, billing)
        story += self._build_parties(seller_company, customer, billing)
        story += self._build_line_table(billing, material_descriptions)
        story += self._build_totals(billing)
        story += self._build_footer(billing)

        doc.build(
            story,
            onFirstPage=self._draw_watermark,
            onLaterPages=self._draw_watermark,
        )
        return buf.getvalue()

    # ---- header ----
    def _build_header(self, seller_company, billing):
        bar = Table(
            [[Paragraph(
                f"<font color='white'><b>{self.cfg['title']}</b></font><br/>"
                f"<font color='white' size='9'>{self.cfg['subtitle']}</font>",
                self.styles["Normal"])]],
            colWidths=[170 * mm],
        )
        bar.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), self.cfg["header_bar_color"]),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        return [bar, Spacer(1, 6 * mm)]

    # ---- seller / buyer panel ----
    def _build_parties(self, seller_company, customer, billing):
        small = ParagraphStyle(
            "small", parent=self.styles["Normal"], fontSize=9, leading=11,
        )
        seller_addr = (
            f"<b>{seller_company.name}</b><br/>"
            f"Country: {seller_company.country}<br/>"
            f"Currency: {seller_company.currency}"
        )
        buyer_addr_lines = [f"<b>{customer.name}</b>",
                           customer.address_line1 or "",
                           customer.address_line2 or "",
                           f"{customer.city or ''}  {customer.postal_code or ''}",
                           f"Country: {customer.country}"]
        buyer_addr = "<br/>".join([l for l in buyer_addr_lines if l.strip()])

        meta = (
            f"Invoice No: <b>{billing.document_number}</b><br/>"
            f"Invoice Date: {billing.document_date.isoformat()}<br/>"
            f"Currency: {billing.currency}<br/>"
            f"Payment Terms: {billing.payment_terms or '-'}<br/>"
            f"Customer: {customer.bp_code}"
        )

        t = Table(
            [
                ["Seller", "Buyer", "Invoice Information"],
                [Paragraph(seller_addr, small),
                 Paragraph(buyer_addr, small),
                 Paragraph(meta, small)],
            ],
            colWidths=[55 * mm, 60 * mm, 55 * mm],
        )
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return [t, Spacer(1, 5 * mm)]

    # ---- line table ----
    def _build_line_table(self, billing, descriptions):
        header = ["#", "Material", "Description", "Qty", "Unit Price", "Net Amount"]
        rows = [header]
        for it in sorted(billing.items, key=lambda i: i.item_no):
            desc = descriptions.get(it.material_code, "")
            rows.append([
                str(it.item_no),
                it.material_code,
                desc,
                self._fmt_qty(it.quantity),
                self._fmt_money(it.unit_price),
                self._fmt_money(it.net_amount),
            ])

        t = Table(rows, colWidths=[10 * mm, 30 * mm, 60 * mm,
                                  20 * mm, 25 * mm, 30 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0),
             self.cfg["header_bar_color"]),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 1), (0, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f9fafb")]),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.lightgrey),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return [t, Spacer(1, 4 * mm)]

    # ---- totals ----
    def _build_totals(self, billing):
        rows = [
            ["Net Amount:", f"{self._fmt_money(billing.net_amount)} {billing.currency}"],
            ["Tax:",        f"{self._fmt_money(billing.tax_amount)} {billing.currency}"],
            ["Gross:",      f"{self._fmt_money(billing.gross_amount)} {billing.currency}"],
        ]
        t = Table(rows, colWidths=[40 * mm, 60 * mm])
        t.hAlign = "RIGHT"
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LINEABOVE", (0, 2), (-1, 2), 0.6, colors.black),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return [t, Spacer(1, 6 * mm)]

    # ---- footer ----
    def _build_footer(self, billing):
        small = ParagraphStyle(
            "footer", parent=self.styles["Normal"],
            fontSize=8, leading=10, textColor=colors.HexColor("#374151"),
        )
        ref_line = ""
        if billing.sales_order_id:
            ref_line = f"Source SO: {billing.sales_order_id}<br/>"
        if billing.delivery_id:
            ref_line += f"Source Delivery: {billing.delivery_id}<br/>"

        text = (
            f"{ref_line}"
            f"<br/><b>Notice:</b> {self.cfg['footer_note']}<br/>"
            f"<br/>"
            f"This document is computer-generated. "
            f"For any inquiries, please contact the issuing entity."
        )
        return [Paragraph(text, small)]

    # ---- watermark ----
    def _draw_watermark(self, canvas, doc):
        if not self.cfg.get("watermark"):
            return
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 70)
        canvas.setFillColorRGB(0.85, 0.85, 0.85)
        canvas.translate(105 * mm, 150 * mm)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, self.cfg["watermark"])
        canvas.restoreState()

    # ---- format helpers ----
    @staticmethod
    def _fmt_money(amount: Decimal | float | int) -> str:
        return f"{Decimal(amount):,.2f}"

    @staticmethod
    def _fmt_qty(qty: Decimal | float | int) -> str:
        d = Decimal(qty)
        if d == d.to_integral_value():
            return f"{int(d)}"
        return f"{d:.3f}".rstrip("0").rstrip(".")
