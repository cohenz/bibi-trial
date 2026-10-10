# Railway — פריסה ותפעול

מקור לסכמת ההגדרות: https://docs.railway.com/config-as-code/reference

## שירותים

| שירות | קובץ config | Public | פקודה |
|---|---|---|---|
| api | `infra/railway/api.railway.json` | כן (domain) | `uvicorn ntk_api.app:app … --workers 2`, pre‑deploy: `trial-knowledge migrate` |
| worker | `infra/railway/worker.railway.json` | לא | `celery -A ntk_worker.celery_app worker -Q ntk` |
| beat | `infra/railway/beat.railway.json` | לא | `celery … beat` (webhooks כל 30 שניות, כמופע יחיד) |
| backup | `infra/railway/backup.railway.json` | לא | cron `17 2 * * *`: הרצת `backup.sh` (pg_dump → R2) |
| Postgres | תבנית Railway | לא | PG16 עם pgvector, pg_trgm, btree_gist (נוצרים ב־migration) |
| Redis | תבנית Railway | לא | broker ו־rate limits |

בכל שירות: Settings → Config-as-code → נתיב הקובץ. שירותי api, worker ו־beat נבנים מ־`Dockerfile.base` (Python 3.12 + tesseract‑heb). backup נבנה מ־`infra/railway/Dockerfile.backup`.

**beat חייב לרוץ במופע אחד בלבד.** שני מופעים ישלחו כל webhook פעמיים. ה־outbox אמנם נועל שורות, אבל אין סיבה לבזבז.

## רשת פרטית
- worker, beat, Postgres ו־Redis ללא public domain. התקשורת ביניהם עוברת ב־`*.railway.internal` דרך reference variables (`${{Postgres.DATABASE_URL}}`, `${{Redis.REDIS_URL}}`).
- ה־API הוא השירות הציבורי היחיד. ממשק הניהול (`/v2/admin/*`) מוגן בחתימת HMAC, ולכן אינו צריך הגנת רשת נוספת. אם רוצים שכבה נוספת, אפשר להגביל את `/v2/admin` ב־Cloudflare לכתובת שרת ה־WordPress.
- ה־API סומך רק על הכתובת **הימנית** ב־`X-Forwarded-For`, כלומר זו ש־Railway מוסיף (ADR‑0004).

## משתני סביבה
הרשימה המלאה ב־`.env.example`. שימו לב:
- `NTK_ENV=production` מפעיל חסימות: ספק mock אסור בפרסום, `local_path` אסור, ו־PDF שהכותרת שלו מציינת תיק אחר נכשל בשלב segment (`case_number_mismatch`).
- `NTK_EMBEDDING_DIM` נקבע **לפני ה־migration הראשונה**. שינוי מאוחר דורש migration ידנית ובניית embeddings מחדש.
- ב־Railway מגדירים סודות כ־Variables (sealed). הם לא נכנסים לריפו, ו־`Settings` מסתיר אותם בלוגים.

## Health checks
- `/v2/health`: התהליך חי.
- `/v2/ready`: DB, סכמה ו־Redis. זה ה־healthcheck של ה־deploy. deploy שלא עובר אותו תוך 60 שניות לא מקבל traffic.

## Migrations
- `preDeployCommand` מריץ `trial-knowledge migrate` (Alembic, SQL‑first) לפני שהגרסה החדשה מקבלת traffic.
- כל migration היא forward‑only ו־additive (ADR‑0010). לפני migration שמשנה נתונים קיימים, מריצים backup ידני.

## לוגים
- שורה אחת לכל בקשה: method, path, status ומשך. בלי body, בלי query string, בלי טקסט השאלה ב־Ask ובלי כותרות חתימה.
- שגיאות מודל נשמרות ב־`ntk.model_runs` (validation_errors), לא בלוג.
- זמן השמירה נקבע לפי תוכנית Railway. למעקב ארוך יותר אפשר להוסיף log drain.

## Retry ו־DLQ
- כל שלב רשום ב־`ntk.ingestion_stages` עם checkpoint. משימה שנפלה ממשיכה מהשלב שנכשל.
- Celery: `acks_late`, ועד 3 ניסיונות עם backoff אקספוננציאלי לשגיאות retryable (רשת, R2, 429/503 של המודל).
- אחרי שהניסיונות נגמרו נוצרת שורה ב־`ntk.dead_letters`, המשימה מסומנת `failed`, וכפתור "ניסיון חוזר" ב־WordPress מפעיל `POST /v2/admin/ingestion-jobs/{id}/retry`.

## גיבויים
- שירות backup: pg_dump יומי ל־bucket נפרד ב־R2 (`BACKUP_BUCKET`), עם token נפרד שמוגבל ל־bucket הזה.
- קובצי המקור עצמם כבר ב־R2, מוגנים ב־Bucket Lock ובמפתח מבוסס SHA‑256.
- **שחזור:** DB ריק → `gunzip -c ntk-<ts>.sql.gz | psql "$DATABASE_URL"` → `trial-knowledge migrate`. מומלץ לתרגל זאת פעם ברבעון על סביבת staging.

## Rollback
1. Railway → Deployments → הגרסה הקודמת → Redeploy.
2. migrations לא מתגלגלות אחורה. מאחר שהן additive, קוד ישן ממשיך לעבוד על סכמה חדשה.
3. כדי להסיר תוכן שפורסם בטעות, לא עושים rollback לקוד. משתמשים ב־unpublish (`POST /v2/admin/artifacts/{id}/unpublish`), שמעלה את גרסת הקורפוס ושולח webhook לניקוי המטמון ב־WordPress.
