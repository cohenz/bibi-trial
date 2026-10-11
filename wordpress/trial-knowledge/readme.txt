=== Trial Knowledge ===
Contributors: trialknowledge
Tags: knowledge base, legal, citations, rtl
Requires at least: 6.4
Tested up to: 6.6
Requires PHP: 8.1
Stable tag: 2.3.0
License: GPLv2 or later

Presentation and editorial layer for the Netanyahu trial Knowledge API.

== Description ==

* Reader entry points (2.3): [tk_start] home page ("מתחילים כאן"), case guides (/trial/case/{1000|2000|4000}/), witness pages (/trial/witness/{w_…}/), a dual-track zoomable timeline (/trial/timeline/, [tk_timeline]), the witnesses list (/trial/witnesses/, [tk_witnesses]) and a glossary with automatic term tooltips (/trial/glossary/, [tk_glossary]).
* Claim Card, Source Citation, Hearing Timeline and Ask the Trial blocks (and shortcodes [tk_claim_card id=""], [tk_citation id=""], [tk_hearing_timeline], [tk_ask]).
* Stable public URLs: /trial/claim/{id}/, /trial/answer/{id}/, /trial/source/{su_id}/, /trial/hearing/{hr_id}/.
* Upload PDFs directly to object storage (Cloudflare R2 / S3) with presigned URLs, create ingestion jobs and follow progress.
* Review screen showing writer output, verifier output and sources side by side; approve, reject, request changes, publish, unpublish.
* Only published content is shown or cached. WordPress never stores claims or evidence and never runs AI models.

== Installation ==

1. Upload the ZIP in Plugins → Add New → Upload Plugin and activate.
2. Add to wp-config.php (recommended):
   define( 'TK_API_SECRET', '…service key secret…' );
   define( 'TK_WEBHOOK_SECRET', '…webhook secret…' );
3. Trial Knowledge → Settings: API base URL and Key ID; run "Test connection".
4. Configure the API's WP_CALLBACK_URL to the webhook URL shown on the settings screen.
5. Settings → Permalinks → Save (refreshes rewrite rules) if the public URLs return 404.

== Changelog ==

= 2.3.0 =
* New home shortcode [tk_start]: what the site is, a neutrality line (an indictment is the prosecution's allegations; presumption of innocence), the three cases (4000, 2000, 1000), the indictment in brief, where the trial stands (latest hearing + counts), witnesses, entry links and Ask. Optional attributes override the entry URLs: glossary, timeline, witnesses, decisions, motions, responses, notices; ask="0" hides Ask.
* New virtual pages: /case/{key}/ (banner "allegations, not findings", what the indictment alleges, charges, people, case timeline by year with day/month/year precision, related hearings, source document; a friendly "in preparation" page until the guide is published), /witness/{slug}/, /timeline/ (?tk_case=4000 preselects a case), /witnesses/, /glossary/.
* Dual-track timeline (assets/timeline.js, no dependencies): "מה קרה (לפי כתב האישום)" and "המשפט"; zoom years → months → days with +/−, clickable periods and a breadcrumb; case, track and event-type filters; detail panel with citations and links; on phones a year-grouped list with sticky headers. Without JS a plain grouped list is shown.
* Glossary tooltips (assets/glossary.js): the first occurrence of each term per section inside .tk-glossable texts becomes an accessible popover with a link to the glossary entry (or the case page).
* Hearing pages are organised in tabs: בקצרה, שאלות ותשובות מרכזיות, הפרוטוקול המלא, מסמך המקור. The tab is kept in the URL and in the transcript pager links; without JS the tabs are anchors. Witnesses link to their witness pages.
* Review screen: guide artifacts render readably (blocks with Hebrew headings, items with label/date, citations with page/lines and the quoted source text), failed gates and verifier verdicts highlighted per item; raw JSON remains available.
* Caching: guide endpoints are cached like other public reads and purged by artifact.published/unpublished webhooks (guide, case, witness, indictment) and by corpus changes; approving a guide purges them immediately.
* Before the guides are approved the pages degrade gracefully: pending case cards, no indictment section, witness pages from published hearing digests, timeline with the trial track only.

= 2.2.2 =
* Compact citations in digests, short affirmed/denied badges, no repeated type label in the timeline.

= 2.2.1 =
* Hearing pages show the full protocol page by page (speakers, line numbers, verified Q/A labels, link to the original PDF).
* New document pages (/document/{sv_id}/) for decisions, motions, responses, notices and affidavits.
* New shortcode [tk_documents type="" limit=""]; the hearing timeline also lists dated documents.
* Citation pages link to the passage inside the full document.
* Rewrite rules refresh automatically after an update.

= 2.1.0 =
* First release for spec v2.1.
