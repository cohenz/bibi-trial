# ADR-0009: Project 315 adapter without a real export

No real export was provided. Per the brief, development is not blocked and no final mapping is invented:
* The adapter accepts a **canonical snapshot** (keys = spec §5.2 field names) or any JSON/CSV plus a **mapping file** (`canonical_field → source column`).
* A synthetic, clearly-labelled fixture (`tests/fixtures/project315_sample_synthetic.json`, `example.org` URLs) exercises every rule (required fields, broken URL, duplicate, unparseable date, unknown involvement value, no linked source, classification change → version + diff).
* `docs/project315-adapter.md` lists exactly what a real sample must contain to finish the mapping. Reuse terms should be confirmed with the project before importing its data.
