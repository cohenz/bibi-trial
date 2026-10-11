# מצב הפריסה וההעברה לשיחה חדשה — 11.10.2026

המסמך הזה מאפשר להמשיך את העבודה בשיחה חדשה בלי לאבד הקשר. **אין בו סודות.** הסודות שמורים רק ב־Railway Variables ובהגדרות התוסף ב־WordPress.

## איפה כל דבר נמצא

| רכיב | מיקום |
|---|---|
| קוד | GitHub [cohenz/bibi-trial](https://github.com/cohenz/bibi-trial), ענף `main`. אפליקציית Claude ב־GitHub מותקנת על ה־repo הזה בלבד, עם הרשאת push |
| Railway | פרויקט `bibi-trial`, סביבה `production`. Project ID `70fde9b1-8af2-44c4-a771-6995bcc45074`, Environment ID `77764ba9-1b65-405d-922e-8cfed4c30cf5` |
| API ציבורי | https://api-production-6562.up.railway.app (`/v2/ready`, `/docs`) |
| אחסון | Cloudflare R2. Account `b3aa40c092c2bbcc8c4c1201b53a4946`. Buckets `ntk-sources` (פרטי, CORS ל־`https://shomersaf.com`, Bucket Lock על `sources/`) ו־`ntk-backups` |
| WordPress | https://shomersaf.com/trial/. התוסף `trial-knowledge` 2.1.0 מותקן, מוגדר, ו"בדיקת חיבור" עוברת |
| Webhook | `https://shomersaf.com/trial/wp-json/trial-knowledge/v1/webhook`, מוגדר ב־worker וב־beat |

## שירותי Railway

| שירות | Service ID | מקור | הגדרות |
|---|---|---|---|
| postgres | `b03a4ac5-f086-47d5-b322-468fc51e6314` | image `pgvector/pgvector:pg16` | volume `/var/lib/postgresql/data`. משתנים: `POSTGRES_USER=postgres`, `POSTGRES_DB=ntk`, `PGDATA=…/pgdata`. הסיסמה נוצרה אקראית בדפדפן |
| redis | `5d414dd5-8824-4f48-9db2-8fa59262fd87` | image `redis:7-alpine` | volume `/data`. start: `redis-server --requirepass $REDIS_PASSWORD --appendonly yes` |
| api | `bc38fe78-ed4b-474c-b84b-714a269da527` | repo `cohenz/bibi-trial` | `Dockerfile.base`. pre‑deploy: `trial-knowledge migrate`. start: `/bin/sh -c "exec uvicorn … --port ${PORT:-8000} …"`. healthcheck `/v2/ready` |
| worker | `04d3035c-c44b-4487-8669-4ffaba94b312` | repo | start: `celery -A ntk_worker.celery_app worker -Q ntk --concurrency 2` |
| beat | `9d413561-a1b3-4ea9-82b6-1d25a258b2a5` | repo | start: `celery -A ntk_worker.celery_app beat`. **מופע אחד בלבד** |

**משתנים:**
- **משותפים (Shared Variables):** `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` ו־`GEMINI_API_KEY`. כולם מוזנים, אבל במפתח Gemini אין יתרה, ראו למטה.
- **api ו־worker מפנים אליהם:**
  - `S3_ACCESS_KEY_ID=${{shared.R2_ACCESS_KEY_ID}}`;
  - `S3_SECRET_ACCESS_KEY=${{shared.R2_SECRET_ACCESS_KEY}}`.
- **ב־api, worker ו־beat:**
  - `NTK_ENV=production`;
  - `DATABASE_URL` ו־`REDIS_URL`, דרך reference variables לשירותים postgres ו־redis;
  - `NTK_EMBEDDING_DIM=768`;
  - `NTK_MODEL_PROVIDER=mock`, `NTK_EMBEDDING_PROVIDER=mock` (עדיין);
  - `S3_ENDPOINT_URL`, `S3_BUCKET=ntk-sources`, `S3_REGION=auto`;
  - `NTK_PUBLIC_BASE_URL`;
  - `RAILWAY_DOCKERFILE_PATH=Dockerfile.base`.
- **ב־api בלבד:** `NTK_SERVICE_KEYS` (המפתח `wp-bibi`, scope `admin:all`), `NTK_IP_HASH_SALT`, `NTK_CORS_ORIGINS=https://shomersaf.com`.
- **ב־worker וב־beat:** `WP_CALLBACK_URL`, `WP_CALLBACK_SECRET`.

## מה נבדק בייצור
- כל חמשת השירותים רצים. migrations רצו, ו־`/v2/ready` מחזיר ok.
- קריאה חתומה של התוסף (`whoami`) עוברת, גם מתוך WordPress וגם מבחוץ.
- presign מול R2 עובד, כלומר המפתחות וה־bucket תקינים.
- **מקצה לקצה:** פרוטוקול 15.9.2025 (0421) הועלה דרך התוסף, ישירות מהדפדפן ל־R2, ועבר את 14 השלבים ב־worker. התוצאה: 93 עמודים, 1,394 קטעים, 242 זוגות ש/ת, 44 chunks. אלה בדיוק המספרים מהבדיקה המקומית. נפתחו 22 משימות ביקורת. **שום דבר לא פורסם**, כי פרסום דורש אישור אנושי.

## פתוח — לפי סדר
1. **Gemini.** המפתח תקין ויש לו גישה למודלים, אבל Google מחזיר `402 prepayment credits are depleted`. אחרי שתיטען יתרה:
   - **בדיקה:** בדיקת קריאה אמיתית מהדפדפן, בלי להעביר את המפתח דרך הצ'אט.
   - **הגדרת ספקים:** ב־api וב־worker: `NTK_MODEL_PROVIDER=gemini`, `NTK_EMBEDDING_PROVIDER=gemini`, `NTK_EMBEDDING_MODEL=gemini-embedding-001`, `GEMINI_API_KEY=${{shared.GEMINI_API_KEY}}`.
   - **מודלים:** `NTK_MODEL_EXTRACTOR`, `MAPPER`, `JUDICIAL_CLASSIFIER`, `WRITER`, `QA_RELATION` ו־`VERIFIER` מקבלים כולם `gemini-3.8-flash`. אסור Lite לסיווג שיפוטי ולאימות.
   - **מה מריצים אחר כך:**
     - קליטה מחדש של הפרוטוקולים;
     - בניית ה־embeddings;
     - benchmark החיפוש (`golden/search-bench-real-sept2025-v1.json`), עכשיו עם וקטורים אמיתיים;
     - סטי השאלות.
   - המודלים הזמינים במפתח אומתו ב־10.10.2026: `gemini-3.8-flash`, `gemini-3.1-pro-preview`, `gemini-embedding-001`, `gemini-embedding-2`.
2. **שלושת הפרוטוקולים הנוספים** (0422–0424): להעלות דרך מסך "מקורות וקליטה" בתוסף.
3. **ביקורת ופרסום ראשון:** במסך "ביקורת ופרסום". אחר כך לבדוק את הדפים הציבוריים `/trial/hearing/...` ואת הבלוקים.
4. **שירות backup:** pg_dump לילי ל־`ntk-backups`. צריך token נפרד ב־R2, מוגבל ל־`ntk-backups`. מקימים מ־`infra/railway/Dockerfile.backup` עם cron `17 2 * * *`.
5. **עדכון התיעוד:** Railway הפסיק לתמוך ב־config‑as‑code (`railway.json`) ועבר ל־`.railway/railway.ts`. כרגע ההגדרות נקבעו ישירות בכל שירות, והקבצים ב־`infra/railway/*.json` משמשים כתיעוד בלבד.

## לקחים טכניים (חשוב לשיחה הבאה)
- **אין גישה מהסביבה ל־railway.com ול־Cloudflare.** את Railway מנהלים דרך GraphQL `https://backboard.railway.com/graphql/v2`, מתוך לשונית Railway המחוברת בחלונית הדפדפן (javascript, `credentials:"include"`). למשל `variableCollectionUpsert`, `serviceInstanceUpdate`, `serviceInstanceDeployV2` ו־`environmentStagedChanges` / `environmentPatchCommitStaged`.
- **`serviceInstanceUpdate` עם `builder` נכשל.** במקום זה מגדירים `RAILWAY_DOCKERFILE_PATH`.
- **פקודות start רצות ב־exec form.** כדי שמשתנים כמו `$PORT` ימולאו, צריך לעטוף ב־`/bin/sh -c`.
- **ה־API הציבורי נגיש מהסביבה,** כך שאפשר לשלוח קריאות admin חתומות עם `tools/e2e_live.py` או עם `ntk_api.security.sign`. הסוד נמצא ב־`NTK_SERVICE_KEYS` ב־Railway.
- **התחברות ל־Cloudflare נכשלת בחלונית הדפדפן** (Turnstile). כל עבודה מול Cloudflare נעשית בדפדפן הרגיל של המשתמש, לפי הוראות.
- **בחירת קבצים ב־WordPress** נעשית על ידי המשתמש. אין לי גישה לבורר הקבצים.
- **סודות:** אף פעם לא בצ'אט. סודות של צד שלישי מדביק המשתמש ישירות ב־Railway. סודות שאני יוצר (מפתח השירות וסוד ה־webhook) הוזנו ישירות ל־Railway ולתוסף.
