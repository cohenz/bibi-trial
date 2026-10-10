# התקנה וחיבור — מאגר משפט נתניהו (V1)

המסמך מתאר שלוש סביבות: פיתוח מקומי, פריסה ב־Railway עם Cloudflare R2, וחיבור תוסף WordPress.
כל המשתנים מתועדים ב־`.env.example` (שמות בלבד).

---

## 1. פיתוח מקומי — פקודה אחת

דרישות: Docker עם Compose.

```bash
cp .env.example .env          # ערכי פיתוח; אפשר להשאיר NTK_MODEL_PROVIDER=mock
make dev                      # postgres+pgvector, redis, minio, api, worker, beat + migrate + seed-claims
```

- API ותיעוד OpenAPI: http://localhost:8000/docs
- MinIO (תחליף מקומי ל־R2): http://localhost:9001 (ntk-dev / ntk-dev-secret), bucket `ntk-sources`
- להגדרת מפתח שירות לפיתוח, הוסיפו ל־`.env`:
  `NTK_SERVICE_KEYS={"wp-dev": {"secret": "<סוד אקראי ארוך>", "scopes": ["admin:all"]}}`

בדיקות:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.lock pytest moto[server] ruff
pip install -e services/common -e adapters/project315 -e services/api -e services/worker
NTK_TEST_ADMIN_URL=postgresql+psycopg://ntk:ntk@localhost:5432/postgres pytest     # 179 בדיקות (NTK_REAL_PDF_DIR=data/real מפעיל גם את מבחני ה־PDF האמיתיים)
php wordpress/trial-knowledge/tests/run.php                                      # בדיקות התוסף
python tools/e2e_live.py tests/fixtures/synthetic_protocol.pdf                   # בדיקה חיה מול שירותים רצים
```

---

## 2. Cloudflare R2

1. **Bucket פרטי:** R2 → Create bucket (למשל `ntk-sources`). לא להפעיל Public access / r2.dev.
2. **API token:** R2 → Manage API tokens → Create API token → הרשאה **Object Read & Write** → **Apply to specific buckets only** → `ntk-sources`. שמרו את ה־Access Key ID ואת ה־Secret Access Key. הם מוגדרים רק במשתני הסביבה של Railway, ולא ב־WordPress.
3. **Endpoint:** `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`, region `auto`.
4. **CORS** (bucket → Settings → CORS policy). ההגדרה מאפשרת לדפדפן של עורכי האתר להעלות ישירות:

```json
[
  {
    "AllowedOrigins": ["https://your-wordpress-site.example"],
    "AllowedMethods": ["PUT", "HEAD"],
    "AllowedHeaders": ["content-type", "content-length", "x-amz-checksum-sha256"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

5. **Retention:** bucket → Settings → Bucket lock rules → כלל על prefix `sources/` (למשל שנה). R2 אינו תומך ב־object versioning. במקומו, כל קובץ נשמר תחת מפתח שמכיל את ה־SHA‑256 שלו (ADR‑0011), כך שקובץ לעולם אינו נדרס.
6. **הצפנה:** R2 מצפין את כל האובייקטים במנוחה כברירת מחדל, ואין צורך בהגדרה.
7. **גיבויים:** מומלץ bucket נפרד (למשל `ntk-backups`) ו־token נפרד לשירות ה־backup.

---

## 3. Railway

צרו פרויקט עם השירותים הבאים:

| שירות | מקור | הגדרות |
|---|---|---|
| **Postgres** | תבנית Postgres עם pgvector | בדקו `SELECT extversion FROM pg_extension WHERE extname='vector'` ≥ 0.7 אם `NTK_EMBEDDING_DIM=3072`. אחרת בחרו ממד ≤ 2000 |
| **Redis** | תבנית Redis | — |
| **api** | הריפו הזה | Config as code: `infra/railway/api.railway.json`. **Public domain: כן.** migrations רצות ב־pre-deploy |
| **worker** | הריפו הזה | `infra/railway/worker.railway.json`. **ללא public domain** |
| **beat** | הריפו הזה | `infra/railway/beat.railway.json` (משלוח webhooks כל 30 שניות). ללא public domain |
| **backup** (אופציונלי) | הריפו הזה | `infra/railway/backup.railway.json`. cron לילי: pg_dump ל־R2 |

**משתני סביבה** (Service → Variables), לפי `.env.example`:
- `DATABASE_URL=${{Postgres.DATABASE_URL}}` ו־`REDIS_URL=${{Redis.REDIS_URL}}`. אלה כתובות פנימיות ברשת הפרטית של Railway.
- `NTK_ENV=production`, `NTK_PUBLIC_BASE_URL=https://<api-domain>`.
- משתני R2: `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_REGION=auto`.
- משתני מודלים: `NTK_MODEL_PROVIDER=gemini`, `GEMINI_API_KEY`, ומודל לכל תפקיד (`NTK_MODEL_*`), לפי בחירה אחרי benchmark. אין שמות מודלים בקוד.
- `NTK_SERVICE_KEYS`, `NTK_IP_HASH_SALT`, `NTK_CORS_ORIGINS=https://your-wordpress-site.example`.
- `WP_CALLBACK_URL`, `WP_CALLBACK_SECRET`. ההגדרה נדרשת בשירותי worker ו־beat.

**Health checks:** ה־API חושף `/v2/ready` (בודק DB וסכמה) ו־`/v2/health`.
**לוגים:** לוג שורה לכל בקשה, בלי גוף הבקשה ובלי סודות. `Settings` מסתיר סודות ב־repr. זמן שמירת הלוגים נקבע לפי תוכנית Railway.
**Retry ו־DLQ:** משימת קליטה נכשלת → עד 3 ניסיונות עם backoff אקספוננציאלי. אחרי זה היא נרשמת ב־`ntk.dead_letters`, והמשימה מסומנת `failed`. ב־WordPress מופיע כפתור "ניסיון חוזר". שלבים שהושלמו אינם רצים שוב.
**Rollback:** ב־Railway → Deployments → Redeploy לגרסה קודמת. migrations הן forward‑only. לפני deploy עם migration חדשה, הריצו backup ידני (service backup → Run now).

---

## 4. תוסף WordPress

1. בנו את ה־ZIP: `tools/build_plugin_zip.sh`. הקובץ נוצר ב־`dist/trial-knowledge-2.1.0.zip`.
2. WordPress → Plugins → Add New → Upload Plugin → הפעלה.
3. ב־`wp-config.php` (מומלץ):

```php
define( 'TK_API_SECRET', '<הסוד של מפתח השירות ב-NTK_SERVICE_KEYS>' );
define( 'TK_WEBHOOK_SECRET', '<אותו ערך כמו WP_CALLBACK_SECRET ב-Railway>' );
```

4. **מאגר המשפט → הגדרות:** כתובת ה־API (חובה https), Key ID, ואז "בדיקת חיבור". התוצאה צריכה להראות `ready` ו־`whoami`.
5. העתיקו את כתובת ה־webhook שמוצגת במסך ל־`WP_CALLBACK_URL` ב־Railway.
6. Settings → Permalinks → Save, כדי לרענן את כתובות `/trial/...`.
7. **הרשאות:** Administrator מקבל את כל ההרשאות. Editor מקבל `tk_review`. פרסום דורש `tk_publish`, העלאה דורשת `tk_manage_sources`, והגדרות דורשות `tk_manage_settings`.

**שימוש:**
- **מקורות וקליטה:** בחירת קובצי PDF. הדפדפן מחשב SHA‑256, מקבל presigned URL ומעלה ישירות ל־R2. אחר כך נוצרת משימת קליטה, ומוצגים שלבים, התקדמות, כשלים ו־retry.
- **ביקורת ופרסום:** תור משימות. לכל פריט מוצגים זה לצד זה פלט הכותב, פלט המאמת, המקורות, השערים, והמודל וההנחיה שיצרו כל פסקה. הפעולות: אישור, בקשת שינויים, דחייה, פרסום והסרה מפרסום.
- **בלוקים:** כרטיס טענה, ציטוט מקור, ציר זמן, שאלו את המשפט. ולכל אחד shortcode מקביל:
  `[tk_claim_card id="<uuid>"]`, `[tk_citation id="su_…"]`, `[tk_hearing_timeline]`, `[tk_ask]`.

---

## 5. הרצת הפיילוט

```bash
trial-knowledge migrate
trial-knowledge seed-claims
trial-knowledge ingest manifests/pilot-april-2021.json          # דרך התור (worker)
# או: ingest manifests/pilot-april-2021.r2.json — אחרי שהקבצים הועלו ל-R2 (ראו _alternatives)
trial-knowledge run --stage parse,pair,chunk,extract-a,map-b,verify --manifest manifests/pilot-april-2021.json
trial-knowledge build-claims --slug p-request-attribution --slug p-judicial-remarks
trial-knowledge label-export --kind speakers --n 200 --out golden/labels/speakers.csv
trial-knowledge label-export --kind exchanges --n 100 --out golden/labels/exchanges.csv
# ...תיוג אנושי של הקבצים...
trial-knowledge label-score --kind speakers --file golden/labels/speakers.csv
trial-knowledge label-score --kind exchanges --file golden/labels/exchanges.csv
trial-knowledge eval --suite golden/adversarial-v1.json --out golden/reports/adversarial.json
trial-knowledge eval --suite golden/pilot-hebrew-legal-v1.json --out golden/reports/pilot.json
trial-knowledge bench --suite golden/search-bench-pilot-v1.json --out golden/reports/search-bench.json
trial-knowledge publish --artifact-set pilot-april-2021 --dry-run
```

`NTK_FETCH_ALLOWLIST` חייב לכלול את `www.gov.il` כדי להוריד מקובצי ה־URL. הורדה עם redirect נחסמת (הגנת SSRF).
