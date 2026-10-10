# מאגר משפט נתניהו — Public Knowledge Foundation (V1)

מערכת שהופכת פרוטוקולים רשמיים של ת״פ 67104‑01‑20 לבסיס ידע ציבורי. **כל משפט שמתפרסם מעוגן לעמוד ולשורה בפרוטוקול**, עובר שערי ציטוט ואימות, ומתפרסם רק אחרי ביקורת אנושית.

- מפרט: "מאגר משפט נתניהו — Public Knowledge Foundation, גרסה 2.1"
- הכרעות ארכיטקטורה: `docs/adr/` (0001–0012)

> **מצב:** ארבעה פרוטוקולים אמיתיים (ספטמבר 2025, 550 עמודים) נקלטו ונמדדו. זיהוי הדובר ומיקום הציטוט עברו, צימוד ש/ת (77%) ו־Recall בחיפוש (0.755) **נכשלו**, והתיוג נעשה על ידי AI ולא על ידי בני אדם. ראו `docs/pilot-report.md` ו־`docs/credentials-needed.md`.

## מבנה

```
services/common      ntk_common: מזהים, נרמול עברית, חוזים, PDF→שורות→יחידות→ש/ת, שכבות A/B, שערים, Ask, חיפוש, DB
services/api         FastAPI: Knowledge API ציבורי (/v2/*) + ניהול (/v2/admin/*, חתימת HMAC)
services/worker      Celery: 14 שלבי קליטה עם checkpoints, retries, DLQ, webhooks; CLI ‏trial-knowledge
adapters/project315  ייבוא ייצוא Project 315 עם גרסאות ו־diff
db/                  migrations ‏SQL‑first ‏(Alembic)
contracts/           JSON Schema ‏(ntk-contracts-2.0.json) + openapi.json
wordpress/           תוסף trial-knowledge: הגדרות, העלאה ל־R2, ביקורת ופרסום, 4 בלוקים, דפים ציבוריים
golden/              סט אדברסרי (56), שאלות פיילוט, benchmark חיפוש, דוחות
manifests/           מניפסט פיילוט, registry של טענות
infra/railway/       config‑as‑code ל־api/worker/beat/backup
docs/                התקנה, Railway, R2, runbook, Project 315, credentials, דוח פיילוט
```

## התחלה מהירה

```bash
make dev          # Docker: postgres+pgvector, redis, minio, api, worker, beat
make test         # pytest (179) — דורש Postgres עם pgvector
php wordpress/trial-knowledge/tests/run.php
make plugin-zip   # dist/trial-knowledge-2.1.0.zip
```

פריסה: `docs/install.md` → `docs/railway.md` → `docs/r2.md`.

## עקרונות שמובנים בקוד
- **מקורות בלתי ניתנים לשינוי:** triggers חוסמים מחיקה ושינוי תוכן ב־`source_versions` וב־`source_units` (מותר רק לשנות מצב פרסום). תיקון מקור הוא גרסה חדשה.
- **מזהים דטרמיניסטיים:** אותו PDF תמיד יוצר אותם מזהים, והחישוב זהה ב־Python וב־SQL.
- **שום דבר לא מתפרסם אוטומטית:** הסדר הוא שערים → משימת ביקורת → אישור → פרסום מפורש. כל פרסום מעלה את גרסת הקורפוס ונרשם ב־audit.
- **ניסוח שיפוטי מוגבל:** "בית המשפט קבע" מותר רק כשיש החלטה מאושרת. הערה של שופט אינה החלטה.
- **Ask:**
  - מתקן הנחות שגויות;
  - מסרב להזרקת הנחיות;
  - מחזיר `insufficient_published_evidence` במקום לנחש;
  - בנושאים רגישים מחזיר ציטוטים בלבד, עד שיש ביקורת.
- **מדיניות מודלים:** כל מודל מוגדר במשתני סביבה. מודלי Lite אסורים לסיווג שיפוטי ולאימות, וספק mock אסור בפרסום.
- **סודות:** רק במשתני סביבה. הדפדפן ו־WordPress לא רואים מפתחות R2 או Gemini.
