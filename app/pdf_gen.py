"""Render structured documents and HTML flyers to PDF.

The PDF document path uses ReportLab Platypus (no system deps, pure Python).
The flyer path uses WeasyPrint (HTML/CSS → PDF, needs Pango/Cairo).
"""
from __future__ import annotations

import io
import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)

logger = logging.getLogger(__name__)


# Try to register a Unicode-capable font so Russian text renders properly.
# DejaVu is shipped by most Linux distros (and the python `fonttools` wheels).
def _register_unicode_fonts() -> tuple[str, str, str]:
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
        ("/usr/share/fonts/truetype/freefont/FreeSans.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf"),
    ]
    for regular, bold, italic in candidates:
        if all(os.path.exists(p) for p in (regular, bold, italic)):
            try:
                pdfmetrics.registerFont(TTFont("AppSans", regular))
                pdfmetrics.registerFont(TTFont("AppSans-Bold", bold))
                pdfmetrics.registerFont(TTFont("AppSans-Italic", italic))
                from reportlab.pdfbase.pdfmetrics import registerFontFamily

                registerFontFamily(
                    "AppSans",
                    normal="AppSans",
                    bold="AppSans-Bold",
                    italic="AppSans-Italic",
                    boldItalic="AppSans-Bold",
                )
                return "AppSans", "AppSans-Bold", "AppSans-Italic"
            except Exception as exc:
                logger.warning("Failed to register %s: %s", regular, exc)
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


REGULAR_FONT, BOLD_FONT, ITALIC_FONT = _register_unicode_fonts()


def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName=BOLD_FONT,
            fontSize=26,
            leading=32,
            alignment=TA_LEFT,
            spaceAfter=6,
            textColor=colors.HexColor("#0F172A"),
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName=ITALIC_FONT,
            fontSize=14,
            leading=18,
            spaceAfter=18,
            textColor=colors.HexColor("#475569"),
        ),
        "meta": ParagraphStyle(
            "Meta",
            parent=base["Normal"],
            fontName=REGULAR_FONT,
            fontSize=10,
            leading=14,
            spaceAfter=18,
            textColor=colors.HexColor("#64748B"),
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName=BOLD_FONT,
            fontSize=16,
            leading=20,
            spaceBefore=18,
            spaceAfter=8,
            textColor=colors.HexColor("#1E293B"),
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName=REGULAR_FONT,
            fontSize=11,
            leading=16,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
            textColor=colors.HexColor("#111827"),
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName=REGULAR_FONT,
            fontSize=11,
            leading=16,
            textColor=colors.HexColor("#111827"),
        ),
        "callout": ParagraphStyle(
            "Callout",
            parent=base["BodyText"],
            fontName=ITALIC_FONT,
            fontSize=11,
            leading=16,
            leftIndent=12,
            rightIndent=12,
            spaceBefore=8,
            spaceAfter=12,
            textColor=colors.HexColor("#1E40AF"),
            backColor=colors.HexColor("#EFF6FF"),
            borderColor=colors.HexColor("#BFDBFE"),
            borderWidth=0.5,
            borderPadding=10,
        ),
        "footer": ParagraphStyle(
            "Footer",
            parent=base["Normal"],
            fontName=REGULAR_FONT,
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#94A3B8"),
        ),
    }


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class _DocTemplate(BaseDocTemplate):
    def __init__(self, *args: Any, footer_text: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._footer_text = footer_text

    def afterPage(self) -> None:  # noqa: N802 (reportlab API name)
        canvas = self.canv
        canvas.saveState()
        page_width, _ = A4
        canvas.setFont(REGULAR_FONT, 8)
        canvas.setFillColor(colors.HexColor("#94A3B8"))
        canvas.drawCentredString(
            page_width / 2.0,
            12 * mm,
            f"{self._footer_text}  ·  стр. {self.page}",
        )
        canvas.restoreState()


def render_document_pdf(spec: Dict[str, Any]) -> bytes:
    """Render a structured document spec to PDF bytes."""
    buf = io.BytesIO()
    styles = _styles()

    title = str(spec.get("title") or "Документ").strip()
    subtitle = str(spec.get("subtitle") or "").strip()
    author = str(spec.get("author") or "").strip()
    doc_date = str(spec.get("date") or "").strip() or date.today().isoformat()

    doc = _DocTemplate(
        buf,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title=title,
        author=author or "VPKN bot",
        footer_text=title,
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="main",
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame])])

    flowables: List[Any] = []
    flowables.append(Paragraph(_escape(title), styles["title"]))
    if subtitle:
        flowables.append(Paragraph(_escape(subtitle), styles["subtitle"]))

    meta_bits: List[str] = []
    if author:
        meta_bits.append(_escape(author))
    meta_bits.append(_escape(doc_date))
    flowables.append(Paragraph(" · ".join(meta_bits), styles["meta"]))

    sections = spec.get("sections") or []
    for section in sections:
        heading = str(section.get("heading") or "").strip()
        if heading:
            flowables.append(Paragraph(_escape(heading), styles["h2"]))

        for para in section.get("paragraphs") or []:
            text = str(para).strip()
            if text:
                flowables.append(Paragraph(_escape(text), styles["body"]))

        bullets = section.get("bullets") or []
        if bullets:
            items = [
                ListItem(Paragraph(_escape(str(b)), styles["bullet"]), leftIndent=12)
                for b in bullets
                if str(b).strip()
            ]
            if items:
                flowables.append(
                    ListFlowable(
                        items,
                        bulletType="bullet",
                        bulletColor=colors.HexColor("#1E40AF"),
                        leftIndent=16,
                    )
                )
                flowables.append(Spacer(1, 4))

        numbered = section.get("numbered") or []
        if numbered:
            items = [
                ListItem(Paragraph(_escape(str(b)), styles["bullet"]), leftIndent=12)
                for b in numbered
                if str(b).strip()
            ]
            if items:
                flowables.append(
                    ListFlowable(
                        items,
                        bulletType="1",
                        bulletFormat="%s.",
                        leftIndent=16,
                    )
                )
                flowables.append(Spacer(1, 4))

        callout = str(section.get("callout") or "").strip()
        if callout:
            flowables.append(Paragraph(_escape(callout), styles["callout"]))

    doc.build(flowables)
    return buf.getvalue()


def render_flyer_pdf(html: str) -> bytes:
    """Render a self-contained HTML flyer to PDF bytes via WeasyPrint."""
    # Import lazily so the rest of the bot works even if WeasyPrint isn't
    # installed yet (helpful during early local development).
    from weasyprint import HTML  # noqa: WPS433 (local import is intentional)

    return HTML(string=html).write_pdf()


def safe_filename(name: str, suffix: str = ".pdf", fallback: str = "document") -> str:
    """Make a filesystem-safe filename out of an arbitrary string."""
    cleaned = "".join(c if c.isalnum() or c in (" ", "-", "_") else "" for c in name)
    cleaned = "_".join(cleaned.split())[:60].strip("_")
    return (cleaned or fallback) + suffix
