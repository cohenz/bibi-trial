"""Model providers.

``GeminiProvider`` talks to the Gemini REST API (generateContent /
batchEmbedContents). ``MockProvider`` is a deterministic offline provider
used for development and tests; artifacts produced by it are marked with
model_family ``mock`` and the publication gate refuses them outside
development/test environments.

Providers return raw text; JSON parsing and contract validation happen in
``ntk_common.llm.runner`` so every provider is held to the same contracts.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .. import hebrew


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = True, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass
class ProviderResult:
    text: str
    usage: dict = field(default_factory=dict)
    model_version: str | None = None
    raw: dict | None = None


class ModelProvider(Protocol):
    name: str

    def generate_json(self, *, model_id: str, system: str, user: str, temperature: float, task_type: str,
                      payload: dict | None = None, response_schema: dict | None = None) -> ProviderResult: ...

    def embed(self, *, model_id: str, texts: list[str], dim: int, task: str) -> list[list[float]]: ...


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, base_url: str, timeout: int = 120, session: Any = None):
        import requests

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:  # may be injected by an egress proxy instead
            h["x-goog-api-key"] = self.api_key
        return h

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}/{path}"
        try:
            resp = self.session.post(url, headers=self._headers(), data=json.dumps(body), timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 - network errors are retryable
            raise ProviderError(f"gemini request failed: {type(exc).__name__}", retryable=True) from exc
        if resp.status_code >= 400:
            retryable = resp.status_code in {408, 429, 500, 502, 503, 504}
            # never echo request bodies or keys; response text is truncated
            raise ProviderError(f"gemini HTTP {resp.status_code}: {resp.text[:300]}", retryable=retryable, status=resp.status_code)
        return resp.json()

    def generate_json(self, *, model_id: str, system: str, user: str, temperature: float, task_type: str,
                      payload: dict | None = None, response_schema: dict | None = None) -> ProviderResult:
        """``response_schema`` (the output contract) constrains decoding via ``responseJsonSchema``. If the API
        rejects the schema (HTTP 400), the call is repeated once with the schema written into the prompt instead;
        the contract is validated afterwards either way."""
        gen: dict[str, Any] = {"temperature": temperature, "responseMimeType": "application/json"}
        if response_schema:
            gen["responseJsonSchema"] = gemini_schema(response_schema)
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen,
        }
        try:
            data = self._post(f"models/{model_id}:generateContent", body)
        except ProviderError as exc:
            if not (response_schema and exc.status == 400):
                raise
            gen.pop("responseJsonSchema", None)
            schema_text = json.dumps(response_schema, ensure_ascii=False)
            body["contents"] = [{"role": "user", "parts": [{"text": user + "\n<output_json_schema>\n" + schema_text
                                                             + "\n</output_json_schema>"}]}]
            data = self._post(f"models/{model_id}:generateContent", body)
        cands = data.get("candidates") or []
        if not cands:
            fb = data.get("promptFeedback", {})
            raise ProviderError(f"gemini returned no candidates (blockReason={fb.get('blockReason')})", retryable=False)
        parts = cands[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        usage = data.get("usageMetadata", {})
        return ProviderResult(text=text, usage=usage, model_version=data.get("modelVersion"), raw=None)

    def embed(self, *, model_id: str, texts: list[str], dim: int, task: str) -> list[list[float]]:
        task_type = "RETRIEVAL_QUERY" if task == "query" else "RETRIEVAL_DOCUMENT"
        out: list[list[float]] = []
        for i in range(0, len(texts), 100):
            batch = texts[i : i + 100]
            body = {
                "requests": [
                    {"model": f"models/{model_id}", "content": {"parts": [{"text": t}]}, "taskType": task_type,
                     "outputDimensionality": dim}
                    for t in batch
                ]
            }
            data = self._post(f"models/{model_id}:batchEmbedContents", body)
            for emb in data.get("embeddings", []):
                out.append(_l2(emb.get("values", [])))
        if len(out) != len(texts):
            raise ProviderError("embedding count mismatch", retryable=True)
        return out


# JSON Schema keywords Gemini's responseJsonSchema accepts; others (pattern, minLength, format, ...) are dropped here
# and still enforced by contract validation after the call
_GEMINI_KEYWORDS = {"type", "properties", "required", "items", "enum", "anyOf", "additionalProperties", "minItems",
                    "maxItems", "minimum", "maximum", "description"}


def gemini_schema(schema: Any) -> Any:
    """Translate a contract (JSON Schema 2020-12) into the subset Gemini's structured output accepts."""
    if isinstance(schema, list):
        return [gemini_schema(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    if "const" in schema:  # const → single-value enum
        c = schema["const"]
        out["enum"] = [c]
        out["type"] = "string" if isinstance(c, str) else ("boolean" if isinstance(c, bool) else "number")
    for k, v in schema.items():
        if k not in _GEMINI_KEYWORDS:
            continue
        if k == "properties":
            out[k] = {name: gemini_schema(sub) for name, sub in v.items()}
        elif k in {"items", "additionalProperties"} and isinstance(v, dict):
            out[k] = gemini_schema(v)
        elif k == "anyOf":
            out[k] = [gemini_schema(x) for x in v]
        else:
            out[k] = v
    if "enum" in out and "type" not in out and all(isinstance(x, str) for x in out["enum"]):
        out["type"] = "string"
    return out


def _l2(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


# ---------------------------------------------------------------------------
# Mock (deterministic, offline)
# ---------------------------------------------------------------------------

class MockProvider:
    """Deterministic stand-in for development and CI.

    It implements every task type with transparent rules over the inputs it
    receives, so the full pipeline, gates and contracts can be exercised
    without network access. It is *not* a summariser: its texts are short
    extractive statements built from the cited units."""

    name = "mock"

    def generate_json(self, *, model_id: str, system: str, user: str, temperature: float, task_type: str,
                      payload: dict | None = None, response_schema: dict | None = None) -> ProviderResult:
        payload = payload or {}
        fn = getattr(self, f"_task_{task_type}", None)
        if fn is None:
            raise ProviderError(f"mock provider has no task {task_type!r}", retryable=False)
        out = fn(payload)
        text = json.dumps(out, ensure_ascii=False)
        return ProviderResult(text=text, usage={"promptTokenCount": len(user) // 4, "candidatesTokenCount": len(text) // 4},
                              model_version=f"{model_id}-v1")

    def embed(self, *, model_id: str, texts: list[str], dim: int, task: str) -> list[list[float]]:
        return [hash_embedding(t, dim) for t in texts]

    # -- tasks ---------------------------------------------------------------
    @staticmethod
    def _first_words(text: str, n: int = 18) -> str:
        words = text.replace("\n", " ").split()
        return " ".join(words[:n]) + ("…" if len(words) > n else "")

    def _task_digest(self, p: dict) -> dict:
        units = p.get("units", [])
        sentences = []
        seen_speakers: set[str] = set()
        for u in units:
            if u.get("unit_type") in {"caption"} or len(u.get("text", "").split()) < 4:
                continue
            spk = u.get("speaker") or "לא מזוהה"
            if spk in seen_speakers and len(sentences) >= 3:
                continue
            seen_speakers.add(spk)
            verb = "שאל" if u.get("unit_type") == "question" else ("השיב" if u.get("unit_type") == "answer" else "אמר")
            sentences.append({"text": f"{spk} {verb}: \"{self._first_words(u['text'])}\"", "source_unit_ids": [u["id"]]})
            if len(sentences) >= 6:
                break
        if not sentences and units:
            u = units[0]
            sentences.append({"text": f"תיעוד: \"{self._first_words(u['text'])}\"", "source_unit_ids": [u["id"]]})
        counts: dict[str, int] = {}
        for u in units:
            for t in hebrew.tokens(u.get("text", "")):
                if hebrew.is_hebrew_word(t) and len(t) >= 4:
                    counts[t] = counts.get(t, 0) + 1
        topics = [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]
        persons = sorted({u["speaker"] for u in units if u.get("speaker")})
        notable = [e["id"] for e in p.get("exchanges", []) if e.get("answer_relation") in {"affirms", "denies"}][:10]
        judicial = [u["id"] for u in units if u.get("speaker_role") in {"judge", "court"}][:20]
        return {
            "schema_version": "2.0",
            "summary_sentences": sentences,
            "topics": topics,
            "persons": persons,
            "exhibits": sorted({t for u in units for t in hebrew.tokens(u.get("text", "")) if t[:2] in {"ת/", "נ/"}}),
            "dates": [],
            "claims_mentioned": [],
            "notable_exchange_ids": notable,
            "judicial_candidate_unit_ids": judicial,
        }

    def _task_judicial(self, p: dict) -> dict:
        out = []
        for c in p.get("candidates", []):
            text = c.get("text", "")
            role = c.get("speaker_role")
            if c.get("unit_type") == "decision":
                level, conf = "procedural_decision", 0.8
            elif "?" in text:
                level, conf = "question_or_comment", 0.85
            elif role in {"judge", "court"}:
                level, conf = "interim_observation", 0.6
            else:
                out.append({"source_unit_id": c["id"], "is_judicial": False, "level": None, "summary": None, "confidence": 0.9})
                continue
            out.append({"source_unit_id": c["id"], "is_judicial": True, "level": level,
                        "summary": self._first_words(text, 14), "confidence": conf})
        return {"schema_version": "2.0", "classifications": out}

    def _task_map_claim(self, p: dict) -> dict:
        claim_terms = set(hebrew.search_terms(p.get("claim_text", "") + " " + p.get("question", "")))
        evidence = []
        for u in p.get("candidates", []):
            terms = set(hebrew.search_terms(u.get("text", "")))
            overlap = len(claim_terms & terms)
            if overlap < 3:
                continue
            text = u.get("text", "")
            negated = any(w in hebrew.tokens(text)[:4] for w in ("לא", "ממש", "מעולם", "שולל"))
            direction = "weakens" if negated else "supports"
            role = u.get("speaker_role")
            attribution = {
                "witness": "witness_said", "judge": "judge_commented", "court": "court_decided",
                "prosecution": "prosecution_argued", "defense": "defense_argued",
            }.get(role or "", "document_states")
            if u.get("unit_type") == "question":
                attribution = "judge_asked" if role == "judge" else "counsel_asked"
                direction = "contextual"
            if u.get("exchange_id") and u.get("answer_relation") == "affirms":
                attribution = "witness_affirmed_question"
            evidence.append({
                "source_unit_ids": [u["id"]] + ([u["paired_unit_id"]] if u.get("paired_unit_id") else []),
                "direction": direction,
                "summary": f"{u.get('speaker') or 'מקור'}: \"{self._first_words(text, 16)}\"",
                "attribution": attribution,
                "exchange_id": u.get("exchange_id"),
                "rationale": f"lexical overlap {overlap}",
            })
        return {"schema_version": "2.0", "claim_id": p["claim_id"], "evidence": evidence[:12],
                "unresolved_questions": [], "decomposition": []}

    def _task_verify(self, p: dict) -> dict:
        units = {u["id"]: u for u in p.get("sources", [])}
        out = []
        for a in p.get("assertions", []):
            cited = [units[c] for c in a.get("citation_ids", []) if c in units]
            a_terms = set(hebrew.search_terms(a.get("text", "")))
            best = 0.0
            for u in cited:
                u_terms = set(hebrew.search_terms(u.get("text", "")))
                if a_terms:
                    best = max(best, len(a_terms & u_terms) / max(1, min(len(a_terms), 25)))
            supported = "yes" if best >= 0.35 else ("partial" if best >= 0.15 else "no")
            if not cited:
                supported = "no"
            overstated = any(w in a.get("text", "") for w in ("קבע", "הכריע", "פסק")) and not any(
                u.get("judicial_level") in {"procedural_decision", "substantive_ruling"} for u in cited
            )
            out.append({"path": a["path"], "supported": supported, "attribution_ok": True,
                        "judicial_overstatement": overstated, "false_premise": False, "note": None})
        verdict = "pass" if out and all(x["supported"] != "no" and not x["judicial_overstatement"] for x in out) else "fail"
        return {"schema_version": "2.0", "assertions": out, "omitted_counterevidence": [], "verdict": verdict}

    def _task_answer(self, p: dict) -> dict:
        ctx = p.get("context", [])
        if not ctx:
            return {"schema_version": "2.0", "answer_status": "insufficient_published_evidence",
                    "answer_short": "לא נמצא חומר מפורסם שמאפשר לענות על השאלה.", "answer_short_citation_ids": [],
                    "sections": [], "premise_issues": []}
        q_terms = set(hebrew.search_terms(p.get("question", "")))
        scored = sorted(ctx, key=lambda c: -len(q_terms & set(hebrew.search_terms(c.get("text", "")))))
        top = scored[:3]
        sections = []
        for c in top:
            kind = {"supports": "supports", "weakens": "weakens", "court": "court_position"}.get(c.get("bucket", ""), "why")
            sections.append({"kind": kind, "text": f"{c.get('attribution') or c.get('speaker') or 'במקור'}: \"{self._first_words(c['text'], 22)}\"",
                             "citation_ids": [c["id"]]})
        sections.append({"kind": "limitation", "text": "התשובה מבוססת רק על החומר שפורסם במאגר עד מועד התשובה.", "citation_ids": []})
        lead = top[0]
        who = lead.get("attribution") or lead.get("speaker") or "במקור"
        return {"schema_version": "2.0", "answer_status": "answered",
                "answer_short": f"{who}: \"{self._first_words(lead['text'], 20)}\"",
                "answer_short_citation_ids": [lead["id"]], "sections": sections, "premise_issues": []}

    # guides: extractive, every item quotes the unit it cites and is framed as an allegation
    def _guide_items(self, units: list[dict], n: int, prefix: str = "לפי כתב האישום, ") -> list[dict]:
        out = []
        for u in units:
            if len(u.get("text", "").split()) < 6:
                continue
            out.append({"text": prefix + self._first_words(u["text"], 16), "source_unit_ids": [u["id"]]})
            if len(out) >= n:
                break
        return out

    def _task_indictment_overview(self, p: dict) -> dict:
        units = p.get("units", [])
        items = self._guide_items(units, 4) or [{"text": "לפי כתב האישום, מסמך", "source_unit_ids": [units[0]["id"]]}]
        defs = []
        for u in units:
            m = re.search(r"^\s*\d+\.\s*([א-ת'\"]+\s+[א-ת'\"]+)", u.get("text", ""))
            if m and "הנאשם" in u.get("text", ""):
                defs.append({"name": m.group(1), "text": "לפי כתב האישום, " + self._first_words(u["text"], 12),
                             "case_keys": [k for k in p.get("counts", [])][:1], "source_unit_ids": [u["id"]]})
        return {"schema_version": "2.0", "overview": items, "defendants": defs[:4]}

    def _task_case_guide(self, p: dict) -> dict:
        units = p.get("units", [])
        items = self._guide_items(units, 8) or [{"text": "לפי כתב האישום, מסמך", "source_unit_ids": [units[0]["id"]]}]
        events = []
        for u in units:
            m = re.search(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})", u.get("text", ""))
            if m:
                d = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
                events.append({"date": d, "date_precision": "day", "title": self._first_words(u["text"], 5),
                               "text": "לפי כתב האישום, " + self._first_words(u["text"], 14), "source_unit_ids": [u["id"]]})
        return {"schema_version": "2.0", "case_key": p.get("case_key", "4000"), "subtitle": "תיאור התיק",
                "one_line": items[0], "alleged": items[1:] or items, "people": [], "charges": [], "events": events[:40]}

    def _task_witness_guide(self, p: dict) -> dict:
        role = self._guide_items(p.get("indictment_mentions", []), 1)
        testimony = []
        for h in p.get("hearings", []):
            testimony += self._guide_items(h.get("units", []), 2, prefix=f"בדיון מיום {h.get('date')}: ")
        return {"schema_version": "2.0", "role": role, "testimony": testimony[:10]}

    def _task_document_brief(self, p: dict) -> dict:
        units = [u for u in p.get("units", []) if len(u.get("text", "").split()) >= 4] or p.get("units", [])
        u0 = units[0]
        court = p.get("document_source_type") == "decision"
        lead = "בית המשפט" if court else "לפי המסמך,"
        body = " ".join(u["text"] for u in units)
        procedural = bool(re.search(r"מועד|ארכה|דחיית|הוקלט|העתק", body))
        days = []
        m = re.search(r"העיד(?:ה)?\s+(?:(עד(?:ת)?\s+(הגנה|תביעה)(?:\s+\d+)?),?\s+)?([א-ת]+\s+[א-ת]+)", body)
        d = re.search(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})", body)
        if m and d:
            src = next(u["id"] for u in units if m.group(3) in u["text"])
            days.append({"hearing_date": f"{d.group(3)}-{int(d.group(2)):02d}-{int(d.group(1)):02d}",
                         "witnesses": [{"name": m.group(3), "side": {"הגנה": "defense", "תביעה": "prosecution"}.get(m.group(2) or "", "unknown"),
                                        "description": m.group(1) or ""}],
                         "next_hearing_date": (lambda n: f"{n.group(3)}-{int(n.group(2)):02d}-{int(n.group(1)):02d}" if n else None)(
                             re.search(r"הדיון הבא[^0-9]*(\d{1,2})\.(\d{1,2})\.(20\d{2})", body)),
                         "source_unit_ids": [src]})
        return {"schema_version": "2.0",
                "title": {"text": self._first_words(u0["text"], 8), "source_unit_ids": [u0["id"]]},
                "summary": [{"text": f"{lead} {self._first_words(u['text'], 16)}", "source_unit_ids": [u["id"]]} for u in units[:2]],
                "significance": "procedural" if procedural else "substantive",
                "significance_reason": "כלל מילים של עניינים טכניים" if procedural else "תוכן מהותי",
                "hearing_days": days}

    def _task_classify_document(self, p: dict) -> dict:
        from ..inbox import classify_by_rules

        c = classify_by_rules(p.get("first_pages", ""), p.get("last_page", ""), p.get("filename", ""))
        return {"schema_version": "2.0", "source_type": c.source_type, "title": c.title or "מסמך",
                "document_date": c.document_date, "court_case_numbers": c.case_numbers, "author": None,
                "hearing_date": c.hearing_date, "confidence": c.confidence, "rationale": "mock: rules"}

    def _task_qa_relation(self, p: dict) -> dict:
        from ..pipeline.qa import classify_answer

        items = []
        for e in p.get("exchanges", []):
            rel, conf, _ = classify_answer(e.get("question", ""), e.get("answer", ""))
            items.append({"exchange_id": e["id"], "answer_relation": rel, "interpreted_proposition": None, "confidence": conf})
        return {"schema_version": "2.0", "items": items}


def hash_embedding(text: str, dim: int) -> list[float]:
    """Deterministic bag-of-ngrams embedding (feature hashing) for offline use.

    Captures lexical similarity only; quality is far below a real model and it
    is never used in production."""
    vec = [0.0] * dim
    grams = hebrew.char_ngrams(text) + hebrew.search_terms(text)
    for g in grams:
        h = int.from_bytes(hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest(), "big")
        idx = h % dim
        vec[idx] += 1.0 if (h >> 63) & 1 else -1.0
    return _l2(vec)


def build_provider(name: str, *, api_key: str = "", base_url: str = "", timeout: int = 120) -> ModelProvider:
    n = (name or "mock").lower()
    if n == "mock":
        return MockProvider()
    if n == "gemini":
        return GeminiProvider(api_key=api_key, base_url=base_url or "https://generativelanguage.googleapis.com/v1beta",
                              timeout=timeout)
    raise ValueError(f"unknown model provider {name!r}; implement ModelProvider for it (ADR-0007)")


def backoff_sleep(attempt: int, base: float = 1.0, cap: float = 30.0) -> None:
    time.sleep(min(cap, base * (2 ** attempt)))
