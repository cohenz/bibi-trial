"""Generate a SYNTHETIC Hebrew court-protocol PDF for tests.

All names, the case number and the content are fictional. The layout mimics
Israeli court protocols: RTL text, printed line numbers in the left margin,
a repeated page header and a page footer. Hebrew is drawn in visual order
(as most PDF producers store it) so the extractor's RTL repair is exercised.

Usage: python tools/make_fixture_protocol.py tests/fixtures/synthetic_protocol.pdf
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "common"))

from ntk_common.hebrew import reverse_visual_line  # noqa: E402

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]

HEADER = 'ת"פ 99999-01-20 מדינת ישראל נ\' פלוני ואח\''
LINES_PER_PAGE = 28

BODY: list[str] = [
    "בית המשפט המחוזי בתל אביב-יפו",
    HEADER,
    "12 אפריל 2021",
    "לפני כב' השופטת שרה כהן, אב\"ד",
    "כב' השופט יוסף לוי",
    "כב' השופט אבי מזרחי",
    "המאשימה מדינת ישראל",
    "נגד",
    "הנאשמים 1. ראובן פלוני 2. שמעון אלמוני",
    "נוכחים:",
    "ב\"כ המאשימה עו\"ד רחל אדלר, עו\"ד דן ברק",
    "ב\"כ הנאשם 1 עו\"ד משה גולן, עו\"ד נועה שחר",
    "ב\"כ הנאשם 2 עו\"ד יעל רוזן",
    "פרוטוקול",
    "כב' השופטת כהן: בוקר טוב. אנחנו ממשיכים היום בשמיעת הראיות.",
    "עו\"ד אדלר: בוקר טוב גבירתי. המאשימה מבקשת להמשיך בעדותו של העד.",
    "עו\"ד גולן: אין לנו התנגדות להמשך, אך נבקש הפסקה בשעה אחת עשרה.",
    "כב' השופטת כהן: בסדר. נמשיך.",
    "העד מר דוד לוי, לאחר שהוזהר כדין להגיד את האמת, משיב לשאלות עו\"ד אדלר בחקירה ראשית:",
    "ש. אתה עבדת בחברה בשנים 2014 עד 2016?",
    "ת. כן.",
    "ש. ומה היה תפקידך באותה תקופה?",
    "ת. הייתי מנהל המחלקה. אחראי על הקשר עם הלקוחות ועל",
    "הדיווח להנהלה. זה כלל גם פגישות שבועיות עם המנכ\"ל.",
    "ש. נכון שבאותה תקופה קיבלת הנחיות ישירות מהנאשם 1?",
    "ת. נכון, אבל לא תמיד. לפעמים ההנחיות הגיעו דרך אנשים אחרים.",
    "ש. האם נכחת בפגישה שהתקיימה במאי 2015?",
    "ת. אני לא זוכר את הפגישה הזאת.",
    "ש. נכון שבפגישה ההיא הוצג לך מסמך ת/12?",
    "עו\"ד גולן: התנגדות, השאלה מדריכה.",
    "ת. לא. לא הוצג לי שום מסמך.",
    "ש. תאר לבית המשפט מה קרה אחרי הפגישה.",
    "ת. אחרי הפגישה חזרתי למשרד והתקשרתי לסגן שלי. סיפרתי לו מה",
    "שנאמר ובקשתי שיכין סיכום. הוא הכין סיכום וזה נשלח להנהלה",
    "באותו ערב. אני זוכר את זה כי זה היה יום לפני החג.",
    "כב' השופט לוי: רק להבהרה, הסיכום נשלח על ידך או על ידי הסגן?",
    "ת. על ידי הסגן.",
    "ש. האם ידעת שהנאשם 1 ביקש לשנות את הכותרת? ת. כן.",
    "ש. ממש לא היה ברור לך מי ביקש?",
    "ת. מה זאת אומרת?",
    "ש. אשאל אחרת. מי ביקש לשנות את הכותרת?",
    "ת. בגדול אני חושב שזה הגיע מהדובר, אבל אני לא בטוח.",
    "החלטה",
    "ההתנגדות נדחית. השאלה נוסחה באופן פתוח מספיק, והעד רשאי להשיב לה.",
    "ניתנה והודעה היום, 12 אפריל 2021, במעמד הנוכחים.",
    "חקירה נגדית ע\"י עו\"ד גולן:",
    "ש. אתה מסכים שלא ראית אף פעם את הנאשם 1 נותן הוראה ישירה?",
    "ת. נכון.",
    "ש. ונכון שכל מה שאתה יודע על ההוראות הוא מפי אחרים?",
    "ת. לא נכון. היו פעמים שראיתי מיילים.",
    "ש. מיילים ששלח הנאשם 1 בעצמו?",
    "ת. לא זכור לי מי שלח אותם.",
    "כב' השופטת כהן: נעשה כאן הפסקה של עשר דקות.",
    "(הפסקה)",
    "עו\"ד גולן: אני ממשיך בחקירה הנגדית.",
    "ש. בחקירה במשטרה אמרת שהפגישה הייתה ביוני ולא במאי, נכון?",
    "ת. יכול להיות. אני לא זוכר בדיוק את החודש.",
    "ש. אז ייתכן שהפגישה לא התקיימה במאי כלל?",
    "ת. ייתכן.",
]


def build(out_path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    font_path = next((p for p in FONT_CANDIDATES if Path(p).exists()), None)
    if not font_path:
        raise SystemExit("no Hebrew-capable TTF font found")
    pdfmetrics.registerFont(TTFont("HebFont", font_path))
    width, height = A4
    c = canvas.Canvas(str(out_path), pagesize=A4, invariant=1)
    c.setTitle("SYNTHETIC FIXTURE - fictional protocol")
    c.setCreator("trial-knowledge tests")
    pages = [BODY[i : i + LINES_PER_PAGE] for i in range(0, len(BODY), LINES_PER_PAGE)]
    total = len(pages)
    for pno, page_lines in enumerate(pages, start=1):
        c.setFont("HebFont", 9)
        # repeated header (unnumbered)
        c.drawRightString(width - 60, height - 40, reverse_visual_line(HEADER))
        y = height - 75
        for i, text in enumerate(page_lines, start=1):
            c.setFont("HebFont", 8)
            c.drawString(28, y, str(i))  # printed line number in left margin
            c.setFont("HebFont", 11)
            c.drawRightString(width - 60, y, reverse_visual_line(text))
            y -= 24
        c.setFont("HebFont", 9)
        c.drawCentredString(width / 2, 30, reverse_visual_line(f"עמוד {pno} מתוך {total}"))
        c.showPage()
    c.save()


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "tests" / "fixtures" / "synthetic_protocol.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    build(out)
    print(f"wrote {out}")
