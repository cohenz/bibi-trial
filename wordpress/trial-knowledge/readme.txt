=== Trial Knowledge ===
Contributors: trialknowledge
Tags: knowledge base, legal, citations, rtl
Requires at least: 6.4
Tested up to: 6.6
Requires PHP: 8.1
Stable tag: 2.2.1
License: GPLv2 or later

Presentation and editorial layer for the Netanyahu trial Knowledge API.

== Description ==

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

= 2.2.1 =
* Hearing pages show the full protocol page by page (speakers, line numbers, verified Q/A labels, link to the original PDF).
* New document pages (/document/{sv_id}/) for decisions, motions, responses, notices and affidavits.
* New shortcode [tk_documents type="" limit=""]; the hearing timeline also lists dated documents.
* Citation pages link to the passage inside the full document.
* Rewrite rules refresh automatically after an update.

= 2.1.0 =
* First release for spec v2.1.
