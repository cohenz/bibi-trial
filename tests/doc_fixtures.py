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

# SYNTHETIC indictment with two counts, a witness list and an appendix (fictional people and events)
INDICTMENT = [[
    "בבית המשפט המחוזי בירושלים ת\"פ 67104-01-20",
    "",
    "כתב אישום",
    "",
    "חלק כללי",
    "",
    "1. הנאשם פלוני אלמוני כיהן כשר התקשורת בין השנים 2014 ו-2017 והיה עובד ציבור.",
    "",
    "2. הנאשם יוסי כהן היה בעל השליטה בחברת התקשורת אופק בע\"מ ובאתר החדשות גלים.",
    "",
    "האישום הראשון – פרשת 4000 (הנאשמים אלמוני וכהן)",
    "",
    "3. ביום 12.3.2015 נפגש הנאשם כהן עם דוד לוי, מנכ\"ל אתר גלים, וביקש ממנו לשנות כותרות לטובת הנאשם אלמוני.",
    "",
    "4. ביום 20.6.2016 חתם הנאשם אלמוני על החלטה רגולטורית שהיטיבה עם חברת אופק, כמפורט בנספח א'.",
], [
    "הוראות החיקוק לפיהן מואשמים הנאשמים:",
    "",
    "5. הנאשם אלמוני: לקיחת שוחד לפי סעיף 290 לחוק העונשין; מרמה והפרת אמונים לפי סעיף 284 לחוק העונשין.",
    "",
    "האישום השני – פרשת 2000 (הנאשם אלמוני)",
    "",
    "6. ביום 1.12.2014 נפגש הנאשם אלמוני עם מו\"ל עיתון יומי ושוחח עמו על הצעת חוק.",
    "",
    "7. הנאשם אלמוני: מרמה והפרת אמונים לפי סעיף 284 לחוק העונשין.",
    "",
    "ירושלים, 1 בדצמבר 2019",
    "",
    "עדי התביעה:",
    "",
    "1. דוד לוי",
    "",
    "נספח א' – דוגמאות לבקשות שינוי כותרות",
    "",
    "8. ביום 3.4.2015 ביקש הנאשם כהן מדוד לוי להסיר ידיעה מהאתר.",
]]
