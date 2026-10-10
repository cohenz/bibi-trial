# ADR-0008: Publication boundary and review

* Review states per spec: `draft → machine_verified | human_review_required | rejected → approved → published → superseded`.
* **Stricter than the brief:** nothing is ever published automatically — not even `machine_verified` items. Publication is an explicit, audited admin action (`/v2/admin/artifacts/{id}/publish`) and requires `approved`. Gate-rejected artifacts cannot be approved.
* Source versions have their own `publication_state`; an artifact can be published only if every cited SourceVersion is published (`include_sources=true` publishes them in the same audited action). A source with published citations cannot be withdrawn.
* Public read models (`ntk.public_source_units`, `ntk.public_chunks`, `ntk.public_artifacts`) and every public query filter on publication **before** ranking or generation. Ask the Trial reads only these.
* Each publish/unpublish bumps the corpus version (`cv-NNNNNN`) and enqueues a WordPress cache-purge webhook (outbox table, retried with backoff).
* Bi-temporal claim status (`valid_during`, `recorded_during`): `GET /v2/claims/{id}?as_of=&known_at=` answers both "status at date X" and "what did the site know at time Y".
