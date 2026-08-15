"""Export Declaration PDF generator (輸出申告書).

Generates an ERP-side Shipper's Export Declaration that captures:
  - Exporter / Consignee information
  - Item classification (HS / ECCN)
  - AI_TradeManagement case reference and clearance status
  - License type and authority
  - Signature block for compliance officer

This document is produced by the ERP and submitted to customs /
forwarding agents alongside the commercial invoice and packing list.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

HEADER_COLOR  = colors.HexColor("#1e3a5f")   # navy
SECTION_COLOR = colors.HexColor("#dbeafe")   # light blue
WARN_COLOR    = colors.HexColor("#fef9c3")   # yellow


class ExportDeclPdfGenerator:
    """Render an Export Declaration as PDF bytes."""

    def __init__(self):
        self.styles = getSampleStyleSheet()

    def render(
        self,
        *,
        decl,
        seller_company,
        customer,
        material=None,
        ai_tm_case_no: str | None = None,
        so_document_number: str | None = None,
        delivery_document_number: str | None = None,
    ) -> bytes:
        """Return PDF bytes.

        Args:
            decl: ExportDeclaration ORM instance.
            seller_company: Company ORM instance (exporter).
            customer: BusinessPartner ORM instance (consignee).
            material: Material ORM instance (optional, for classification detail).
            ai_tm_case_no: AI_TM transaction case number (from SO.export_check_ref).
            so_document_number: Source SO number.
            delivery_document_number: Source Delivery number.
        """
        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=18 * mm, rightMargin=18 * mm,
            topMargin=15 * mm, bottomMargin=15 * mm,
            title=f"Export Declaration {decl.declaration_number or decl.id}",
        )

        story: list = []
        story += self._header(decl)
        story += self._parties(seller_company, customer)
        story += self._references(decl, so_document_number,
                                  delivery_document_number, ai_tm_case_no)
        story += self._items(decl, material)
        story += self._compliance(decl, ai_tm_case_no)
        story += self._signature(decl)

        doc.build(story)
        return buf.getvalue()

    # ── header ──────────────────────────────────────────────────────

    def _header(self, decl):
        bar = Table(
            [[Paragraph(
                "<font color='white'><b>EXPORT DECLARATION</b></font><br/>"
                "<font color='white' size='8'>"
                "輸出申告書 / Déclaration d'Exportation / Shipper's Export Declaration"
                "</font>",
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
        status_color = (
            colors.HexColor("#d1fae5") if decl.status in ("APPROVED", "SUBMITTED")
            else colors.HexColor("#fef3c7") if decl.status == "DRAFT"
            else colors.HexColor("#fee2e2")
        )
        status_bar = Table(
            [[Paragraph(
                f"<b>Status: {decl.status}</b>   "
                f"Declaration No: {decl.declaration_number or '(Pending)'}",
                ParagraphStyle("sb", parent=self.styles["Normal"], fontSize=9),
            )]],
            colWidths=[170 * mm],
        )
        status_bar.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), status_color),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("BOX", (0, 0), (-1, -1), 0.3, colors.grey),
        ]))
        return [bar, Spacer(1, 2 * mm), status_bar, Spacer(1, 4 * mm)]

    # ── parties ─────────────────────────────────────────────────────

    def _parties(self, seller, customer):
        small = ParagraphStyle("small", parent=self.styles["Normal"],
                               fontSize=9, leading=11)

        exporter = (
            f"<b>{seller.name}</b><br/>"
            f"Country: <b>{seller.country}</b><br/>"
            f"Currency: {seller.currency}"
        )
        clines = [f"<b>{customer.name}</b>",
                  customer.address_line1 or "",
                  customer.address_line2 or "",
                  f"{customer.city or ''}  {customer.postal_code or ''}".strip(),
                  f"Country: <b>{customer.country}</b>",
                  f"BP Code: {customer.bp_code}"]
        consignee_txt = "<br/>".join(l for l in clines if l.strip())

        t = Table(
            [
                ["EXPORTER / 輸出者", "CONSIGNEE / 仕向人"],
                [Paragraph(exporter, small), Paragraph(consignee_txt, small)],
            ],
            colWidths=[85 * mm, 85 * mm],
        )
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SECTION_COLOR),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        return [t, Spacer(1, 4 * mm)]

    # ── reference block ─────────────────────────────────────────────

    def _references(self, decl, so_num, del_num, case_no):
        small = ParagraphStyle("small", parent=self.styles["Normal"],
                               fontSize=9, leading=11)

        col1 = (
            f"Declaration Date: <b>{date.today().isoformat()}</b><br/>"
            + (f"Source SO: {so_num}<br/>" if so_num else "")
            + (f"Source Delivery: {del_num}<br/>" if del_num else "")
            + f"Destination Country: <b>{decl.destination_country or '-'}</b>"
        )
        col2 = (
            f"AI_TM Case No: <b>{case_no or decl.ai_tm_transaction_id or '-'}</b><br/>"
            + (f"License No: {decl.ai_tm_license_number or '(N/A)'}<br/>")
            + (f"License Type: {decl.license_type or 'N/A'}<br/>")
            + (f"Authority: {decl.license_authority or 'N/A'}")
        )

        t = Table(
            [
                ["DOCUMENT REFERENCES", "EXPORT LICENSE INFORMATION"],
                [Paragraph(col1, small), Paragraph(col2, small)],
            ],
            colWidths=[85 * mm, 85 * mm],
        )
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SECTION_COLOR),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        return [t, Spacer(1, 4 * mm)]

    # ── commodity / item block ───────────────────────────────────────

    def _items(self, decl, material):
        rows = [
            ["Field", "Value"],
            ["Material Code",   decl.material_code or "-"],
            ["Description",     material.description if material else "-"],
            ["HS Code (Schedule B)",
             decl.hs_code or (material.hs_code if material else "-")],
            ["ECCN",
             decl.eccn or (material.eccn if material else "-")],
            ["Quantity",
             f"{decl.quantity or '-'} {decl.quantity_unit or ''}".strip()],
            ["Declared Value (USD)",
             f"USD {decl.declared_value_usd:,.2f}" if decl.declared_value_usd else "-"],
        ]

        t = Table(rows, colWidths=[55 * mm, 115 * mm])
        n = len(rows)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SECTION_COLOR),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.lightgrey),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
        ]))
        return [
            Paragraph("<b>COMMODITY DETAILS / 貨物明細</b>",
                      ParagraphStyle("sec", parent=self.styles["Normal"],
                                     fontSize=9, textColor=HEADER_COLOR)),
            Spacer(1, 2 * mm),
            t,
            Spacer(1, 4 * mm),
        ]

    # ── compliance notes ─────────────────────────────────────────────

    def _compliance(self, decl, case_no):
        small = ParagraphStyle("small", parent=self.styles["Normal"],
                               fontSize=8, leading=10,
                               textColor=colors.HexColor("#374151"))

        eccn = decl.eccn or "N/A"
        hs   = decl.hs_code or "N/A"

        notes = [
            f"<b>EAR / Export Control Notice:</b>",
            f"ECCN: {eccn}  |  HS: {hs}  |  "
            f"Destination: {decl.destination_country or 'N/A'}",
            "",
            "This shipment has been screened through AI_TradeManagement export compliance "
            "platform. The transaction has been reviewed and cleared subject to applicable "
            "export control regulations (EAR / FEFTA / EU Dual-Use Regulation).",
        ]
        if case_no or decl.ai_tm_transaction_id:
            notes.append(
                f"AI_TM Transaction ID: {case_no or decl.ai_tm_transaction_id}"
            )
        notes += [
            "",
            "The exporter certifies that all information contained herein is accurate and "
            "that the goods are not destined for nuclear, chemical, or biological weapons "
            "end-uses. Re-export without prior written authorization is prohibited.",
        ]
        if decl.remarks:
            notes += ["", f"<b>Remarks:</b> {decl.remarks}"]

        t = Table(
            [["COMPLIANCE CERTIFICATION / 輸出コンプライアンス証明"],
             [Paragraph("<br/>".join(notes), small)]],
            colWidths=[170 * mm],
        )
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SECTION_COLOR),
            ("BACKGROUND", (0, 1), (-1, 1), WARN_COLOR),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.lightgrey),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        return [t, Spacer(1, 5 * mm)]

    # ── signature block ─────────────────────────────────────────────

    def _signature(self, decl):
        small = ParagraphStyle("small", parent=self.styles["Normal"],
                               fontSize=8, leading=10)

        sig_table = Table(
            [
                ["AUTHORIZED SIGNATURE / 責任者署名",
                 "COMPLIANCE OFFICER / コンプライアンス担当",
                 "DATE / 日付"],
                [Paragraph("<br/><br/>_______________________", small),
                 Paragraph("<br/><br/>_______________________", small),
                 Paragraph(f"<br/><br/>{date.today().isoformat()}", small)],
                ["Name:", "Name:", "Stamp:"],
                ["Title:", "Title:", ""],
            ],
            colWidths=[57 * mm, 57 * mm, 56 * mm],
        )
        sig_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.lightgrey),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return [
            HRFlowable(width="100%", thickness=0.5, color=colors.grey),
            Spacer(1, 3 * mm),
            sig_table,
        ]
