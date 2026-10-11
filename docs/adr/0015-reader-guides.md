# ADR-0015: Reader guides — entry points over the record

**Status:** accepted (11.10.2026, operator decision: tools א, ב, ג, ד, ז, ח)

## Context
The site listed hearings and documents by date. Readers who are not lawyers had no way in: what the indictment says,
what each of the three cases (1000, 2000, 4000) is about, who the witnesses are, what happened when.

## Decision
1. A new artifact type `guide` (migration 0009) with three object types: `indictment/main`, `case/<1000|2000|4000>`,
   `witness/w_<sha1(name)[:10]>`. The payload contract is `GuideObject`: titled blocks of items, every item cited to
   source units (`docs/guides-api.md`).
2. Case guides are written from the indictment only (its general part, the count, and the appendix the count refers
   to). Everything is framed as an allegation; a new gate (`allegation_framing`) rejects an offense stated as a fact,
   and the model gets one retry with the offending phrases. Witness guides are written from the witness's own turns in
   published hearings (digest-cited units first, an even sample of the rest) and the indictment's mentions of them.
3. Every guide runs the citation, support, judicial-wording, absolute-wording and provenance gates and the verifier,
   and then **always** waits for one human approval (`force_human`). These are the most read pages; there are about a
   dozen of them. Approval publishes immediately (ADR-0014).
4. Dated events in case guides feed the dual timeline (`/v2/guide/timeline`, track `story`); hearings and documents
   form track `trial`. Dates keep the precision the indictment gives (day, month, year) — a day is never invented.
5. The glossary is editorial (`ntk_common/glossary.py`), marked as general explanations not drawn from the file.

## Consequences
- Nothing about the cases is public until the operator approves the guides.
- Rebuilding a guide creates a new version that goes back to review; the published one stays live until approved.
