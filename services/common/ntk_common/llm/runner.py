"""Executes a model task end-to-end with contracts and run records.

For every call a ``ModelRunRecord`` is produced (spec §17 / brief): provider,
model id/version, prompt version, temperature, schema version, timing, token
usage, input source ids, input/output hashes, status and validation errors.

Idempotency: the run id is UUIDv5(task, model, prompt version, input hash).
If a successful run with that id exists in the ``RunStore`` it is reused and
the provider is not called again.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from .. import contracts, ids
from .prompts import ALL as PROMPTS
from .prompts import ROLE_FOR_TASK
from .providers import ModelProvider, ProviderError, backoff_sleep
from .registry import ModelRegistry, ModelSpec


@dataclass
class ModelRunRecord:
    id: str
    task_type: str
    role: str
    provider: str
    model_family: str
    model_id: str
    model_version: str
    prompt_version: str
    schema_version: str
    corpus_version: str
    temperature: float
    input_hash: str
    input: dict
    input_source_ids: list[str]
    output: dict
    output_hash: str | None
    usage: dict
    status: str  # succeeded | invalid_output | provider_error | rejected_by_gate
    validation_errors: list[dict] = field(default_factory=list)
    duration_ms: int = 0
    error: dict | None = None
    registry_id: str = ""
    created_at: str = field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat())

    @property
    def ok(self) -> bool:
        return self.status == "succeeded"


class RunStore(Protocol):
    def get_run(self, run_id: str) -> ModelRunRecord | None: ...
    def save_run(self, run: ModelRunRecord) -> None: ...


class MemoryRunStore:
    def __init__(self) -> None:
        self.runs: dict[str, ModelRunRecord] = {}

    def get_run(self, run_id: str) -> ModelRunRecord | None:
        return self.runs.get(run_id)

    def save_run(self, run: ModelRunRecord) -> None:
        self.runs[run.id] = run

    def invalidate_run(self, run_id: str, errors: list[dict]) -> None:
        run = self.runs.get(run_id)
        if run is not None:
            run.status, run.validation_errors = "invalid_output", errors


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.S)


_ID_IN_TEXT = re.compile(r"\b(?:su|qx|sv|hr|rc)_[0-9a-f]{26}\b")


def split_joined_ids(obj: Any) -> Any:
    """Models sometimes return ["su_a, su_b"] instead of ["su_a", "su_b"]. Split such list items; nothing else changes."""
    if isinstance(obj, dict):
        return {k: split_joined_ids(v) for k, v in obj.items()}
    if isinstance(obj, list):
        out: list[Any] = []
        for v in obj:
            if isinstance(v, str) and len(_ID_IN_TEXT.findall(v)) > 1:
                out.extend(_ID_IN_TEXT.findall(v))
            else:
                out.append(split_joined_ids(v))
        return out
    return obj


def parse_json_text(text: str) -> Any:
    t = _FENCE.sub("", text.strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start : end + 1])
        raise


SemanticCheck = Callable[[dict], list[dict]]


class ModelRunner:
    def __init__(self, registry: ModelRegistry, providers: dict[str, ModelProvider], store: RunStore,
                 *, max_retries: int = 3, sleep: Callable[[int], None] = backoff_sleep):
        self.registry = registry
        self.providers = providers
        self.store = store
        self.max_retries = max_retries
        self.sleep = sleep

    def provider_for(self, spec: ModelSpec) -> ModelProvider:
        if spec.provider not in self.providers:
            raise KeyError(f"no provider instance for {spec.provider!r}")
        return self.providers[spec.provider]

    def request_for(self, task_type: str, payload: dict, *, role: str | None = None) -> dict:
        """Everything that identifies a model call: the run id (deterministic), the prompt texts and the schema.
        Used by the batch path: a request answered by a batch is saved under the same run id, so the regular
        ``run()`` later finds it in the run store and does not call the model again."""
        prompt = PROMPTS[task_type]
        role = role or ROLE_FOR_TASK[task_type]
        spec = self.registry.get(role)
        user = prompt.render_user(payload)
        input_hash = ids.sha256_json({"system": prompt.system, "user": user, "schema": prompt.schema})
        run_id = str(ids.derived_uuid("model_run", task_type, spec.provider, spec.model_id, prompt.version, input_hash))
        return {"run_id": run_id, "task_type": task_type, "role": role, "spec": spec, "prompt": prompt, "user": user,
                "input_hash": input_hash, "response_schema": contracts.json_schema_for(prompt.schema)}

    def run(self, task_type: str, payload: dict, *, input_source_ids: list[str], corpus_version: str,
            semantic_check: SemanticCheck | None = None, role: str | None = None,
            thinking: str | None = None) -> ModelRunRecord:
        req = self.request_for(task_type, payload, role=role)
        spec, prompt = req["spec"], req["prompt"]
        cached = self.store.get_run(req["run_id"])
        if cached is not None and cached.ok:
            # a stored answer (e.g. from the Batch API, recorded without this check) is checked again before reuse;
            # one that cites unknown passages is marked invalid and the model is asked again, once
            stale = semantic_check(cached.output) if semantic_check else []
            if not stale:
                return cached
            invalidate = getattr(self.store, "invalidate_run", None)
            if invalidate:
                invalidate(cached.id, stale[:20])

        provider = self.provider_for(spec)
        started = time.monotonic()
        last_error: ProviderError | None = None
        result = None
        for attempt in range(self.max_retries + 1):
            try:
                result = provider.generate_json(model_id=spec.model_id, system=prompt.system, user=req["user"],
                                                temperature=spec.temperature, task_type=task_type, payload=payload,
                                                response_schema=req["response_schema"],
                                                **({"thinking": thinking} if thinking else {}))
                break
            except ProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt >= self.max_retries:
                    break
                self.sleep(attempt)
        return self.record(req, result, payload=payload, input_source_ids=input_source_ids, corpus_version=corpus_version,
                           semantic_check=semantic_check, duration_ms=int((time.monotonic() - started) * 1000),
                           error=last_error)

    def record(self, req: dict, result: Any, *, payload: dict | None, input_source_ids: list[str], corpus_version: str,
               semantic_check: SemanticCheck | None = None, duration_ms: int = 0, error: Any = None) -> ModelRunRecord:
        """Validate a provider result against the contract and save the run (also used for batch results)."""
        spec, prompt, task_type = req["spec"], req["prompt"], req["task_type"]
        base = dict(
            id=req["run_id"], task_type=task_type, role=req["role"], provider=spec.provider, model_family=spec.model_family,
            model_id=spec.model_id, prompt_version=prompt.version, schema_version=f"{prompt.schema}@2.0",
            corpus_version=corpus_version, temperature=spec.temperature, input_hash=req["input_hash"],
            input={"payload_sha256": ids.sha256_json(payload) if payload is not None else None,
                   "source_ids": input_source_ids[:2000]},
            input_source_ids=input_source_ids, duration_ms=duration_ms, registry_id=spec.registry_id,
        )
        if result is None:
            run = ModelRunRecord(**base, model_version=spec.model_id, output={}, output_hash=None, usage={},
                                 status="provider_error",
                                 error={"message": str(error)[:500], "status": getattr(error, "status", None)})
            self.store.save_run(run)
            return run

        errors: list[dict] = []
        output: dict = {}
        try:
            parsed = parse_json_text(result.text)
            if not isinstance(parsed, dict):
                raise ValueError("model output is not a JSON object")
            output = split_joined_ids(parsed)
            contracts.validate(prompt.schema, output)
            if semantic_check:
                errors.extend(semantic_check(output))
        except contracts.ContractError as ce:
            errors.extend(ce.errors)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append({"path": "/", "message": f"invalid JSON: {exc}"[:300], "validator": "json"})
        status = "succeeded" if not errors else "invalid_output"
        run = ModelRunRecord(
            **base,
            model_version=result.model_version or spec.model_id,
            output=output if status == "succeeded" else {"raw_text_sha256": ids.sha256_text(result.text)},
            output_hash=ids.sha256_json(output) if output else None,
            usage=result.usage or {},
            status=status,
            validation_errors=errors,
        )
        self.store.save_run(run)
        return run


def unknown_ids_check(allowed: set[str], *paths: str) -> SemanticCheck:
    """Semantic check: every id at the given JSON paths must be in ``allowed``.

    Paths use ``a.b[].c`` notation, e.g. ``summary_sentences[].source_unit_ids[]``."""

    def walk(obj: Any, parts: list[str]) -> list[Any]:
        if not parts:
            return [obj]
        head, rest = parts[0], parts[1:]
        if head.endswith("[]"):
            key = head[:-2]
            seq = obj.get(key, []) if key else obj
            out = []
            for item in seq or []:
                out.extend(walk(item, rest))
            return out
        if isinstance(obj, dict) and head in obj:
            return walk(obj[head], rest)
        return []

    def check(output: dict) -> list[dict]:
        errs = []
        for path in paths:
            for value in walk(output, path.split(".")):
                if value is not None and value not in allowed:
                    errs.append({"path": path, "message": f"unknown id {value!r} not in input", "validator": "unknown_id"})
        return errs

    return check
