# מצב הפריסה וההעברה לשיחה חדשה — 11.10.2026 (אחרי Gemini ותיבת הקליטה)

המסמך הזה מאפשר להמשיך את העבודה בשיחה חדשה בלי לאבד הקשר. **אין בו סודות.** הסודות שמורים רק ב־Railway Variables ובהגדרות התוסף ב־WordPress.

## איפה כל דבר נמצא

| רכיב | מיקום |
|---|---|
| קוד | GitHub [cohenz/bibi-trial](https://github.com/cohenz/bibi-trial), ענף `main`. אפליקציית Claude ב־GitHub מותקנת על ה־repo הזה בלבד, עם הרשאת push |
| Railway | פרויקט `bibi-trial`, סביבה `production`. Project ID `70fde9b1-8af2-44c4-a771-6995bcc45074`, Environment ID `77764ba9-1b65-405d-922e-8cfed4c30cf5` |
| API ציבורי | https://api-production-6562.up.railway.app (`/v2/ready`, `/docs`) |
| אחסון | Cloudflare R2. Account `b3aa40c092c2bbcc8c4c1201b53a4946`. Buckets `ntk-sources` (פרטי, CORS ל־`https://shomersaf.com`, Bucket Lock על `sources/`) ו־`ntk-backups` |
| WordPress | https://shomersaf.com/trial/. התוסף `trial-knowledge` **2.2.1 מותקן** (פרוטוקול מלא, דפי מסמכים, `[tk_documents]`). **2.2.2** (ציטוטים קומפקטיים, תגי אישר/הכחיש) נשלחה למשתמש להתקנה: `dist/trial-knowledge-2.2.2.zip`. **עמוד הבית** (11.10): עמוד 9, "משפט נתניהו — המאגר", בכתובת `/trial/trial/`, עם `[tk_ask]`, `[tk_hearing_timeline]` ו־`[tk_documents]` |
| דפים ציבוריים | `https://shomersaf.com/trial/trial/hearing/<hr_id>/`. ה־slug הציבורי `trial` יושב מתחת להתקנת WordPress ב־`/trial/`, ולכן הוא מופיע פעמיים. נבדק: `hr_a52174a761df72d3aba0325a7e` (15.9) מוצג עם תאריך ועדים, ו"טרם פורסם סיכום" |
| Webhook | `https://shomersaf.com/trial/wp-json/trial-knowledge/v1/webhook`, מוגדר ב־worker וב־beat |

## שירותי Railway

| שירות | Service ID | מקור | הגדרות |
|---|---|---|---|
| postgres | `b03a4ac5-f086-47d5-b322-468fc51e6314` | image `pgvector/pgvector:pg16` | volume `/var/lib/postgresql/data`. משתנים: `POSTGRES_USER=postgres`, `POSTGRES_DB=ntk`, `PGDATA=…/pgdata`. הסיסמה נוצרה אקראית בדפדפן |
| redis | `5d414dd5-8824-4f48-9db2-8fa59262fd87` | image `redis:7-alpine` | volume `/data`. start: `redis-server --requirepass $REDIS_PASSWORD --appendonly yes` |
| api | `bc38fe78-ed4b-474c-b84b-714a269da527` | repo `cohenz/bibi-trial` | `Dockerfile.base`. pre‑deploy: `trial-knowledge migrate`. start: `/bin/sh -c "exec uvicorn … --port ${PORT:-8000} …"`. healthcheck `/v2/ready`. **פרוס: `4f2797b`** (migrations 0009–0010). `NTK_INBOX_AUTO_PROCESS=true`, `NTK_INBOX_DELETE_DUPLICATES=true` |
| worker | `04d3035c-c44b-4487-8669-4ffaba94b312` | repo | start: `celery -A ntk_worker.celery_app worker -Q ntk --concurrency 2`. **פרוס: `4f2797b`**. `NTK_INBOX_AUTO_PROCESS=true`, `NTK_INBOX_DELETE_DUPLICATES=true` |
| beat | `9d413561-a1b3-4ea9-82b6-1d25a258b2a5` | repo | start: `celery -A ntk_worker.celery_app beat`. **מופע אחד בלבד.** **פרוס: `dd3488f`**. מתזמן webhooks כל 30 שניות, וסריקת inbox יומית ב־02:47 UTC |

**Railway לא פורס אוטומטית ב־push.** פריסה נעשית ב־`serviceInstanceDeployV2(serviceId, environmentId, commitSha)`. ה־pre‑deploy של api מריץ migrations, כולל 0005 (`ntk.evaluation_runs`) ו־0006 (`ntk.inbox_items`, `ntk.inbox_scans`, וסוגי מקור `response`, `notice` ו־`affidavit`).

**משתנים:**
- **משותפים (Shared Variables):** `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `GEMINI_API_KEY`. ב־Gemini יש יתרה, והוא נבדק מהדפדפן ב־11.10: ג'נרציה ו־embeddings מחזירים 200.
- **api ו־worker מפנים אליהם:**
  - `S3_ACCESS_KEY_ID=${{shared.R2_ACCESS_KEY_ID}}`;
  - `S3_SECRET_ACCESS_KEY=${{shared.R2_SECRET_ACCESS_KEY}}`;
  - `GEMINI_API_KEY=${{shared.GEMINI_API_KEY}}`.
- **מודלים ב־api וב־worker:**
  - `NTK_MODEL_PROVIDER=gemini`, `NTK_EMBEDDING_PROVIDER=gemini`;
  - `NTK_EMBEDDING_MODEL=gemini-embedding-001`, `NTK_EMBEDDING_DIM=768`;
  - `NTK_MODEL_EXTRACTOR`, `MAPPER`, `JUDICIAL_CLASSIFIER`, `WRITER`, `QA_RELATION` ו־`VERIFIER` כולם `gemini-3.8-flash`.
  - `/v2/admin/registry` מחזיר `uses_mock: false` ו־`single_family: true`. כלומר, כל פריט רגיש עובר לבדיקה אנושית.
- **ב־beat:** עדיין `NTK_MODEL_PROVIDER=mock`. beat לא קורא למודלים.
- **ב־api, worker ו־beat:**
  - `NTK_ENV=production`;
  - `DATABASE_URL` ו־`REDIS_URL`, דרך reference variables לשירותים postgres ו־redis;
  - `S3_ENDPOINT_URL`, `S3_BUCKET=ntk-sources`, `S3_REGION=auto`;
  - `NTK_PUBLIC_BASE_URL`;
  - `RAILWAY_DOCKERFILE_PATH=Dockerfile.base`.
- **ב־api בלבד:**
  - `NTK_SERVICE_KEYS`: המפתח `wp-bibi`, scope `admin:all`, של התוסף;
  - `NTK_SERVICE_KEYS_EXTRA`: המפתח `claude-ops`, scopes `admin:read`, `admin:ingest` ו־`admin:publish`. נוצר ב־11.10 לעבודה של Claude באישור המשתמש. **ביטול:** מוחקים את המשתנה ופורסים את api;
  - `NTK_IP_HASH_SALT`, `NTK_CORS_ORIGINS=https://shomersaf.com`.
- **ב־worker וב־beat:** `WP_CALLBACK_URL`, `WP_CALLBACK_SECRET`.

## נקודות כניסה — מדריכים (ADR‑0015, 11.10.2026 אחה"צ)
- **פרסום מסמכים:** בקשות, תגובות והודעות מתפרסמים אוטומטית כשמספר התיק מודפס עליהם. 11 כאלה פורסמו ידנית (cv-000039–49). כתב האישום (`sv_eaad25c9b5be51fb4e1bf55125`, 1.12.2019, 77 עמ') פורסם (cv-000050). בקשה 1004 (בזק) לא פורסמה: אין עליה מספר תיק.
- **עמודי WordPress חדשים:** `/trial/decisions/` (39), `/trial/motions/` (40), `/trial/responses/` (41), `/trial/notices/` (42).
- **קליטה אוטומטית מלאה:** `NTK_INBOX_AUTO_PROCESS=true` ב־api וב־worker. הסריקה היומית קולטת מיד.
- **מדריכים:** נבנו 14 (`POST /v2/admin/guides/build`): סקירת כתב האישום, תיקים 4000/2000/1000 ו־10 עדים. כולם `human_review_required`, ממתינים לאישור המשתמש בתור הבדיקה. API ציבורי: `/v2/guide`, `/v2/guide/cases/{key}`, `/v2/guide/witnesses/{slug}`, `/v2/guide/timeline`, `/v2/glossary` (`docs/guides-api.md`).
- **נספחי כתב האישום:** לא שויכו לתיקים, כי ההפניה כתובה `כנספח "א"`. תוקן ופורס ב־`e20e368`. מדריכי 4000 ו־1000 נבנו מחדש.
- **כפילויות (`e20e368`):**
  - עותק זהה נמחק אוטומטית מ־`inbox/`, אחרי שנבדק שהעותק השמור קיים;
  - עותק כמעט זהה מוחזק, ומחכה להחלטה במסך "כפילויות" בתוסף 2.3.1;
  - פירוט ב־`docs/inbox.md`.
- **התוסף 2.3.1** (`dist/trial-knowledge-2.3.1.zip`, כולל את 2.3.0 ומסך כפילויות): `[tk_start]`, עמודי תיק/עד/ציר זמן/עדים/מילון תחת `/trial/trial/…`, לשוניות בעמוד הדיון, מילון בריחוף, ותצוגת מדריכים בתור הבדיקה. אחרי ההתקנה: להחליף את תוכן עמוד הבית (עמוד 9) ב־`[tk_start]`.

## אצוות 100 הקבצים (11.10.2026, 13:41)
- **מה הועלה:** 100 קבצים. כמעט כל מסמך הועלה פעמיים, פעם בשם ארכיון ופעם בשם `NNNN_1.pdf`.
  - 50 עותקים זהים נמחקו אוטומטית מ־`inbox/`;
  - פריט אחד מוחזק כ"כמעט זהה": `0015_1`, זהה בטקסט ל־0025;
  - העותק הזהה שלו, `0015 — …`, ממתין להחלטה עליו;
  - 48 מסמכים חדשים נקלטו.
- **באג בסיווג (תוקן ב־`7e9d831`):** כל מסמך שהופיעה בו המילה "פרוטוקול" סווג כפרוטוקול. כך הפכו 34 החלטות קצרות של בית המשפט ל"דיונים" מדומים.
  - **הכלל החדש:** פרוטוקול הוא רק מסמך עם רשימת נוכחים או עם תורות דוברים. גם ה־pipeline בודק זאת אחרי הניתוח.
  - **ניקוי:** `POST /v2/admin/maintenance/non-hearings` (`apply: true`) הפך את 34 ה"דיונים" להחלטות. התקצירים שלהם הוסרו.
  - **אחרי הניקוי:** נשארו 14 דיונים אמיתיים.
- **כותרות:** הכותרת נלקחת משם הארכיון, אם קיים עותק כזה (`apply_best_name`). 41 מסמכים קיבלו כותרת חדשה.
  - **בעיה פתוחה:** כ־35 החלטות נקראות "שניתנה ע\"י רבקה פרידמן-פלדמן", כי זה מה שכתוב בשם הקובץ, ואין מזה כותרת מועילה.

## תקצירי מסמכים (11.10.2026 ערב)
- **מה זה:** לכל מסמך שאינו פרוטוקול נבנה תקציר:
  - כותרת שאומרת במה המסמך עוסק;
  - משפט עד שלושה משפטים, עם ציטוט;
  - הכרעה "מהותי / פרוצדורלי בלבד", עם נימוק;
  - "ימי דיון" מהודעות של בית המשפט: מי העיד, לאיזה צד, והדיון הבא.
- **פרסום:** תקציר נקי מתפרסם לבד. ב־pipeline התקציר נבנה בשלב `extract_a` ומתפרסם יחד עם המקור.
- **השלמה למסמכים קיימים:** `POST /v2/admin/briefs/build`.
  - ריצה ראשונה: 42 תקצירים נבנו (23 מהותיים, 19 פרוצדורליים).
  - 26 תקצירים נכשלו, כי התאריכים נכתבו בפורמט שלא תאם את החוזה (`18.05.2021`). התיקון נפרס ב־`9356004`, והריצה חוזרת עליהם.
- **התוסף 2.4.0** (`dist/trial-knowledge-2.4.0.zip`):
  - כותרת ותקציר בכל רשימה;
  - מסמכים פרוצדורליים מוסתרים כברירת מחדל, ויש כפתור להציג אותם;
  - ימי דיון מסומנים על ציר הזמן ובעמודי העדים;
  - עמוד עד גם לעדים שמופיעים רק בהודעות של בית המשפט.

## עותק מקומי בוורדפרס (תוסף 2.5.0, 11.10.2026)
- **מה זה:** הקוראים מקבלים את התוכן מטבלאות בוורדפרס: `{prefix}tk_store` ו־`tk_store_tags`.
- **איך הוא מתעדכן:**
  - Webhook מסמן תוכן שהשתנה, והתוכן מתרענן ברקע;
  - כל 15 דקות: `GET /v2/sync/changes?since=`;
  - פעם ביום: סנכרון מלא לפי `GET /v2/sync/objects` (api פרוס ב־`045957d`).
- **מה נשאר מול Railway בזמן אמת:** Ask, קישורי PDF, וממשק הניהול.
- **אחרי התקנה:** מריצים פעם אחת "סנכרון מלא" במסך "עותק מקומי".

## בקרת עלויות (11.10.2026 ערב)
- **`NTK_HEARING_DIGESTS=deferred`** (api, worker): פרוטוקולים נקלטים בלי תקציר. התקצירים נבנים אחר כך באחת משתי דרכים:
  - **Batch API:** `POST /v2/admin/digests/batch` שולח ב־Batch של Gemini, בחצי מחיר ועם תוצאות תוך 24 שעות. beat אוסף את התוצאות כל 10 דקות, מעקב ב־`GET /v2/admin/batches`. התוצאה נשמרת כ־model run באותו run id, ולכן הבנייה הרגילה עוברת את אותם שערים;
  - **ישירות:** `POST /v2/admin/digests/build`.
- **`NTK_MODEL_QA_RELATION=gemini-3.5-flash-lite`** (api, worker): סיווג שאלות ותשובות במודל הזול.
- **מדידה:** תקציר עולה בממוצע כ־1,950 טוקני קלט וכ־65 טוקני פלט לעמוד.
- **מחירון `gemini-3.8-flash`** (מבצע עד 31.12.2026): 0.75$ לקלט ו־3.75$ לפלט, לכל מיליון טוקנים. ב־Batch המחיר חצי.
- **פרוס:** `e8bd088` ב־api, ב־worker וב־beat (migration 0011).

## מה בייצור עכשיו
- **ארבעה פרוטוקולים נקלטו** (550 עמודים):

  | פרוטוקול | דיון | job |
  |---|---|---|
  | 0421 | 15.9 | `6535c612-6eb8-59e1-a900-dd9b640b5d6e` |
  | 0422 | 16.9 | `a355b596-98ed-54fb-b399-3ee513ffe89d` |
  | 0423 | 17.9 | `580bbb25-e820-538b-82f2-a40dd9f410ec` |
  | 0424 | 29.9 | `ec77075c-24ef-5439-a3dd-449741fe7bc0` |

  כל ה־embeddings הם `gemini-embedding-001`: 203 chunks.
- **פורסמו רק ארבעת המקורות**, באישור המשתמש, ב־corpus versions `cv-000002` עד `cv-000005`:
  - `sv_e98977d5617fc819dc82e3dd91`
  - `sv_40f4a8924f3136a752567e7151`
  - `sv_950c84af03858147cd7529afe8`
  - `sv_2faa12277963f688354dbfbff9`
- **לא פורסמו:** תקצירים ו־Claim Cards. שלושה תקצירים נדחו בשער, ואחד ממתין לבדיקה. ראו `docs/pilot-report.md`.
- **ריצות הערכה** שמורות ב־`ntk.evaluation_runs`, ונקראות ב־`GET /v2/admin/evaluations`. עותקים ב־`golden/reports/*.gemini.json`.

## תיבת הקליטה (inbox) — פעילה מ־11.10.2026
- **מיקום:** הקידומת `inbox/` ב־`ntk-sources`. המשתמש מעלה לשם את כל המסמכים, בכל מבנה תיקיות. התיעוד המלא ב־`docs/inbox.md`.
- **מצב נוכחי:** `NTK_INBOX_AUTO_PROCESS` לא מוגדר, כלומר `false`. סריקות רק מסווגות ומכינות "מפה". ההחלטה של המשתמש: קודם מפה, אחר כך קליטה.
- **מדיניות פרסום** (החלטת המשתמש): פרוטוקולים והחלטות שמספר התיק מודפס עליהם מתפרסמים אוטומטית. כל השאר, וכל שכבות ה־AI, ממתינים לאישור.
- **נבדק בייצור:** סריקה ידנית על תיקייה ריקה עברה בלי שגיאה (`listed: 0`), כלומר הרשאת ה־List ב־R2 תקינה. **עדיין לא נבדק על מסמכים אמיתיים בתיבה.**
- **אחרי שהמשתמש מאשר את המפה:**
  1. `POST /v2/admin/inbox/process` עם הסוגים המאושרים;
  2. `NTK_INBOX_AUTO_PROCESS=true` ב־worker, ופריסה של worker.

## כלים חדשים ב־API (admin, חתום)
- `POST /v2/admin/ingestion-jobs/{id}/rerun` עם `{"stages": [...], "force_stale": false}`:
  - מריץ מחדש שלבים מסוימים, למשל `embed`, `extract_a`, `verify` ו־`review` אחרי החלפת מודל. השלבים הקודמים נשארים כמו שהם;
  - `publish` נדחה;
  - `force_stale` מאפשר להריץ משימה שנשארה `running` אחרי ש־worker נעצר. זה מותר רק אחרי 15 דקות בלי התקדמות, כי הודעת Celery חוזרת רק אחרי visibility timeout של שעתיים.
- `POST /v2/admin/evaluations` עם `{"kind": "search_bench"|"ask_suite", "suite": "<שם ב־golden/>"}`:
  - מריץ את הסט ב־worker מול הקורפוס והמודלים בייצור;
  - `GET /v2/admin/evaluations[/{id}]` מחזיר את הדוח. `?report=false` מחזיר תקציר בלבד.

## מדיניות ביקורת ופרסום (ADR‑0014, מ־11.10.2026)
- **הגדרות ב־api וב־worker:** `NTK_AUTO_PUBLISH=gates` ו־`NTK_MODEL_TIMEOUT_SECONDS=300`.
- **מה מתפרסם לבד:** תוצר AI שעבר את כל השערים ואין לו דגל סיכון.
- **מה מגיע לתור:** רק פריטים שבאמת מוטלים בספק.
- **זוגות ש/ת:** לא פותחים משימות. התווית "אישר/הכחיש" מוצגת רק כשהמאמת מסכים.
- **מצב 11.10:**
  - תקצירי 15.9, 16.9 ו־29.9 פורסמו אוטומטית, והם מכסים את כל הדיון.
  - תקציר 17.9 ממתין בתור, בגלל דגל `motive_or_conspiracy` על משפט שמתאר טענת "קנוניה" של ריטמן.

## קורפוס (11.10.2026, cv-000037)
- **20 מקורות מפורסמים, 25,262 יחידות ציטוט:** 17 פרוטוקולים, ו־3 החלטות שפורסמו מהתיבה.
- **תקצירים:** 16 מפורסמים. התקציר של 30.11.2021 ממתין בתור, בגלל דגל `investigator_offense`.
- **תיבה:** 30/30 קבצים נקלטו. 12 מסמכים שאינם פרוטוקול או החלטה (בקשות, תגובות, הודעות, כתב אישום ומוצג) נקלטו ואינם מפורסמים, לפי המדיניות.
- **Parser 1.3:** פרוטוקולי 2021–2023 עברו ניתוח מחדש (migration 0008, הסימון superseded).
- **בתיבה התגלו ותוקנו:**
  - נוסחי הצגת עד ישנים;
  - שורה שיש בה רק מספר שורה;
  - מזהים מחוברים בפלט המודל;
  - תקציר שעבר את כל הבדיקות ולא פורסם, כי המקור שלו פורסם רק אחריו;
  - אישור בתוסף שלא פרסם.

## פתוח — לפי סדר
1. **התקנת תוסף 2.2.2** על ידי המשתמש.
2. **החלטה של המשתמש:** האם לפרסם גם בקשות, תגובות והודעות, והאם להפעיל `NTK_INBOX_AUTO_PROCESS=true` לקליטה יומית אוטומטית.
3. **Ask תוקן:** הזוג ש/ת מגיע שלם להקשר, וסט השאלות עובר 15/16.
2. **Layer A:**
   - התקציר מכסה רק את 400 היחידות הראשונות, כלומר עד עמוד 28–36;
   - הניסוח "בית המשפט קבע" נחסם בשער;
   - בגלאי יש פער: "ובהמשך קבע" לא נחסם.
3. **חיפוש:** Recall@20 0.759 מול יעד 0.85. לבנות מחדש את מאגר התיוג עם האות הווקטורי, ואז לכוונן.
4. **ביקורת:** במסך "ביקורת ופרסום" ממתינות משימות `qa_exchange` ו־`hearing_digest_failure`. לבדוק את הבלוקים בדפים הציבוריים.
5. **שירות backup:** pg_dump לילי ל־`ntk-backups`. צריך token נפרד ב־R2, מוגבל ל־`ntk-backups`. מקימים מ־`infra/railway/Dockerfile.backup` עם cron `17 2 * * *`.
6. **עדכון התיעוד:** Railway הפסיק לתמוך ב־config‑as‑code (`railway.json`) ועבר ל־`.railway/railway.ts`. ההגדרות נקבעו ישירות בכל שירות, והקבצים ב־`infra/railway/*.json` משמשים כתיעוד בלבד.

## לקחים טכניים (חשוב לשיחה הבאה)
- **אין גישה מהסביבה ל־railway.com, ל־Cloudflare ול־Gemini** (`generativelanguage.googleapis.com` מחזיר 403 מה־proxy).
  - את Railway מנהלים דרך GraphQL `https://backboard.railway.com/graphql/v2`, מתוך לשונית Railway המחוברת בחלונית הדפדפן (javascript, `credentials:"include"`). למשל `variableCollectionUpsert` עם `skipDeploys`, `serviceInstanceDeployV2` ו־`deployments`.
  - Gemini נבדק מאותה לשונית.
- **`serviceInstanceUpdate` עם `builder` נכשל.** במקום זה מגדירים `RAILWAY_DOCKERFILE_PATH`.
- **פקודות start רצות ב־exec form.** כדי שמשתנים כמו `$PORT` ימולאו, צריך לעטוף ב־`/bin/sh -c`.
- **קריאות admin מהסביבה** נחתמות במפתח `claude-ops`. הסוד שמור רק בקובץ זמני בסביבת השיחה וב־Railway, ולא נכנס ל־repo. מנגנון הבטיחות **חוסם** קריאה של `NTK_SERVICE_KEYS` הקיים, גם לחתימה בדפדפן. בשיחה חדשה צריך מפתח חדש באישור המשתמש, או להמשיך עם הקיים אם הסוד זמין.
- **כל פריסה לייצור דורשת אישור מפורש של המשתמש באותה שיחה.** מנגנון הבטיחות חוסם `serviceInstanceDeployV2` בלי אישור כזה.
- **פריסה של worker הורגת משימה רצה.** המשימה נשארת `running` עד ה־visibility timeout (שעתיים). לכן פורסים בין משימות, ומשתמשים ב־`rerun` עם `force_stale` אם צריך.
- **התחברות ל־Cloudflare נכשלת בחלונית הדפדפן** (Turnstile). כל עבודה מול Cloudflare נעשית בדפדפן הרגיל של המשתמש, לפי הוראות.
- **בחירת קבצים ב־WordPress** נעשית על ידי המשתמש. אין לי גישה לבורר הקבצים.
- **סודות:** אף פעם לא בצ'אט. סודות של צד שלישי מדביק המשתמש ישירות ב־Railway. סודות שאני יוצר (מפתח השירות, סוד ה־webhook ו־`claude-ops`) הוזנו ישירות ל־Railway ולתוסף.
