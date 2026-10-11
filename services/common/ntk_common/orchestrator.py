"""Staged, resumable ingestion pipeline (spec §27.2, build brief "pipeline").

Stages: register → download → validate → extract_text → ocr_fallback →
lineize → segment → pair → chunk → embed → extract_a → map_b → verify →
review → publish.

Each stage records status, attempts, checkpoint and output in
ntk.ingestion_job_stages. A stage that already succeeded is skipped on
retry, so a failure never forces a restart from the beginning. Every stage
is idempotent: re-running with the same bytes and versions writes nothing new.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import logging
import socket
import traceback
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import Engine

from . import hebrew, ids
from .config import Settings
from .db import knowledge as kdb
from .db import ops, sources
from .db.core import row, rows, scalar
from .db.public import units_by_ids
from .layers import ClaimView, ExchangeView, UnitView, build_claim_bundle, build_hearing_digest
from .llm.providers import build_provider
from .llm.registry import ModelRegistry
from .llm.runner import ModelRunner
from .pipeline import pdf as pdfmod
from .pipeline.chunking import build_chunks
from .pipeline.document import parse_document
from .pipeline.pdf import ExtractedDocument, Line, PageText
from .pipeline.protocol import PARSER_VERSION, parse_protocol
from .pipeline.qa import pair_exchanges
from .search.base import SearchFilters, SearchRequest
from .search.postgres import PostgresSearchBackend
from .storage import Storage, build_storage

log = logging.getLogger("ntk.pipeline")

STAGES = ops.PROTOCOL_STAGES


class StageError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass
class Services:
    settings: Settings
    engine: Engine
    storage: Storage | None
    registry: ModelRegistry
    runner: ModelRunner
    embedder: Any

    def search_backend(self, *, use_vector: bool = True) -> PostgresSearchBackend:
        return PostgresSearchBackend(self.engine, self.embedder if use_vector else None)


def build_services(settings: Settings, engine: Engine, *, storage: Storage | None = None) -> Services:
    registry = ModelRegistry.from_settings(settings)
    providers = {}
    for spec_role in ("extractor", "mapper", "judicial_classifier", "writer", "qa_relation", "verifier"):
        sp = registry.get(spec_role)
        if sp.provider not in providers:
            if sp.provider == "gemini":
                key = settings.gemini_api_key if spec_role != "verifier" or not settings.verifier_api_key else settings.verifier_api_key
                providers[sp.provider] = build_provider("gemini", api_key=key, base_url=settings.gemini_base_url,
                                                        timeout=settings.model_timeout_seconds)
            else:
                providers[sp.provider] = build_provider(sp.provider, api_key=settings.verifier_api_key,
                                                        base_url=settings.verifier_base_url, timeout=settings.model_timeout_seconds)
    runner = ModelRunner(registry, providers, ops.PgRunStore(engine), max_retries=settings.model_max_retries)
    emb_spec = registry.get("embedder")
    emb_provider = build_provider(emb_spec.provider, api_key=settings.embedding_api_key,
                                  base_url=settings.gemini_base_url, timeout=settings.model_timeout_seconds)

    def embed_one(text: str) -> list[float]:
        return emb_provider.embed(model_id=emb_spec.model_id, texts=[text], dim=settings.embedding_dim, task="query")[0]

    embed_one.batch = lambda texts: emb_provider.embed(model_id=emb_spec.model_id, texts=texts,  # type: ignore[attr-defined]
                                                       dim=settings.embedding_dim, task="document")
    embed_one.model_id = emb_spec.model_id  # type: ignore[attr-defined]
    if storage is None:
        try:
            storage = build_storage(settings)
        except Exception as exc:  # noqa: BLE001 - storage may be unconfigured in some commands
            log.warning("storage not configured: %s", exc)
            storage = None
    return Services(settings, engine, storage, registry, runner, embed_one)


# ---------------------------------------------------------------------------
# SSRF-safe fetch for manifest URLs
# ---------------------------------------------------------------------------
def safe_fetch(url: str, *, allowlist: tuple[str, ...], max_bytes: int, timeout: int = 60) -> tuple[bytes, dict]:
    import requests

    p = urlparse(url)
    if p.scheme != "https":
        raise StageError("fetch_blocked", "only https URLs may be fetched")
    host = (p.hostname or "").lower()
    if host not in allowlist:
        raise StageError("fetch_blocked", f"host {host!r} is not in NTK_FETCH_ALLOWLIST")
    try:
        for info in socket.getaddrinfo(host, 443):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise StageError("fetch_blocked", f"{host} resolves to a non-public address")
    except socket.gaierror:
        pass  # proxied environments resolve remotely; the proxy enforces egress
    with requests.get(url, stream=True, timeout=timeout, allow_redirects=False) as r:
        if r.status_code in {301, 302, 303, 307, 308}:
            raise StageError("fetch_blocked", "redirects are not followed; put the final URL in the manifest")
        if r.status_code != 200:
            raise StageError("fetch_failed", f"HTTP {r.status_code}", retryable=r.status_code >= 500)
        buf = bytearray()
        for chunk in r.iter_content(65536):
            buf.extend(chunk)
            if len(buf) > max_bytes:
                raise StageError("file_too_large", "download exceeded size limit")
        headers = {k.lower(): v for k, v in r.headers.items() if k.lower() in {"etag", "last-modified", "content-type", "content-length"}}
    return bytes(buf), headers


# ---------------------------------------------------------------------------
# checkpoint (de)serialisation for extracted lines
# ---------------------------------------------------------------------------
def _pages_to_cp(pages: list[PageText]) -> list[dict]:
    return [{"page": p.page, "method": p.method, "visual_order_fixed": p.visual_order_fixed,
             "printed_line_numbers": p.printed_line_numbers, "char_count": p.char_count,
             "lines": [[ln.line_no, ln.text, ln.kind, ln.synthetic, round(ln.top, 2),
                        getattr(ln, "_margin_no", None)] for ln in p.lines]} for p in pages]


def _cp_to_pages(cp: list[dict]) -> list[PageText]:
    out = []
    for p in cp:
        pt = PageText(page=p["page"], method=p["method"], visual_order_fixed=p["visual_order_fixed"],
                      printed_line_numbers=p["printed_line_numbers"], char_count=p["char_count"])
        for no, text, kind, syn, top, margin in p["lines"]:
            ln = Line(page=p["page"], line_no=no, text=text, kind=kind, synthetic=syn, top=top)
            ln._margin_no = margin  # type: ignore[attr-defined]
            pt.lines.append(ln)
        out.append(pt)
    return out


# ---------------------------------------------------------------------------
# the pipeline
# ---------------------------------------------------------------------------
class Pipeline:
    def __init__(self, services: Services):
        self.s = services
        self.cfg = services.settings

    # utilities
    def _cp(self, job_id: str, stage: str) -> dict | None:
        with self.s.engine.connect() as conn:
            st = ops.stage_state(conn, job_id, stage)
        return (st or {}).get("checkpoint")

    def _job(self, job_id: str) -> dict:
        with self.s.engine.connect() as conn:
            job = ops.get_job(conn, job_id)
        if job is None:
            raise StageError("not_found", f"job {job_id} not found")
        return job

    def run_job(self, job_id: str, *, only: list[str] | None = None, stop_after: str | None = None) -> dict:
        job = self._job(job_id)
        targets = job.get("target_stages") or STAGES
        statuses = {s["stage"]: s["status"] for s in job["stages"]}
        for stage in targets:
            if only and stage not in only:
                continue
            if statuses.get(stage) in {"succeeded", "skipped"}:
                if stop_after == stage:
                    break
                continue
            with self.s.engine.begin() as conn:
                ops.start_stage(conn, job_id, stage)
            try:
                output, checkpoint, status = getattr(self, f"stage_{stage}")(job_id, self._job(job_id)["input"])
            except StageError as exc:
                self._fail(job_id, stage, {"code": exc.code, "message": str(exc), "retryable": exc.retryable})
                if exc.retryable:
                    raise
                return self._job(job_id)
            except Exception as exc:  # noqa: BLE001
                self._fail(job_id, stage, {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"[:500],
                                           "trace": traceback.format_exc()[-2000:], "retryable": True})
                raise
            with self.s.engine.begin() as conn:
                ops.finish_stage(conn, job_id, stage, status=status, output=output, checkpoint=checkpoint)
            if stop_after == stage:
                break
        job = self._job(job_id)
        done = all(s["status"] in {"succeeded", "skipped"} for s in job["stages"] if s["stage"] in targets)
        if done:
            with self.s.engine.begin() as conn:
                ops.finish_job(conn, job_id, status="succeeded", output=self._summary(job))
        return self._job(job_id)

    def _fail(self, job_id: str, stage: str, error: dict) -> None:
        with self.s.engine.begin() as conn:
            ops.finish_stage(conn, job_id, stage, status="failed", error=error)
            ops.finish_job(conn, job_id, status="failed", error={"stage": stage, **{k: v for k, v in error.items() if k != "trace"}})

    def _summary(self, job: dict) -> dict:
        return {s["stage"]: s.get("output") for s in job["stages"]}

    # ---- stages -----------------------------------------------------------------
    def stage_register(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        doc = inp["document"]
        case_id = inp.get("case_id") or self.cfg.case_id
        document_id = doc.get("id") or ids.source_document_id(case_id, doc.get("canonical_key") or doc.get("url") or doc["title"])
        with self.s.engine.begin() as conn:
            sources.ensure_case(conn, case_id=case_id, court_case_number=inp.get("court_case_number", self.cfg.court_case_number),
                                title=inp.get("case_title", "מדינת ישראל נ' נתניהו ואח'"),
                                court_name=inp.get("court_name", "בית המשפט המחוזי בירושלים"))
            sources.ensure_document(conn, document_id=document_id, case_id=case_id, title=doc["title"],
                                    source_type=doc.get("source_type", "protocol"), authority_tier=int(doc.get("authority_tier", 1)),
                                    source_owner=doc.get("source_owner", "הרשות השופטת"), source_stance=doc.get("source_stance"),
                                    canonical_url=doc.get("url"), default_court_record_status=doc.get("court_record_status", "unknown"),
                                    legal_access_notes=doc.get("legal_access_notes"), metadata={"hearing_date": doc.get("hearing_date")})
            ops.set_job_source_version(conn, job_id, None, document_id)  # type: ignore[arg-type]
        return {"document_id": document_id, "case_id": case_id}, {"document_id": document_id, "case_id": case_id}, "succeeded"

    def stage_download(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        src = inp["source"]
        max_b = self.cfg.max_upload_bytes
        storage = self.s.storage
        if src.get("upload_id") or src.get("s3_key"):
            if storage is None:
                raise StageError("storage_unconfigured", "object storage is not configured")
            key = src.get("s3_key")
            if src.get("upload_id"):
                with self.s.engine.connect() as conn:
                    up = ops.get_upload(conn, src["upload_id"])
                if up is None:
                    raise StageError("upload_not_found", "upload not found")
                key = up["s3_key"]
            info = storage.head(key)
            if info is None:
                raise StageError("object_missing", f"object {key} not found in bucket", retryable=True)
            data = storage.get_bytes(key, max_bytes=max_b)
            cp = {"bucket": storage.bucket, "key": key, "etag": info.etag, "version_id": info.version_id,
                  "size": len(data), "sha256": ids.sha256_bytes(data), "origin": "storage"}
        elif src.get("url"):
            data, headers = safe_fetch(src["url"], allowlist=self.cfg.fetch_allowlist, max_bytes=max_b)
            sha = ids.sha256_bytes(data)
            cp = {"url": src["url"], "headers": headers, "size": len(data), "sha256": sha, "origin": "url"}
            if storage is not None:
                key = storage.content_key(sha)
                info = storage.put_bytes(key, data, mime_type="application/pdf")
                cp.update({"bucket": storage.bucket, "key": key, "etag": info.etag, "version_id": info.version_id})
        elif src.get("local_path"):
            if self.cfg.env not in {"development", "test"}:
                raise StageError("fetch_blocked", "local_path sources are allowed only in development/test")
            with open(src["local_path"], "rb") as fh:
                data = fh.read(max_b + 1)
            if len(data) > max_b:
                raise StageError("file_too_large", "file too large")
            sha = ids.sha256_bytes(data)
            cp = {"local_path": src["local_path"], "size": len(data), "sha256": sha, "origin": "local"}
            if storage is not None:
                key = storage.content_key(sha)
                info = storage.put_bytes(key, data, mime_type="application/pdf")
                cp.update({"bucket": storage.bucket, "key": key, "etag": info.etag, "version_id": info.version_id})
        else:
            raise StageError("invalid_source", "source must have upload_id, s3_key, url or local_path")
        cp["retrieved_at"] = dt.datetime.now(dt.UTC).isoformat()
        return {k: v for k, v in cp.items() if k != "headers"}, cp, "succeeded"

    def _bytes(self, job_id: str, inp: dict) -> bytes:
        cp = self._cp(job_id, "download") or {}
        if cp.get("key") and self.s.storage is not None:
            return self.s.storage.get_bytes(cp["key"], max_bytes=self.cfg.max_upload_bytes)
        if cp.get("local_path"):
            return open(cp["local_path"], "rb").read()
        if cp.get("url"):
            data, _ = safe_fetch(cp["url"], allowlist=self.cfg.fetch_allowlist, max_bytes=self.cfg.max_upload_bytes)
            return data
        raise StageError("download_missing", "no downloaded bytes available; rerun download")

    def stage_validate(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        data = self._bytes(job_id, inp)
        dcp = self._cp(job_id, "download") or {}
        expected = inp["source"].get("expected_sha256")
        if inp["source"].get("upload_id"):
            with self.s.engine.connect() as conn:
                up = ops.get_upload(conn, inp["source"]["upload_id"])
            expected = expected or (up or {}).get("expected_sha256")
        try:
            facts = pdfmod.validate_pdf(data, declared_mime=inp["source"].get("mime_type", "application/pdf"),
                                        expected_sha256=expected, max_bytes=self.cfg.max_upload_bytes)
        except pdfmod.PdfValidationError as exc:
            if inp["source"].get("upload_id"):
                with self.s.engine.begin() as conn:
                    ops.set_upload_status(conn, inp["source"]["upload_id"], "rejected")
            raise StageError(exc.code, str(exc)) from exc
        reg = self._cp(job_id, "register") or {}
        doc = inp["document"]
        with self.s.engine.begin() as conn:
            svid, created = sources.insert_source_version(
                conn, document_id=reg["document_id"], content_sha256=facts["content_sha256"],
                retrieved_at=dcp.get("retrieved_at") or dt.datetime.now(dt.UTC), mime_type="application/pdf",
                size_bytes=facts["size_bytes"], object_uri=(self.s.storage.uri(dcp["key"]) if dcp.get("key") and self.s.storage else None),
                source_url=doc.get("url"), s3=({"bucket": dcp.get("bucket"), "key": dcp.get("key"), "version_id": dcp.get("version_id"),
                                                "etag": dcp.get("etag")} if dcp.get("key") else None),
                page_count=facts["page_count"], parser_version=PARSER_VERSION, extractor_version=pdfmod.EXTRACTOR_VERSION,
                court_record_status=doc.get("court_record_status", "unknown"), published_at=doc.get("published_at"),
                metadata={"hearing_date": doc.get("hearing_date"), "manifest": inp.get("manifest"),
                          **{k: doc[k] for k in ("document_date", "original_filename", "archive_number") if doc.get(k)},
                          **({"source_type": doc["source_type"]} if doc.get("source_type") else {})})
            ops.set_job_source_version(conn, job_id, svid, reg["document_id"])
            if inp["source"].get("upload_id"):
                ops.set_upload_status(conn, inp["source"]["upload_id"], "consumed")
        out = {**facts, "source_version_id": svid, "created": created}
        return out, out, "succeeded"

    def stage_extract_text(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        data = self._bytes(job_id, inp)
        pages = pdfmod.extract_text_layer(data)
        empty = [p.page for p in pages if p.method == "empty"]
        out = {"pages": len(pages), "empty_pages": empty, "visual_order_fixed": sum(p.visual_order_fixed for p in pages),
               "printed_line_numbers": sum(p.printed_line_numbers for p in pages)}
        return out, {"pages": _pages_to_cp(pages)}, "succeeded"

    def stage_ocr_fallback(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        pages = _cp_to_pages((self._cp(job_id, "extract_text") or {})["pages"])
        empty = [p for p in pages if p.method == "empty"]
        if not empty:
            return {"ocr_pages": 0}, {"pages": _pages_to_cp(pages)}, "skipped"
        if not (self.cfg.ocr_enabled and pdfmod.tesseract_available(self.cfg.ocr_langs)):
            return ({"ocr_pages": 0, "warning": f"{len(empty)} pages without text layer and OCR unavailable"},
                    {"pages": _pages_to_cp(pages)}, "succeeded")
        data = self._bytes(job_id, inp)
        for i, p in enumerate(pages):
            if p.method == "empty":
                pages[i] = pdfmod.ocr_page(data, p.page, self.cfg.ocr_langs)
        return {"ocr_pages": len(empty)}, {"pages": _pages_to_cp(pages)}, "succeeded"

    def _lines(self, job_id: str) -> list[Line]:
        cp = self._cp(job_id, "lineize")
        if not cp:
            raise StageError("checkpoint_missing", "lineize checkpoint missing")
        return [ln for p in _cp_to_pages(cp["pages"]) for ln in p.lines]

    def stage_lineize(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        src = self._cp(job_id, "ocr_fallback") or self._cp(job_id, "extract_text") or {}
        pages = _cp_to_pages(src["pages"])
        pdfmod._harmonize_line_numbers(pages)
        pdfmod._tag_headers_footers(pages)
        doc = ExtractedDocument(pages=pages, page_count=len(pages))
        out = {"lines": sum(len(p.lines) for p in pages), "synthetic_lines": doc.synthetic_lines,
               "header_footer_lines": sum(1 for p in pages for ln in p.lines if ln.kind != "body")}
        with self.s.engine.begin() as conn:
            svid = (self._cp(job_id, "validate") or {})["source_version_id"]
            from .db.core import execute

            execute(conn, "UPDATE ntk.source_versions SET synthetic_lines = :s WHERE id = :id",
                    {"s": doc.synthetic_lines, "id": svid})
        return out, {"pages": _pages_to_cp(pages)}, "succeeded"

    @staticmethod
    def _is_protocol(inp: dict) -> bool:
        return inp["document"].get("source_type", "protocol") == "protocol"

    def _parse(self, job_id: str, inp: dict):
        svid = (self._cp(job_id, "validate") or {})["source_version_id"]
        if not self._is_protocol(inp):
            return svid, parse_document(self._lines(job_id), source_version_id=svid,
                                        source_type=inp["document"]["source_type"])
        parsed = parse_protocol(self._lines(job_id), source_version_id=svid, case_number_hint=self.cfg.court_case_number)
        return svid, parsed

    def _segment_document(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        """Decisions, motions, notices …: paragraph units, no hearing, no speakers or Q/A."""
        svid, parsed = self._parse(job_id, inp)
        doc = inp["document"]
        with self.s.engine.begin() as conn:
            from .pipeline import L0Result

            l0 = L0Result(svid, (self._cp(job_id, "validate") or {})["content_sha256"], 0,
                          ExtractedDocument([], 0), parsed, [], [])
            counts = sources.write_l0(conn, l0, hearing_id=None, court_record_status=doc.get("court_record_status", "unknown"))
            counts["superseded"] = sources.supersede_units(conn, svid, [u.id for u in parsed.units], parsed.parser_version)
        out = {"hearing_id": None, "source_type": doc["source_type"], "document_date": doc.get("document_date"),
               "units": len(parsed.units), "units_inserted": counts["units_inserted"],
               "units_superseded": counts["superseded"], "warnings": parsed.warnings}
        return out, {"hearing_id": None}, "succeeded"

    def stage_segment(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        if not self._is_protocol(inp):
            return self._segment_document(job_id, inp)
        svid, parsed = self._parse(job_id, inp)
        reg = self._cp(job_id, "register") or {}
        doc = inp["document"]
        hearing_date = doc.get("hearing_date") or parsed.header.hearing_date or doc.get("hearing_date_hint")
        if not hearing_date:
            raise StageError("hearing_date_unknown", "hearing date not found in document or manifest")
        warnings = list(parsed.warnings)
        if doc.get("hearing_date") and parsed.header.hearing_date and doc["hearing_date"] != parsed.header.hearing_date:
            warnings.append(f"manifest date {doc['hearing_date']} differs from protocol header {parsed.header.hearing_date}")
        expected_no = inp.get("court_case_number") or self.cfg.court_case_number
        found_no = parsed.header.court_case_number
        if expected_no and found_no and found_no != expected_no:
            msg = f"protocol caption names case {found_no}, job is for case {expected_no}"
            if self.cfg.env not in {"development", "test"}:
                raise StageError("case_number_mismatch", msg)  # a stray PDF must never enter the corpus under this case
            warnings.append(msg)
        crs = doc.get("court_record_status", "unknown")
        with self.s.engine.begin() as conn:
            hid = sources.ensure_hearing(conn, case_id=reg["case_id"], hearing_date=hearing_date, source_version_id=svid,
                                         judges=parsed.header.judges, witnesses=parsed.witnesses,
                                         metadata={"court_case_number": parsed.header.court_case_number,
                                                   "court_case_number_source": parsed.header.court_case_number_source,
                                                   "header_hearing_date": parsed.header.hearing_date,
                                                   "parser_version": parsed.parser_version,
                                                   "summary_witnesses": parsed.header.summary_witnesses})
            speaker_entities = {}
            for u in parsed.units:
                if u.speaker_label and u.speaker_label not in speaker_entities and u.speaker_role in {"judge", "witness", "prosecution", "defense", "counsel"}:
                    canonical = u.witness_label if u.speaker_role == "witness" and u.witness_label else u.speaker_label
                    speaker_entities[u.speaker_label] = sources.ensure_entity(
                        conn, entity_type="person", canonical_name=hebrew.normalize(canonical).replace("״", '"'),
                        aliases=[u.speaker_label], role_types=[u.speaker_role])
            from .pipeline import L0Result

            l0 = L0Result(svid, (self._cp(job_id, "validate") or {})["content_sha256"], 0,
                          ExtractedDocument([], 0), parsed, [], [])
            counts = sources.write_l0(conn, l0, hearing_id=hid, court_record_status=crs, speaker_entities=speaker_entities)
            counts["superseded"] = sources.supersede_units(conn, svid, [u.id for u in parsed.units], parsed.parser_version)
        out = {"hearing_id": hid, "hearing_date": hearing_date, "units": len(parsed.units),
               "units_inserted": counts["units_inserted"], "units_superseded": counts["superseded"],
               "witnesses": parsed.witnesses, "judges": parsed.header.judges,
               "warnings": warnings[:50]}
        return out, {"hearing_id": hid}, "succeeded"

    def stage_pair(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        if not self._is_protocol(inp):
            return {"note": f"no Q/A in a {inp['document']['source_type']} document"}, {}, "skipped"
        svid, parsed = self._parse(job_id, inp)
        hid = (self._cp(job_id, "segment") or {})["hearing_id"]
        exchanges, warnings = pair_exchanges(parsed.units)
        from .db.core import execute
        from .db.sources import _exchange_row

        # a re-parse keeps an exchange's id and review state when it pairs the same question and answer again
        with self.s.engine.begin() as conn:
            n = execute(conn, """
                INSERT INTO ntk.qa_exchanges (id, hearing_id, question_unit_id, answer_unit_id, phase, answer_relation,
                    interpreted_proposition, confidence, review_state, asker_label, asker_side, witness_label, public_wording,
                    flags, rule, parser_version)
                VALUES (:id, :hid, :q, :a, CAST(:phase AS ntk.examination_phase), CAST(:rel AS ntk.answer_relation), :prop,
                    :conf, 'draft', :asker, :side, :wit, :wording, :flags, :rule, :pv)
                ON CONFLICT (question_unit_id, answer_unit_id) DO UPDATE SET
                    phase = EXCLUDED.phase, answer_relation = EXCLUDED.answer_relation, confidence = EXCLUDED.confidence,
                    asker_label = EXCLUDED.asker_label, asker_side = EXCLUDED.asker_side,
                    witness_label = EXCLUDED.witness_label, public_wording = EXCLUDED.public_wording,
                    flags = EXCLUDED.flags, rule = EXCLUDED.rule, parser_version = EXCLUDED.parser_version,
                    superseded_at = NULL
            """, [_exchange_row(e, hid, parsed.parser_version) for e in exchanges])
            current_ids = [r["id"] for r in rows(conn, """
                SELECT x.id FROM ntk.qa_exchanges x
                JOIN unnest(CAST(:q AS text[]), CAST(:a AS text[])) AS p(q, a) ON p.q = x.question_unit_id AND p.a = x.answer_unit_id
            """, {"q": [e.question.id for e in exchanges], "a": [e.answer.id for e in exchanges]})]
            ex_superseded = sources.supersede_exchanges(conn, hid, current_ids)
        rel: dict[str, int] = {}
        for e in exchanges:
            rel[e.answer_relation] = rel.get(e.answer_relation, 0) + 1
        return {"exchanges": len(exchanges), "inserted": n, "superseded": ex_superseded, "relations": rel,
                "warnings": warnings[:20]}, {}, "succeeded"

    def stage_chunk(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        svid, parsed = self._parse(job_id, inp)
        hid = (self._cp(job_id, "segment") or {})["hearing_id"]
        chunks = build_chunks(parsed.units)
        with self.s.engine.begin() as conn:
            n = sources.write_chunks(conn, chunks, source_version_id=svid, hearing_id=hid,
                                     court_record_status=inp["document"].get("court_record_status", "unknown"))
            removed = sources.drop_stale_chunks(conn, svid, [c.id for c in chunks])
        return {"chunks": len(chunks), "inserted": n, "removed_stale": removed,
                "tokens": sum(c.token_count for c in chunks)}, {}, "succeeded"

    def stage_embed(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        svid = (self._cp(job_id, "validate") or {})["source_version_id"]
        model = self.s.embedder.model_id
        with self.s.engine.connect() as conn:
            todo = sources.chunks_missing_embeddings(conn, svid, model)
        done = 0
        for i in range(0, len(todo), 50):
            batch = todo[i : i + 50]
            vecs = self.s.embedder.batch([c["raw_text"] for c in batch])
            with self.s.engine.begin() as conn:
                done += sources.set_embeddings(conn, list(zip([c["id"] for c in batch], vecs)), model)
        return {"embedded": done, "model": model}, {}, "succeeded"

    def _unit_views(self, conn, unit_rows: list[dict]) -> list[UnitView]:
        return list(units_by_ids(conn, [r["id"] for r in unit_rows], published_only=False).values())

    def stage_extract_a(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        svid = (self._cp(job_id, "validate") or {})["source_version_id"]
        hid = (self._cp(job_id, "segment") or {})["hearing_id"]
        if hid is None:
            return {"note": "hearing digests are built for protocols only"}, {}, "skipped"
        out, cp = self.build_hearing_digest(hid, svid)
        return out, cp, "succeeded"

    def rebuild_hearing_digest(self, hearing_id: str) -> dict:
        """Rebuild Layer A for a hearing outside a job (sources or judicial statements changed)."""
        with self.s.engine.connect() as conn:
            svid = scalar(conn, "SELECT source_version_id FROM ntk.hearings WHERE id = :h", {"h": hearing_id})
        if svid is None:
            raise StageError("hearing_not_found", f"hearing {hearing_id} not found")
        return self.build_hearing_digest(hearing_id, svid)[0]

    def build_hearing_digest(self, hid: str, svid: str) -> tuple[dict, dict]:
        with self.s.engine.connect() as conn:
            unit_rows = sources.units_for_version(conn, svid)
            views = units_by_ids(conn, [r["id"] for r in unit_rows], published_only=False)
            units = [views[r["id"]] for r in unit_rows if r["id"] in views]
            ex_rows = rows(conn, """SELECT id, question_unit_id, answer_unit_id, answer_relation::text AS rel, confidence,
                                           interpreted_proposition, review_state::text AS st
                                    FROM ntk.qa_exchanges WHERE hearing_id = :h AND superseded_at IS NULL""", {"h": hid})
            cv = ops.current_corpus_version(conn)
        exchanges = [ExchangeView(r["id"], r["question_unit_id"], r["answer_unit_id"], r["rel"], float(r["confidence"]),
                                  r["interpreted_proposition"], r["st"] in {"machine_verified", "approved", "published"}) for r in ex_rows]
        res = build_hearing_digest(hearing_id=hid, units=units, exchanges=exchanges, runner=self.s.runner,
                                   corpus_version=cv, citation_base=self.cfg.citation_base, env=self.cfg.env)
        if res.payload is None:
            # a failed generation is an operational fact (job output + audit), not something a reviewer can approve
            with self.s.engine.begin() as conn:
                ops.audit(conn, actor="pipeline", action="hearing_digest.failed", object_type="hearing", object_id=hid,
                          details={"errors": res.errors[:10]})
            return {"digest": None, "errors": res.errors[:10], "attempts": len(res.runs)}, {}
        with self.s.engine.begin() as conn:
            kdb.save_layer_a(conn, object_type="hearing", object_key=hid, version_id=res.payload["id"], payload=res.payload,
                             source_unit_ids=[c["source_unit_id"] for c in res.payload["citations"]],
                             model_run_id=next(r.id for r in reversed(res.runs) if r.task_type == "digest"),
                             review_state=res.decision.state)  # type: ignore[union-attr]
            art_id = str(ids.derived_uuid("summary_artifact", res.payload["id"]))
            kdb.save_artifact(conn, artifact_id=art_id, artifact_type="summary", object_type="hearing", object_id=hid,
                              payload=res.payload, decision=res.decision,  # type: ignore[arg-type]
                              model_run_id=next(r.id for r in reversed(res.runs) if r.task_type == "digest"),
                              verifier_run_id=next((r.id for r in reversed(res.runs) if r.task_type == "verify"), None))
        published = self.auto_publish(art_id, res.decision)  # type: ignore[arg-type]
        return {"digest_id": res.payload["id"], "artifact_id": art_id, "state": res.decision.state,  # type: ignore[union-attr]
                "risk_flags": res.decision.risk_flags, "attempts": len(res.runs),  # type: ignore[union-attr]
                "auto_published": published}, {"artifact_id": art_id}

    def auto_publish(self, artifact_id: str, decision) -> bool:
        """Operator policy NTK_AUTO_PUBLISH=gates: an artifact that passed every automatic gate with no risk flag is
        approved and published by the policy (audited as such). Anything doubtful stays in the review queue."""
        if self.cfg.auto_publish != "gates" or decision is None or decision.state != "machine_verified":
            return False
        try:
            with self.s.engine.begin() as conn:
                kdb.review_artifact(conn, artifact_id=artifact_id, decision="approve", reviewer="policy:auto-publish-gates",
                                    notes="passed all automatic gates with no risk flags")
                kdb.publish_artifact(conn, artifact_id=artifact_id, actor="policy:auto-publish-gates", env=self.cfg.env,
                                     public_base_url=self.cfg.public_base_url, include_sources=False)
            return True
        except kdb.PublicationError as exc:
            log.info("auto-publish of %s skipped: %s", artifact_id, exc)
            return False

    def stage_map_b(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        claim_ids = inp.get("claim_ids") or []
        if not claim_ids:
            return {"claims": 0, "note": "no claims requested for this job"}, {}, "skipped"
        out = []
        for cid in claim_ids:
            out.append(self.build_claim(cid))
        return {"claims": out}, {}, "succeeded"

    def build_claim(self, claim_id: str, *, extra_queries: list[str] | None = None, limit: int = 40) -> dict:
        with self.s.engine.connect() as conn:
            c = kdb.get_claim(conn, claim_id)
            cv = ops.current_corpus_version(conn)
        if c is None:
            raise StageError("claim_not_found", f"claim {claim_id} not found")
        backend = self.s.search_backend()
        cand_ids: list[str] = []
        for q in [c["canonical_question"], c["claim_text"], *(extra_queries or [])]:
            resp = backend.search(SearchRequest(q, SearchFilters(published_only=False), limit=limit))
            for h in resp.hits:
                if h.source_unit_id not in cand_ids:
                    cand_ids.append(h.source_unit_id)
        with self.s.engine.connect() as conn:
            # add the paired unit of every candidate exchange so Q/A are seen together
            pairs = rows(conn, """SELECT id, question_unit_id, answer_unit_id, answer_relation::text AS rel, confidence,
                                         interpreted_proposition, review_state::text AS st
                                  FROM ntk.qa_exchanges WHERE (question_unit_id = ANY(:ids) OR answer_unit_id = ANY(:ids))
                                  AND superseded_at IS NULL""",
                           {"ids": cand_ids})
            for p in pairs:
                for x in (p["question_unit_id"], p["answer_unit_id"]):
                    if x not in cand_ids:
                        cand_ids.append(x)
            views = units_by_ids(conn, cand_ids, published_only=False)
        exchanges_by_unit = {}
        for p in pairs:
            ev = ExchangeView(p["id"], p["question_unit_id"], p["answer_unit_id"], p["rel"], float(p["confidence"]),
                              p["interpreted_proposition"], p["st"] in {"machine_verified", "approved", "published"})
            exchanges_by_unit[p["question_unit_id"]] = ev
            exchanges_by_unit[p["answer_unit_id"]] = ev
        claim = ClaimView(id=str(c["id"]), version_id=str(c["version_id"]), question=c["canonical_question"],
                          claim_text=c["claim_text"], claim_type=c["claim_type"], sensitivity=list(c["sensitivity"] or []),
                          disclosure=c["disclosure"])
        # captions (headers, witness introductions) are never evidence
        candidates = [views[x] for x in cand_ids if x in views and views[x].unit_type != "caption"]
        res = build_claim_bundle(claim=claim, candidates=candidates,
                                 exchanges_by_unit=exchanges_by_unit, runner=self.s.runner, corpus_version=cv,
                                 citation_base=self.cfg.citation_base, env=self.cfg.env,
                                 independent_verifier=not self.s.registry.single_family)
        if res.payload is None:
            with self.s.engine.begin() as conn:
                ops.audit(conn, actor="pipeline", action="claim_build.failed", object_type="claim", object_id=claim.id,
                          details={"errors": res.errors[:10]})
            return {"claim_id": claim.id, "state": "failed", "errors": res.errors[:10]}
        map_run = res.runs[0]
        verify_run = next((r for r in res.runs if r.task_type == "verify"), None)
        with self.s.engine.begin() as conn:
            kdb.save_artifact(conn, artifact_id=res.artifact_id, artifact_type="claim_card", object_type="claim",  # type: ignore[arg-type]
                              object_id=claim.id, payload=res.payload, decision=res.decision,  # type: ignore[arg-type]
                              model_run_id=map_run.id, verifier_run_id=verify_run.id if verify_run else None)
            kdb.save_evidence_from_bundle(conn, case_id=c["case_id"], claim_id=claim.id, bundle=res.payload,
                                          review_state="draft", model_run_id=map_run.id)
            jrun = next((r for r in res.runs if r.task_type == "judicial"), None)
            if jrun and jrun.ok:
                for cl in jrun.output["classifications"]:
                    if cl["is_judicial"] and cl.get("level"):
                        kdb.save_judicial_statement(conn, source_unit_id=cl["source_unit_id"], level=cl["level"],
                                                    summary=cl.get("summary") or "", confidence=cl["confidence"],
                                                    related_claim_ids=[claim.id], model_run_id=jrun.id, statement_date=None)
        published = self.auto_publish(res.artifact_id, res.decision)  # type: ignore[arg-type]
        return {"claim_id": claim.id, "artifact_id": res.artifact_id, "state": res.decision.state,  # type: ignore[union-attr]
                "support": len(res.payload["support"]), "weakness": len(res.payload["weakness"]),
                "risk_flags": res.decision.risk_flags, "auto_published": published}  # type: ignore[union-attr]

    def stage_verify(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        """Verify Q/A 'affirms'/'denies' exchanges so public wording may be used.

        With a single model family, exchanges stay 'human_review_required'
        (spec §23.5).

        Exchanges still awaiting human review whose last check came from the
        mock provider (or from no model at all) are checked again, so a re-run
        after switching to a real model replaces the placeholder verdict.
        Exchanges a person already reviewed are never touched."""
        hid = (self._cp(job_id, "segment") or {})["hearing_id"]
        if hid is None:
            return {"note": "no Q/A exchanges outside protocols"}, {}, "skipped"
        with self.s.engine.connect() as conn:
            exs = rows(conn, """
                SELECT x.id, x.question_unit_id, x.answer_unit_id, x.answer_relation::text AS rel, x.public_wording,
                       q.raw_text AS qtext, a.raw_text AS atext
                FROM ntk.qa_exchanges x JOIN ntk.source_units q ON q.id = x.question_unit_id
                JOIN ntk.source_units a ON a.id = x.answer_unit_id
                LEFT JOIN ntk.model_runs mr ON mr.id = x.relation_model_run_id
                WHERE x.hearing_id = :h AND x.public_wording IS NOT NULL AND x.superseded_at IS NULL
                  AND (x.review_state = 'draft'
                       OR (x.review_state = 'human_review_required' AND :real
                           AND (x.relation_model_run_id IS NULL OR mr.provider = 'mock' OR :auto)))
                ORDER BY x.id
            """, {"h": hid, "real": self.s.registry.get("verifier").provider != "mock",
                  "auto": self.cfg.auto_publish == "gates"})
            cv = ops.current_corpus_version(conn)
        if not exs:
            return {"verified": 0, "checked": 0, "verifier_model": self.s.registry.get("verifier").model_id}, {}, "succeeded"
        independent = not self.s.registry.single_family
        # with NTK_AUTO_PUBLISH=gates the operator accepts a same-family verifier's agreement for this low-stakes label
        trust_agreement = independent or self.cfg.auto_publish == "gates"
        checked = passed = failed_batches = 0
        pairs: dict[str, int] = {}
        for i in range(0, len(exs), 25):
            batch = exs[i : i + 25]
            run = self.s.runner.run("qa_relation", {"exchanges": [{"id": e["id"], "question": e["qtext"][:1500],
                                                                    "answer": e["atext"][:1500]} for e in batch]},
                                    input_source_ids=[x for e in batch for x in (e["question_unit_id"], e["answer_unit_id"])],
                                    corpus_version=cv, role="verifier")
            if not run.ok:
                failed_batches += 1
                continue
            verdicts = {it["exchange_id"]: it for it in run.output["items"]}
            with self.s.engine.begin() as conn:
                for e in batch:
                    checked += 1
                    v = verdicts.get(e["id"])
                    agree = v is not None and v["answer_relation"] == e["rel"] and v["confidence"] >= 0.7
                    state = "machine_verified" if (agree and trust_agreement) else "human_review_required"
                    if agree:
                        passed += 1
                    key = f"{e['rel']}->{v['answer_relation'] if v else 'missing'}"
                    pairs[key] = pairs.get(key, 0) + 1
                    from .db.core import execute

                    execute(conn, """UPDATE ntk.qa_exchanges SET review_state = CAST(:s AS ntk.review_state),
                                     relation_model_run_id = CAST(:r AS uuid) WHERE id = :id""",
                            {"s": state, "r": run.id, "id": e["id"]})
                    # no per-exchange review task: the "affirmed/denied" label is shown only when machine_verified,
                    # and a person is never asked to approve protocol lines one by one
        return {"checked": checked, "verifier_agrees": passed, "independent_family": independent,
                "label_policy": "agreement" if trust_agreement else "human",
                "failed_batches": failed_batches, "relation_pairs": dict(sorted(pairs.items())),
                "verifier_model": self.s.registry.get("verifier").model_id}, {}, "succeeded"

    def stage_review(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        with self.s.engine.connect() as conn:
            open_tasks = rows(conn, "SELECT object_type, count(*) AS n FROM ntk.review_tasks WHERE status='open' GROUP BY 1")
        return {"open_review_tasks": {r["object_type"]: r["n"] for r in open_tasks}}, {}, "succeeded"

    def stage_publish(self, job_id: str, inp: dict) -> tuple[dict, dict, str]:
        """AI layers are never published here. The *source* itself may be, when the operator's intake policy says so
        (``auto_publish_source``: protocols, decisions, motions, responses and notices whose own pages carry
        this case's number)."""
        if not inp.get("auto_publish_source"):
            return {"note": "publication requires an approved review and an explicit publish action"}, {}, "skipped"
        svid = (self._cp(job_id, "validate") or {})["source_version_id"]
        hid = (self._cp(job_id, "segment") or {}).get("hearing_id")
        verified = bool(inp.get("case_number_verified"))
        if hid is not None:
            with self.s.engine.connect() as conn:
                meta = scalar(conn, "SELECT metadata FROM ntk.hearings WHERE id = :h", {"h": hid}) or {}
            verified = verified and meta.get("court_case_number") == self.cfg.court_case_number \
                and meta.get("court_case_number_source") == "document"
        if not verified:
            return {"note": "case number not verified on the document; source left unpublished"}, {}, "skipped"
        with self.s.engine.begin() as conn:
            cv = kdb.publish_source_version(conn, svid, actor="inbox:auto-publish")
        # the digest was built (extract_a) before its source was public; publish it now if it passed every gate
        digest_published = self.auto_publish_latest(object_type="hearing", object_id=hid) if hid else False
        return {"source_version_id": svid, "published": True, "corpus_version": cv,
                "digest_auto_published": digest_published}, {}, "succeeded"

    def auto_publish_latest(self, *, object_type: str, object_id: str) -> bool:
        with self.s.engine.connect() as conn:
            art = row(conn, """SELECT id::text AS id, review_state::text AS st, risk_flags FROM ntk.generated_artifacts
                               WHERE object_type = :ot AND object_id = :oid ORDER BY created_at DESC LIMIT 1""",
                      {"ot": object_type, "oid": object_id})
        if not art or art["st"] != "machine_verified" or art["risk_flags"]:
            return False

        class _Decision:  # the stored gate outcome: passed every gate, no risk flag
            state = "machine_verified"

        return self.auto_publish(art["id"], _Decision())


def doc_input_from_manifest(manifest: dict, doc: dict) -> dict:
    """Build an ingestion job input from a manifest entry."""
    source: dict[str, Any] = {}
    for k in ("upload_id", "s3_key", "url", "local_path", "expected_sha256"):
        if doc.get(k):
            source[k] = doc[k]
    if doc.get("s3_uri"):
        source["s3_key"] = urlparse(doc["s3_uri"]).path.lstrip("/")
    if not source.get("s3_key") and not source.get("local_path") and not source.get("upload_id") and doc.get("url"):
        source["url"] = doc["url"]
    title = doc.get("title") or f"פרוטוקול דיון {doc.get('hearing_date', '')} ת״פ {manifest.get('court_case_number', '67104-01-20')}"
    return {
        "case_id": manifest.get("case_id"),
        "manifest": manifest.get("name"),
        "document": {
            "title": title,
            "url": doc.get("url"),
            "canonical_key": doc.get("url") or doc.get("canonical_key") or title,
            "hearing_date": doc.get("hearing_date"),
            "source_type": doc.get("source_type", "protocol"),
            "authority_tier": manifest.get("authority_tier", 1),
            "source_owner": manifest.get("source_owner", "הרשות השופטת"),
            "court_record_status": doc.get("court_record_status", manifest.get("court_record_status", "unknown")),
        },
        "source": source,
        "claim_ids": doc.get("claim_ids", []),
    }


def job_idempotency_key(job_input: dict, *, parser_version: str = PARSER_VERSION) -> str:
    src = job_input["source"]
    ident = src.get("expected_sha256") or src.get("upload_id") or src.get("s3_key") or src.get("url") or src.get("local_path")
    return ids.sha256_json({"doc": job_input["document"].get("canonical_key"), "src": ident, "parser": parser_version})


_ = (row, Any)
