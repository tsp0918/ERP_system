"""Packing List PDF generator.

Renders a delivery-level packing list.  Each line represents one
delivery item with quantity, weight, and carton count.  Used alongside
the Commercial Invoice for international shipments.
"""
from __future__ import annotations

import math
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HEADER_COLOR = colors.HexColor("#92400e")   # dark amber
ROW_ALT      = colors.HexColor("#fef3c7")   # light amber
UNITS_PER_CARTON: int = 50                  # pcs per export carton (default for CTRL-HC200)
UNIT_WEIGHT_KG: Decimal = Decimal("0.010")  # 10 g per unit (default if not in Material)


class PackingListPdfGenerator:
    """Generate a packing list PDF for a Delivery."""

    def __init__(self):
        self.styles = getSampleStyleSheet()

    def render(
        self,
        *,
        delivery,
        customer,
        seller_company,
        material_map: dict[str, object] | None = None,
        so_document_number: str | None = None,
        incoterms: str | None = None,
    ) -> bytes:
        """Return PDF bytes.

        Args:
            delivery: Delivery ORM instance with `items`.
            customer: BusinessPartner ORM instance (consignee).
            seller_company: Company ORM instance (shipper).
            material_map: {material_code: Material ORM} for description/weight lookup.
            so_document_number: Source SO number to print as reference.
            incoterms: Incoterms code (FOB / CIF / DAP …).
        """
        material_map = material_map or {}
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=18 * mm, rightMargin=18 * mm,
            topMargin=15 * mm, bottomMargin=15 * mm,
            title=f"Packing List {delivery.document_number}",
        )

        story: list = []
        story += self._header(delivery)
        story += self._parties(seller_company, customer, delivery,
                               so_document_number, incoterms)
        story += self._items_table(delivery, material_map)
        story += self._marks(delivery, customer)
        doc.build(story)
        return buf.getvalue()

    # ── header bar ──────────────────────────────────────────────────

    def _header(self, delivery):
        bar = Table(
            [[Paragraph(
                "<font color='white'><b>PACKING LIST</b></font><br/>"
                "<font color='white' size='9'>梱包明細書 / Liste de Colisage</font>",
                self.styles["Normal"],
            )]],
            colWidths=[170 * mm],
        )
        bar.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), HEADER_COLOR),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        return [bar, Spacer(1, 5 * mm)]

    # ── parties panel ───────────────────────────────────────────────

    def _parties(self, seller, customer, delivery, so_num, incoterms):
        small = ParagraphStyle("small", parent=self.styles["Normal"],
                               fontSize=9, leading=11)

        shipper = (
            f"<b>{seller.name}</b><br/>"
            f"Country: {seller.country}<br/>"
        )

        clines = [f"<b>{customer.name}</b>",
                  customer.address_line1 or "",
                  customer.address_line2 or "",
                  f"{customer.city or ''}  {customer.postal_code or ''}".strip(),
                  f"Country: {customer.country}"]
        consignee = "<br/>".join(l for l in clines if l.strip())

        doc_info = (
            f"Packing List No: <b>{delivery.document_number}</b><br/>"
            f"Date: {delivery.document_date.isoformat()}<br/>"
        )
        if so_num:
            doc_info += f"Ref SO: {so_num}<br/>"
        if delivery.reference:
            doc_info += f"Delivery Ref: {delivery.reference}<br/>"
        if incoterms:
            doc_info += f"Incoterms: <b>{incoterms}</b><br/>"
        if delivery.actual_delivery_date:
            doc_info += f"Ship Date: {delivery.actual_delivery_date.isoformat()}<br/>"
        case_no = getattr(delivery, "aitm_case_no", None)
        if case_no:
            doc_info += f"<b>AI_TM Approval: {case_no}</b><br/>"
            approval = getattr(delivery, "aitm_approval_status", None)
            if approval:
                doc_info += f"Approval Status: <b>{approval}</b><br/>"

        t = Table(
            [
                ["Shipper (From)", "Consignee (To)", "Document Info"],
                [Paragraph(shipper, small),
                 Paragraph(consignee, small),
                 Paragraph(doc_info, small)],
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
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return [t, Spacer(1, 5 * mm)]

    # ── items table ─────────────────────────────────────────────────

    def _items_table(self, delivery, material_map):
        header = [
            "#", "Material Code", "Description",
            "Qty", "Unit",
            "Net Wt/Unit\n(kg)", "Total Net Wt\n(kg)",
            "Gross Wt\n(kg)", "Cartons",
        ]
        rows = [header]

        total_net = Decimal("0")
        total_gross = Decimal("0")
        total_cartons = 0

        for di in sorted(delivery.items, key=lambda x: x.item_no):
            mat = material_map.get(di.material_code)
            desc = mat.description if mat else di.material_code
            unit_w = (Decimal(str(mat.weight_kg))
                      if mat and mat.weight_kg else UNIT_WEIGHT_KG)
            qty = Decimal(str(di.quantity))
            net_w = (qty * unit_w).quantize(Decimal("0.001"))
            gross_w = (net_w * Decimal("1.15")).quantize(Decimal("0.001"))  # +15% packaging
            cartons = max(1, math.ceil(float(qty) / UNITS_PER_CARTON))

            total_net   += net_w
            total_gross += gross_w
            total_cartons += cartons

            rows.append([
                str(di.item_no),
                di.material_code,
                desc[:40],
                self._fmt_qty(di.quantity),
                di.unit,
                self._fmt_w(unit_w),
                self._fmt_w(net_w),
                self._fmt_w(gross_w),
                str(cartons),
            ])

        # totals row
        rows.append([
            "", "", "TOTAL",
            "", "",
            "",
            self._fmt_w(total_net),
            self._fmt_w(total_gross),
            str(total_cartons),
        ])

        col_w = [10*mm, 30*mm, 55*mm, 12*mm, 10*mm,
                 17*mm, 18*mm, 16*mm, 14*mm]
        t = Table(rows, colWidths=col_w, repeatRows=1)
        n = len(rows)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_COLOR),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 1), (0, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, n - 2), [colors.white, ROW_ALT]),
            ("BACKGROUND", (0, n - 1), (-1, n - 1), colors.HexColor("#fde68a")),
            ("FONTNAME", (0, n - 1), (-1, n - 1), "Helvetica-Bold"),
            ("LINEABOVE", (0, n - 1), (-1, n - 1), 0.8, colors.black),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.lightgrey),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return [t, Spacer(1, 5 * mm)]

    # ── shipping marks ───────────────────────────────────────────────

    def _marks(self, delivery, customer):
        small = ParagraphStyle("marks", parent=self.styles["Normal"],
                               fontSize=8, leading=10,
                               textColor=colors.HexColor("#374151"))
        marks_text = (
            f"<b>Shipping Marks / 荷印:</b><br/>"
            f"Consignee: {customer.name}  ({customer.country})<br/>"
            f"Delivery: {delivery.document_number}<br/>"
            f"Handle with care / 取り扱い注意<br/>"
            f"<br/>"
            f"<b>Note:</b> This is a computer-generated packing list. "
            f"Quantities and weights are as declared. "
            f"Actual gross weight may vary ±5% due to outer packaging."
        )
        return [Paragraph(marks_text, small)]

    # ── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _fmt_qty(q) -> str:
        d = Decimal(str(q))
        return f"{int(d)}" if d == d.to_integral_value() else f"{d:.3f}".rstrip("0")

    @staticmethod
    def _fmt_w(w: Decimal) -> str:
        return f"{w:.3f}"
