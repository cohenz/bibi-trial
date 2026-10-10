# מה עדיין נדרש להפעלה בסביבה האמיתית

**איך מעבירים סודות:** אף פעם לא בצ'אט ולא בריפו. מגדירים אותם ב־Railway → Variables, וב־WordPress ב־`wp-config.php`. סודות נבדקים בצד שלכם עם `trial-knowledge storage-check` ו"בדיקת חיבור" בתוסף.

## חוסמים לפיילוט האמיתי

| # | פריט | למה | איפה מגדירים |
|---|---|---|---|
| 1 | **4 קובצי ה־PDF של אפריל 2021** (5, 7, 12 ו־13 באפריל), או גישה מהשרת ל־www.gov.il | ארבעה פרוטוקולים אמיתיים מספטמבר 2025 כבר נקלטו ונמדדו (docs/pilot-report.md), אבל הפיילוט במפרט מוגדר על אפריל 2021, ושם P1/P2 | העלאה דרך מסך "מקורות" בתוסף, או מ־Railway עם `ingest manifests/pilot-april-2021.json` |
| 2 | **מתייגים אנושיים** לאותם קבצים שתויגו על ידי סוכני AI: `golden/labels/sept-2025/*.csv` (300 תורות, 200 זוגות ש/ת, 970 קטעי חיפוש) | מדדי הקבלה מוגדרים מול תיוג אנושי. כרגע הם מבוססים על תיוג AI | אותם קבצים. מעתיקים, ממלאים את עמודות `label_*` ומריצים `label-score` |
| 3 | **מודלים לכל תפקיד**: שמות מודלי Gemini ל־extractor, mapper, judicial_classifier, writer, qa_relation ו־verifier | אין ברירת מחדל בקוד (ADR‑0007). מודל Lite נחסם לסיווג שיפוטי ולאימות | `NTK_MODEL_*` |
| 4 | `GEMINI_API_KEY` | הרצת שכבות A/B ו־Ask | Railway (api + worker) |

## תשתית

| # | פריט | איפה |
|---|---|---|
| 5 | Cloudflare **Account ID** (ל־endpoint) | `S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com` |
| 6 | שם bucket פרטי למקורות, ו־bucket נפרד לגיבויים | `S3_BUCKET`, `BACKUP_BUCKET` |
| 7 | R2 token למקורות (Object Read & Write, מוגבל ל־bucket) | `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` |
| 8 | R2 token לגיבויים (מוגבל ל־bucket הגיבויים) | `BACKUP_ACCESS_KEY_ID`, `BACKUP_SECRET_ACCESS_KEY` |
| 9 | פרויקט Railway ובו Postgres עם pgvector ≥ 0.7 (אם הממד 3072) ו־Redis | docs/railway.md |
| 10 | **הדומיין של ה־API** (למשל `api.<domain>`) | `NTK_PUBLIC_BASE_URL`, permalinks |
| 11 | **כתובת אתר ה־WordPress** | `NTK_CORS_ORIGINS`, CORS של R2 |
| 12 | סוד מפתח שירות ל־WordPress (32+ בתים אקראיים) | `NTK_SERVICE_KEYS` ב־Railway + `TK_API_SECRET` ב־wp-config |
| 13 | סוד webhook | `WP_CALLBACK_SECRET` ב־Railway + `TK_WEBHOOK_SECRET` ב־wp-config |
| 14 | salt ל־hash של כתובות IP | `NTK_IP_HASH_SALT` |

## החלטות מוצר פתוחות

| # | החלטה | ברירת המחדל כרגע |
|---|---|---|
| 15 | **מאמת ממשפחת מודלים שנייה** (למשל Claude או OpenAI) | בלי מאמת כזה, כל טענה רגישה ותשובת Ask רגישה דורשות ביקורת אנושית (ADR‑0007). זה בטוח, אבל איטי |
| 16 | ממד embeddings: 768, 1536 או 3072 | 3072 דורש halfvec (pgvector ≥ 0.7). חייב להיקבע **לפני** ה־migration הראשונה |
| 17 | **Project 315**: קובץ ייצוא או רשומות לדוגמה, רשימת ערכי סיווג, ואישור שימוש | המתאם עובד על fixture סינתטי בלבד (docs/project315-adapter.md) |
| 18 | מי מחזיק ב־`tk_publish` | Administrator בלבד |
| 19 | נוסח עמוד השקיפות ("release notes") כ־disclaimer קבוע באתר | יש טיוטה במסמך נפרד |
