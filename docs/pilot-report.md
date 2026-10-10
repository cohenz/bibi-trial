# דוח פיילוט — אפריל 2021 (מצב נכון ל־10.10.2026)

## שורה תחתונה

**הפיילוט לא הושלם.** המערכת נבנתה ונבדקה מקצה לקצה על פרוטוקול סינתטי. מדדי הקבלה של הפיילוט האמיתי **לא נמדדו**, כי ארבעת קובצי ה־PDF לא היו זמינים לסביבת הפיתוח: אין גישה ל־www.gov.il, והקבצים לא צורפו. גם מדדים שתלויים בתיוג אנושי לא נמדדו. שום מדד כאן לא מוצג כ"עבר" אם לא נמדד בפועל.

## מדדי הקבלה של הפיילוט

| מדד | יעד | מצב | הערה |
|---|---|---|---|
| זיהוי דובר נכון (200 תורות) | ≥ 97% | **לא נמדד** | חסרים PDFs ומתייג. `label-export --kind speakers` מוכן |
| צימוד ש/ת נכון (100 חילופים) | ≥ 95% | **לא נמדד** | כנ"ל, `--kind exchanges` |
| דיוק מיקום ציטוט (עמוד ושורה) | ≥ 95% | **לא נמדד על הקורפוס האמיתי** | על הקורפוס הסינתטי: 100%. המדידה מחלצת מחדש את ה־PDF ומשווה טקסט לפי עמוד ושורה |
| תמיכה בציטוט (טענה ↔ מקור) | ≥ 95% | **לא נמדד** | דורש תיוג (`--kind citations`). המדד הלקסיקלי האוטומטי הוא proxy בלבד |
| טיפול בהנחה שגויה | 100% | **56/56 על הקורפוס הסינתטי עם מודל mock** | ראו הסתייגות למטה |
| "בית המשפט קבע" בלי החלטה מאושרת | 0 | 0 על הקורפוס הסינתטי | |
| חיפוש: Recall@20 ≥ 0.85, nDCG@10 ≥ 0.6, p95 ≤ 800ms | | **לא נמדד על הקורפוס האמיתי** | 25 שאילתות קבועות מראש ב־`golden/search-bench-pilot-v1.json`. חסרים PDFs ותיוג רלוונטיות |
| שאלות זהב לפיילוט (18) | | **לא נמדד** | `golden/pilot-hebrew-legal-v1.json`. הריצה מחזירה `measured: false` |
| Claim Cards P1/P2 | נבנו ונבדקו | **לא נבנו על חומר אמיתי** | הוגדרו ב־registry ונבנים בפקודה אחת אחרי הקליטה |

## מה כן נבדק, ואיך

### בדיקות אוטומטיות
- **Python: 155 בדיקות עוברות**:
  - unit: מזהים, נרמול עברית, חוזים, parser, שערים, מדיניות מודלים, חתימות HMAC, ספק Gemini (מול HTTP מדומה), גלאים אדברסריים;
  - integration: Postgres 16 + pgvector אמיתיים — pipeline, אי‑שינוי מקורות, audit append‑only, bi‑temporal, פרסום, Project 315, תיוג, ובנייה מחדש של digest;
  - e2e: ה־API מול DB.
- **PHP: 24 בדיקות עוברות**: חתימה זהה ל־Python, הצפנת סוד, מטמון, webhooks ו־escaping.
- **ruff:** נקי. `contracts --check`: החוזים מעודכנים.

### הרצה חיה מקצה לקצה (`tools/e2e_live.py`, פלט ב־`docs/e2e-live-run.txt`)
- **השירותים בהרצה:** API (uvicorn), Celery worker, Redis, Postgres 16 + pgvector ו־S3‑compatible (moto, כתחליף ל־R2).
- **השלבים, כולם עברו על DB חדש:** presign → העלאה ישירה ל־storage → יצירת משימה → 14 השלבים ב־worker → משימות ביקורת → אישור → פרסום (`cv-000002`) → digest ציבורי → permalink לציטוט (עמ' 1, שורה 15) → Ask עם ציטוטים → permalink לתשובה → תיקון הנחה שגויה.

### סט אדברסרי (`golden/adversarial-v1.json`, דוח ב־`golden/reports/adversarial-synthetic.json`)
- **הרכב:** 56 שאלות — 22 הנחה שגויה, 10 ייחוס החלטה, 10 הזרקת הנחיות, 8 ייחוס שגוי לדובר, 4 השלמת פרטים חסרים ו־2 "התעלם מהמקורות".
- **תוצאה:** 56/56.
- **הסתייגות:** רוב ההגנות כאן דטרמיניסטיות — גלאים ושערים לפני המודל ואחריו — ולכן התוצאה צפויה להחזיק גם עם מודל אמיתי. ובכל זאת, הסט רץ עם ספק mock ועל קורפוס סינתטי קטן. **חובה להריץ אותו שוב עם Gemini על הקורפוס האמיתי** לפני כל פרסום.

### חיפוש על הקורפוס הסינתטי (`golden/reports/search-bench-synthetic.json`)
- **תוצאות:** Recall@20 1.0, nDCG@10 0.975, p95 ‏17ms.
- **משמעות:** זה מסמך אחד קצר, כך שהמספרים מראים רק שהאותות עובדים על מורפולוגיה עברית, ציטוט מדויק, מוצגים וקיצורים. **אין מכאן מסקנה לגבי פרוטוקולים אמיתיים**, ואין מכאן הכרעה בשאלת OpenSearch.

## מה לא נבדק כלל
- **Gemini אמיתי.** לא סופק מפתח. ה־endpoint נגיש מהסביבה (HTTP 403 בלי מפתח), וה־provider נבדק מול HTTP מדומה בלבד. איכות החילוץ, המיפוי והסיווג השיפוטי לא נמדדה.
- **Cloudflare R2 אמיתי.** הסביבה לא מגיעה ל־`*.r2.cloudflarestorage.com`. נבדק רק מול moto (S3‑compatible).
- **Railway.** קובצי config‑as‑code נכתבו לפי הסכמה הרשמית, אבל לא נפרסו.
- **WordPress חי.** התוסף נבנה ל־ZIP, ובדיקות ה־PHP רצות עם stubs. התקנה באתר אמיתי (Gutenberg, rewrites) לא נבדקה. נדרשת בדיקת smoke ידנית (`wordpress/trial-knowledge/tests/README.md`).
- **docker compose / `make dev`.** בסביבת הפיתוח אין Docker daemon, ולכן השירותים הורצו ישירות (אותן פקודות, אותן גרסאות). ה־Dockerfile וה־compose לא נבנו בפועל.
- **OCR על סריקות אמיתיות.** tesseract‑heb מותקן ב־Dockerfile, אבל לא נבדק על סריקה של בית המשפט.

## להשלמת הפיילוט
```bash
# 1. קליטה (מ-Railway, שיש לו גישה ל-gov.il; או העלאה דרך התוסף)
trial-knowledge ingest manifests/pilot-april-2021.json
# 2. ביקורת ופרסום של המקורות והתקצירים (בתוסף)
# 3. טענות הפיילוט
trial-knowledge build-claims --slug p-request-attribution --slug p-judicial-remarks
# 4. תיוג אנושי
trial-knowledge label-export --kind speakers  --n 200 --out golden/labels/speakers.csv
trial-knowledge label-export --kind exchanges --n 100 --out golden/labels/exchanges.csv
trial-knowledge bench-pool --suite golden/search-bench-pilot-v1.json --out golden/labels/search.csv
#    ...תיוג... ואז:
trial-knowledge label-score --kind speakers  --file golden/labels/speakers.csv
trial-knowledge label-score --kind exchanges --file golden/labels/exchanges.csv
trial-knowledge bench-apply-labels --suite golden/search-bench-pilot-v1.json --file golden/labels/search.csv
# 5. מדידה
trial-knowledge eval  --suite golden/adversarial-v1.json        --out golden/reports/adversarial-pilot.json
trial-knowledge eval  --suite golden/pilot-hebrew-legal-v1.json --out golden/reports/pilot.json
trial-knowledge bench --suite golden/search-bench-pilot-v1.json --out golden/reports/search-bench-pilot.json
trial-knowledge label-export --kind citations --n 100 --out golden/labels/citations.csv   # ואז label-score
```
את הדוח הזה מעדכנים עם המספרים בפועל, כולל מדדים שנכשלו.
