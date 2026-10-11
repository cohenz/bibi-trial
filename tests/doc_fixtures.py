"""Small SYNTHETIC Hebrew court documents (decision, motion, …) for inbox tests. All content is fictional."""

from __future__ import annotations

import io

from ntk_common.hebrew import reverse_visual_line

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]


def make_pdf(pages: list[list[str]]) -> bytes:
    """One list of lines per page; a blank string leaves a paragraph gap."""
    from pathlib import Path

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    font = next(p for p in FONT_CANDIDATES if Path(p).exists())
    if "HebDoc" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("HebDoc", font))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    width, height = A4
    for lines in pages:
        y = height - 70
        for text in lines:
            if text:
                c.setFont("HebDoc", 11)
                c.drawRightString(width - 60, y, reverse_visual_line(text))
                y -= 18
            else:
                y -= 30
        c.showPage()
    c.save()
    return buf.getvalue()


def blank_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    c.rect(100, 100, 200, 200)
    c.showPage()
    c.save()
    return buf.getvalue()


DECISION = [[
    "בית המשפט המחוזי בירושלים",
    "ת\"פ 67104-01-20 מדינת ישראל נ' פלוני ואח'",
    "",
    "החלטה",
    "",
    "1. לפניי בקשת ההגנה לדחיית מועד הדיון שנקבע ליום 20 באוקטובר 2025.",
    "המאשימה הודיעה כי היא מתנגדת לבקשה ופירטה את נימוקיה בתגובתה.",
    "",
    "2. לאחר שעיינתי בטענות הצדדים, הבקשה נדחית. הדיון יתקיים במועדו.",
    "",
    "ניתנה היום, 12 באוקטובר 2025, בהעדר הצדדים.",
]]

MOTION = [[
    "בבית המשפט המחוזי בירושלים",
    "ת\"פ 67104-01-20",
    "",
    "בקשה לדחיית מועד דיון",
    "",
    "1. הנאשם 1 מבקש בזאת לדחות את מועד הדיון הקבוע ליום 20 באוקטובר 2025.",
    "2. הטעם לבקשה הוא היקף חומר החקירה שהועבר לאחרונה להגנה.",
    "",
    "ב\"כ הנאשם 1",
], [
    "3. המאשימה טרם הודיעה על עמדתה לבקשה.",
    "",
    "היום 10 באוקטובר 2025",
]]

FOREIGN_DECISION = [[
    "בית משפט השלום בתל אביב",
    "ת\"פ 11111-02-19 מדינת ישראל נ' אחר",
    "",
    "החלטה",
    "",
    "התיק נדחה למועד אחר.",
    "ניתנה היום, 1 בינואר 2020.",
]]
