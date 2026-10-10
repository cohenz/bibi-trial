# Project 315 adapter

## מה ממומש
- קלט: JSON (מערך, או אובייקט עם `events`/`items`/`data`) או CSV.
- שני מצבי מיפוי:
  - **canonical snapshot:** מפתחות בשמות שדות spec §5.2.
  - **mapping file:** `{"canonical_field": "שם עמודה במקור"}`.
- לכל ייבוא נשמרים:
  - snapshot של קובץ הייצוא כ־SourceVersion (tier 3, `source_owner=Project 315`, `source_stance=defense-supportive`) עם SHA‑256;
  - `raw_payload` ו־hash לכל רשומה;
  - גרסת parser;
  - מקור הייבוא.
- **שינוי ברשומה אינו דורס אותה.** נוצרת שורה ב־`project315_event_versions` עם diff, ושינוי סיווג מייצר אזהרה.
- `court_record_status` של כל אירוע ושל כל URL מתחיל תמיד ב־`external`. היבוא לעולם אינו מעלה אותו.
- `court_mentions` מקושרים רק ל־SourceUnit קיים. `witness_mentions` מקושרים רק ל־entity מזוהה. כל השאר נרשם כאזהרה ואינו נשמר כטקסט חופשי.
- **כשל:** חסר event id, חסר עמוד מקור, חסר סיווג, או רשומה ריקה.
- **אזהרות:** URL שבור, אירוע כפול, תאריך לא מפוענח, ערך `netanyahu_involvement` לא מוכר (נשמר `null`), אירוע בלי מקור מקושר, ושינוי סיווג.
- **מדגם בדיקה עצמאית:** 10% דטרמיניסטי מקבל review task. כל אירוע שמצוטט ב־Claim Card ציבורי נבדק לפני פרסום.

## מה נדרש כדי להשלים את המיפוי לייצוא אמיתי
1. **קובץ ייצוא אמיתי**, או 20 רשומות לדוגמה, בפורמט שהפרויקט מספק (JSON/CSV/HTML).
2. לכל שדה: שם העמודה בפועל, ואם יש כמה ערכים, כיצד הם מופרדים.
3. **רשימת ערכי הסיווג** בדיוק כפי שהם מופיעים, למשל "הדרישה לא נענתה", "היענות לא חריגה", "נתניהו לא מעורב בדרישה", "היענות חריגה".
4. כיצד מצוינת מעורבות נתניהו בייצוא, ומיפוי שלה לערכים `direct / inferred / staff / third_party / unknown`. בלי מיפוי מאושר הערך נשמר `null`.
5. פורמט התאריכים ופורמט טווחים.
6. מזהה אירוע יציב, או URL קנוני לכל אירוע.
7. **אישור תנאי שימוש** בנתונים מהפרויקט.

## הרצה
```bash
trial-knowledge p315-import export.json --mapping p315-mapping.json --source "the315.org export 2026-10"
trial-knowledge p315-import tests/fixtures/project315_sample_synthetic.json --synthetic   # fixture סינתטי
```
או דרך ה־API: `POST /v2/admin/project315/import`.
