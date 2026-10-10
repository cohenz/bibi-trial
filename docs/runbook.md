# Runbook — תקלות נפוצות

| תסמין | סיבה אפשרית | מה עושים |
|---|---|---|
| `/v2/ready` מחזיר 503, `schema: false` | migrations לא רצו | `trial-knowledge migrate`. ב־Railway: לוגים של pre-deploy |
| migration 0003 נכשלת: `needs halfvec (pgvector >= 0.7)` | pgvector ישן ו־`NTK_EMBEDDING_DIM>2000` | לשדרג pgvector, או להגדיר ממד ≤ 2000 לפני ה־migration הראשונה |
| העלאה מהדפדפן נכשלת ב־CORS | מדיניות CORS של R2 לא כוללת את דומיין האתר או את `content-type` | לעדכן את ה־CORS policy (docs/install.md §2) |
| העלאה נכשלת `403 SignatureDoesNotMatch` | שעון שגוי, או `Content-Type`/`Content-Length` שונים מאלה שנחתמו | הדפדפן חייב לשלוח את הכותרות שהוחזרו ב־presign כמו שהן |
| משימה נכשלת ב־`validate: checksum_mismatch` | הקובץ ב־R2 שונה מה־SHA‑256 שהוצהר | להעלות שוב. האובייקט השגוי לא נקלט, וה־upload מסומן `rejected` |
| משימה נכשלת ב־`download: object_missing` | ההעלאה לא הושלמה | להשלים את ההעלאה ואז "ניסיון חוזר". השלב retryable |
| `fetch_blocked` | URL לא ב־`NTK_FETCH_ALLOWLIST`, redirect, או http | להוסיף host ל־allowlist או לתת URL סופי ב־https |
| `extract_text` עם `empty_pages`, ו־`ocr_fallback` מזהיר "OCR unavailable" | אין שכבת טקסט; tesseract‑heb חסר | ה־Dockerfile מתקין `tesseract-ocr-heb`. מקומית: `apt install tesseract-ocr-heb` |
| שורות "synthetic" בכל המסמך | ה־PDF בלי מספרי שורות מודפסים | צפוי. הציטוט מסומן כך ב־UI. לבדוק את איכות החלוקה בדגימה |
| `segment: hearing_date_unknown` | תאריך לא זוהה בכותרת ולא ניתן במניפסט | להוסיף `hearing_date` למניפסט או בטופס ההעלאה |
| `invalid_output` ב־model_runs | המודל החזיר JSON שאינו עומד בחוזה, או מזהים שלא היו בקלט | נפתחת review task. לבדוק את `validation_errors`, להחליף מודל או prompt version, ולהריץ שוב את השלב |
| Gemini `HTTP 429/503` | מכסה או עומס | retry אוטומטי עם backoff. אם נמשך: להוריד את concurrency של ה־worker |
| `ModelPolicyError` בהפעלה | מודל Lite הוגדר כמסווג שיפוטי או כמאמת, או תפקיד ללא מודל | לתקן את `NTK_MODEL_*` (ADR‑0007) |
| פרסום נכשל `review_required` | הפריט לא אושר | לאשר במסך הביקורת |
| פרסום נכשל `unpublished_object` | מקורות מצוטטים לא פורסמו | לפרסם עם "לפרסם גם את המקורות", או `include_sources=true` |
| פרסום נכשל "mock provider" | תוכן נוצר בספק הדמה | להגדיר מודל אמיתי ולבנות מחדש |
| תשובות Ask הן תמיד `requires_human_review` | נושא רגיש, או writer ו־verifier ממשפחה אחת | צפוי במדיניות. לבנות Claim Card ולאשר אותו, וכך התשובה תיבנה עליו |
| `rate_limited` מהאתר | WordPress לא חותם `X-NTK-Client-*` | להגדיר Key ID וסוד בתוסף. בלעדיהם כל הגולשים חולקים מכסה אחת |
| מטמון WordPress לא מתעדכן אחרי פרסום | webhook לא מגיע | `WP_CALLBACK_URL` ו־`WP_CALLBACK_SECRET` ב־worker וב־beat. בדיקה: `ntk.webhook_outbox` (status/last_error) |
| `nonce already used` / `timestamp outside allowed skew` | שעון השרת של WordPress סוטה | לסנכרן NTP. הטווח המותר הוא ±300 שניות |
| משימות תקועות ב־`running` | worker נפל באמצע שלב | `acks_late` מחזיר את המשימה לתור. אם לא: "ניסיון חוזר". שלבים שהושלמו לא ירוצו שוב |
| רשומות ב־`ntk.dead_letters` | 3 כשלים רצופים | לבדוק את `error`, לתקן, ואז retry למשימה. בסוף לסמן `resolved_at` |
| שחזור DB | — | `gunzip -c ntk-<ts>.sql.gz \| psql "$DATABASE_URL"` לתוך DB ריק, ואז `trial-knowledge migrate` |

**כלל אצבע:** אף פעם לא לעדכן ידנית `source_units` או `source_versions`. triggers חוסמים זאת. תיקון מקור הוא גרסה חדשה של הקובץ.
