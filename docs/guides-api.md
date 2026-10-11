# נקודות כניסה — שכבת "מדריכים" (Guides) וה־API שלה

מטרה: להפוך את החומר הגולמי (פרוטוקולים, כתב אישום, החלטות) לנקודות כניסה קריאות לקהל הרחב:
עמוד "מתחילים כאן", עמוד לכל אחד משלושת התיקים, ציר זמן כפול עם זום, עמודי עדים ומילון מונחים.

## עקרונות
- **כל משפט עובדתי מצוטט** ליחידת מקור (`su_…`), כמו בתקצירי הדיונים. אין ידע חיצוני.
- **טענה ≠ עובדה.** תוכן שנלקח מכתב האישום מוצג תמיד כ"לפי כתב האישום" (גם בטקסט וגם בכותרת המקטע).
- **מדריכים עוברים אישור אנושי פעם אחת** (ADR-0015): השערים והמאמת רצים, אבל גם מדריך שעבר את כולם
  נשאר `human_review_required` עד שהמשתמש מאשר. אחרי אישור — מתפרסם מיד (כמו תקצירים, ADR-0014).
- **מילון המונחים** הוא תוכן עריכתי כללי (לא מתוך התיק) ומסומן ככזה.

## אחסון
`ntk.generated_artifacts` עם `artifact_type = 'guide'`:

| object_type | object_id | מה |
|---|---|---|
| `indictment` | `main` | סקירת כתב האישום: הנאשמים והאישומים |
| `case` | `1000` / `2000` / `4000` | מדריך לתיק |
| `witness` | `w_<10 hex>` | מי העד ותקציר עדותו |

מבנה ה־payload (חוזה `GuideObject`):
```json
{
  "schema_version": "2.0",
  "id": "uuid",
  "kind": "case",
  "key": "4000",
  "title": "תיק 4000",
  "subtitle": "פרשת בזק–וואלה",
  "source_version_ids": ["sv_…"],
  "blocks": [
    {"block": "one_line", "items": [{"text": "…", "citation_ids": ["su_…"]}]},
    {"block": "alleged",  "items": [{"text": "…", "citation_ids": ["su_…"]}]},
    {"block": "people",   "items": [{"label": "אילן ישועה", "text": "מנכ\"ל וואלה …", "citation_ids": ["su_…"]}]},
    {"block": "charges",  "items": [{"label": "בנימין נתניהו", "text": "שוחד; מרמה והפרת אמונים", "citation_ids": ["su_…"]}]},
    {"block": "events",   "items": [{"label": "…", "text": "…", "date": "2015-03-12", "date_precision": "day", "citation_ids": ["su_…"]}]}
  ],
  "citations": [{"source_unit_id": "su_…", "source_version_id": "sv_…", "page": 6, "line_start": 3, "line_end": 9,
                 "speaker": null, "quote": null, "court_record_status": "filed", "permalink": "…/v2/citations/su_…"}],
  "review": {"state": "human_review_required", "risk_flags": [], "reviewer": null, "reviewed_at": null}
}
```
סוגי בלוקים: `one_line`, `overview`, `defendants`, `alleged`, `people`, `charges`, `events` (תיק/כתב אישום),
`role`, `testimony` (עד). `date_precision` ∈ `day|month|year`; `date` תמיד `YYYY-MM-DD` (חודש/שנה → היום הראשון).

## API ציבורי (רק מה שפורסם)

### `GET /v2/guide` — עמוד "מתחילים כאן"
```json
{
  "indictment": {"artifact_id": "…", "title": "כתב האישום",
                 "document": {"source_version_id": "sv_…", "title": "כתב אישום", "document_date": "2019-12-01", "page_count": 77},
                 "blocks": [{"block": "overview", "items": […]}, {"block": "defendants", "items": […]}],
                 "citations": […]} ,
  "cases": [{"key": "4000", "title": "תיק 4000", "subtitle": "פרשת בזק–וואלה", "one_line": {"text": "…", "citation_ids": […]},
             "defendants": ["בנימין נתניהו", "שאול אלוביץ'"], "charges": [{"label": "…", "text": "…"}], "event_count": 31}],
  "witnesses": [{"slug": "w_…", "name": "אילן ישועה", "label": null, "hearing_count": 3, "first_date": "2021-05-10",
                 "last_date": "2021-06-14", "cases": ["4000"], "has_guide": true}],
  "latest_hearing": {"id": "hr_…", "hearing_date": "2026-05-25", "witnesses": [], "summary_sentences": [{"text": "…", "citation_ids": […]}],
                     "citations": […]},
  "counts": {"hearings": 17, "documents": {"decision": 3, "motion": 4, "response": 4, "notice": 3, "indictment": 1}}
}
```
`indictment` הוא `null` ו־`cases` ריק כל עוד המדריכים לא אושרו. `witnesses` תמיד מלא (מחושב מהדיונים).

### `GET /v2/guide/cases/{key}` — עמוד תיק (`key` ∈ 1000, 2000, 4000)
אותו payload של המדריך (`key`, `title`, `subtitle`, `blocks`, `citations`, `review`), ובנוסף:
- `artifact_id`;
- `hearings`: `[{"id","hearing_date","witnesses"}]` — דיונים שבהם העיד אדם שמופיע בבלוק `people`;
- `document`: פרטי כתב האישום (כמו למעלה).
- בבלוק `people`, לכל פריט שהוא גם עד: `"witness_slug": "w_…"`.
404 אם המדריך לא פורסם.

### `GET /v2/guide/witnesses/{slug}` — עמוד עד
```json
{"slug": "w_…", "name": "אילן ישועה", "label": null, "artifact_id": "…|null",
 "blocks": [{"block": "role", "items": […]}, {"block": "testimony", "items": […]}],
 "cases": ["4000"],
 "hearings": [{"id": "hr_…", "hearing_date": "2021-05-10", "digest_sentences": [{"text": "…", "citation_ids": […]}]}],
 "notable_exchanges": [{"hearing_id": "hr_…", "question_unit_id": "su_…", "answer_unit_id": "su_…", "answer_relation": "affirms",
                        "question": "…", "answer": "…"}],
 "citations": […]}
```
עד בלי מדריך מאושר: `blocks` ריק, ו־`hearings` + `digest_sentences` (מתקצירים שפורסמו) עדיין מוצגים.

### `GET /v2/guide/timeline` — ציר זמן כפול
```json
{"events": [
   {"id": "ev_…", "track": "story", "date": "2015-03-12", "date_precision": "day", "title": "…", "text": "…",
    "case_keys": ["4000"], "kind": "indictment_fact", "link": {"type": "case", "key": "4000"}, "citation_ids": ["su_…"]},
   {"id": "hr_…", "track": "trial", "date": "2021-05-10", "date_precision": "day", "title": "דיון: עדות אילן ישועה",
    "text": "…", "case_keys": ["4000"], "kind": "hearing", "link": {"type": "hearing", "id": "hr_…"}, "citation_ids": []},
   {"id": "sv_…", "track": "trial", "date": "2021-07-04", "date_precision": "day", "title": "החלטה: …", "text": null,
    "case_keys": [], "kind": "decision", "link": {"type": "document", "id": "sv_…"}, "citation_ids": []}
 ],
 "citations": {"su_…": {…citation…}},
 "range": {"from": "2009-03-31", "to": "2026-05-25"}}
```
`track=story` — אירועים שכתב האישום מתאר (מהמדריכים שפורסמו). `track=trial` — כתב האישום עצמו, דיונים ומסמכים.
`kind` ∈ `indictment_fact | indictment | hearing | decision | motion | response | notice | affidavit | exhibit | other`.

### `GET /v2/glossary`
```json
{"note": "הסברים כלליים, לא מתוך תיק בית המשפט", "terms": [
  {"id": "cross-examination", "term": "חקירה נגדית", "aliases": ["חקירה הנגדית", "בחקירה נגדית"], "category": "procedure",
   "short": "…משפט אחד…", "long": "…פסקה…", "see_also": ["direct-examination"]}]}
```
קטגוריות: `procedure`, `evidence`, `offense`, `people`, `documents`.

## API admin
- `POST /v2/admin/guides/build` `{"kind": "indictment"|"cases"|"witnesses"|"all", "source_version_id": "sv_…"?}` — בונה (משימת worker).
- המדריכים נכנסים לתור הבדיקה הרגיל (`/v2/admin/review-tasks`), ומאושרים ב־`/v2/admin/artifacts/{id}/review`.
