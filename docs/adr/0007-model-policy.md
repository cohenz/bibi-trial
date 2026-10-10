# ADR-0007: Model policy

* **No model names in code.** Every role (`extractor, mapper, judicial_classifier, writer, qa_relation, verifier, embedder`) is configured by environment and recorded in `ntk.model_registry`.
* **Lite-class models** (`lite|nano|mini|tiny|small` in the id) are accepted only as `extractor`/`qa_relation`; configuring one as judicial classifier, verifier, mapper or writer fails at startup (`ModelPolicyError`).
* **Verifier family.** `NTK_VERIFIER_PROVIDER` may point to another provider. When writer and verifier share a family (Gemini-only pilot) the registry reports `single_family=True`, and gates send every sensitive item, every judicial classification and every "the witness affirmed" wording to human review. Adding a provider means implementing `ModelProvider.generate_json/embed`; contracts do not change.
* **Every call is recorded** in `ntk.model_runs`: provider, family, model id/version, prompt version, schema version, temperature, corpus version, input hash, input source ids, output hash, token usage, duration, status, validation errors.
* **Invalid output** (non-JSON, contract violation, ids not present in the input) is stored as `invalid_output` with errors and never becomes a valid object; the caller opens a review task.
* **Mock provider.** A deterministic offline provider for development/CI. Its artifacts carry `model_family=mock`, and both the gate and the publish action refuse them outside `development`/`test`.
