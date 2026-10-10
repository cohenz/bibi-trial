"""Runtime configuration from environment variables (see .env.example).

Secrets are read from the environment only and are never logged: ``Settings``
redacts them in ``repr`` and ``safe_dict``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache

SECRET_FIELDS = {
    "database_url", "redis_url", "s3_secret_access_key", "gemini_api_key", "verifier_api_key",
    "wp_callback_secret", "service_keys_json", "ip_hash_salt", "embedding_api_key",
}


def _bool(v: str | None, default: bool = False) -> bool:
    if v is None or v == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _int(v: str | None, default: int) -> int:
    try:
        return int(v) if v not in (None, "") else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    env: str = "development"
    database_url: str = "postgresql+psycopg://ntk:ntk@localhost:5432/ntk"
    redis_url: str = "redis://localhost:6379/0"
    public_base_url: str = "http://localhost:8000"
    citation_permalink_base: str = ""  # defaults to public_base_url + /v2/citations/
    answer_permalink_base: str = ""  # defaults to public_base_url + /v2/answers/
    case_id: str = "il-jdc-jerusalem-67104-01-20"
    court_case_number: str = "67104-01-20"

    # storage
    storage_backend: str = "s3"  # s3 | local
    local_storage_dir: str = "./var/storage"
    s3_bucket: str = ""
    s3_region: str = "auto"  # Cloudflare R2 uses "auto"
    s3_addressing_style: str = "path"
    s3_versioning: bool = False  # R2 has no object versioning (ADR-0011)
    s3_endpoint_url: str = ""  # MinIO / LocalStack in development
    s3_public_endpoint_url: str = ""  # endpoint the browser uses for presigned URLs
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_prefix: str = "sources/"
    presign_ttl_seconds: int = 900
    max_upload_bytes: int = 200 * 1024 * 1024

    # models (no model names are hard-coded: ADR-0007)
    model_provider: str = "mock"  # mock | gemini
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    model_extractor: str = ""
    model_mapper: str = ""
    model_judicial_classifier: str = ""
    model_writer: str = ""
    model_qa_relation: str = ""
    model_verifier: str = ""
    verifier_provider: str = ""  # empty → same as model_provider (single family → human review)
    verifier_api_key: str = ""
    verifier_base_url: str = ""
    embedding_provider: str = "mock"
    embedding_model: str = ""
    embedding_api_key: str = ""
    embedding_dim: int = 3072
    model_temperature: float = 0.0
    model_timeout_seconds: int = 120
    model_max_retries: int = 3

    # auth / security
    service_keys_json: str = "{}"  # {"key_id": {"secret": "...", "scopes": [...]}}
    signature_max_skew_seconds: int = 300
    cors_origins: str = ""
    ip_hash_salt: str = ""
    rate_limit_ask_per_minute: int = 6
    rate_limit_search_per_minute: int = 30
    rate_limit_public_per_minute: int = 120
    max_question_chars: int = 500
    max_body_bytes: int = 64 * 1024

    # WordPress callbacks
    wp_callback_url: str = ""
    wp_callback_secret: str = ""

    # pipeline
    ocr_enabled: bool = True
    ocr_langs: str = "heb+eng"
    fetch_allowlist: tuple[str, ...] = ("www.gov.il", "gov.il", "supremedecisions.court.gov.il", "the315.org", "www.the315.org")
    log_level: str = "INFO"
    extra: dict = field(default_factory=dict)

    def __repr__(self) -> str:  # never print secrets
        return f"Settings({self.safe_dict()})"

    def safe_dict(self) -> dict:
        out = {}
        for k in self.__dataclass_fields__:
            v = getattr(self, k)
            out[k] = ("***" if v else "") if k in SECRET_FIELDS else v
        return out

    @property
    def service_keys(self) -> dict:
        try:
            data = json.loads(self.service_keys_json or "{}")
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    @property
    def citation_base(self) -> str:
        return (self.citation_permalink_base or f"{self.public_base_url.rstrip('/')}/v2/citations/").rstrip("/") + "/"

    @property
    def answer_base(self) -> str:
        return (self.answer_permalink_base or f"{self.public_base_url.rstrip('/')}/v2/answers/").rstrip("/") + "/"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def verifier_is_independent_family(self) -> bool:
        vp = (self.verifier_provider or self.model_provider).lower()
        return vp != self.model_provider.lower() and vp not in {"", "mock"}


def load_settings(env: dict[str, str] | None = None) -> Settings:
    e = env if env is not None else os.environ
    g = lambda k, d="": e.get(k, d)  # noqa: E731
    allow = tuple(x.strip() for x in g("NTK_FETCH_ALLOWLIST", "").split(",") if x.strip())
    kwargs = dict(
        env=g("NTK_ENV", "development"),
        database_url=g("DATABASE_URL", Settings.database_url),
        redis_url=g("REDIS_URL", Settings.redis_url),
        public_base_url=g("NTK_PUBLIC_BASE_URL", Settings.public_base_url),
        citation_permalink_base=g("NTK_CITATION_PERMALINK_BASE"),
        answer_permalink_base=g("NTK_ANSWER_PERMALINK_BASE"),
        case_id=g("NTK_CASE_ID", Settings.case_id),
        court_case_number=g("NTK_COURT_CASE_NUMBER", Settings.court_case_number),
        storage_backend=g("NTK_STORAGE_BACKEND", "s3"),
        local_storage_dir=g("NTK_LOCAL_STORAGE_DIR", Settings.local_storage_dir),
        s3_bucket=g("S3_BUCKET"),
        s3_region=g("S3_REGION", Settings.s3_region),
        s3_addressing_style=g("S3_ADDRESSING_STYLE", "path"),
        s3_versioning=_bool(g("S3_VERSIONING"), False),
        s3_endpoint_url=g("S3_ENDPOINT_URL"),
        s3_public_endpoint_url=g("S3_PUBLIC_ENDPOINT_URL"),
        s3_access_key_id=g("S3_ACCESS_KEY_ID") or g("AWS_ACCESS_KEY_ID"),
        s3_secret_access_key=g("S3_SECRET_ACCESS_KEY") or g("AWS_SECRET_ACCESS_KEY"),
        s3_prefix=g("S3_PREFIX", "sources/"),
        presign_ttl_seconds=_int(g("S3_PRESIGN_TTL_SECONDS"), 900),
        max_upload_bytes=_int(g("NTK_MAX_UPLOAD_BYTES"), Settings.max_upload_bytes),
        model_provider=g("NTK_MODEL_PROVIDER", "mock"),
        gemini_api_key=g("GEMINI_API_KEY"),
        gemini_base_url=g("GEMINI_BASE_URL", Settings.gemini_base_url),
        model_extractor=g("NTK_MODEL_EXTRACTOR"),
        model_mapper=g("NTK_MODEL_MAPPER"),
        model_judicial_classifier=g("NTK_MODEL_JUDICIAL_CLASSIFIER"),
        model_writer=g("NTK_MODEL_WRITER"),
        model_qa_relation=g("NTK_MODEL_QA_RELATION"),
        model_verifier=g("NTK_MODEL_VERIFIER"),
        verifier_provider=g("NTK_VERIFIER_PROVIDER"),
        verifier_api_key=g("NTK_VERIFIER_API_KEY"),
        verifier_base_url=g("NTK_VERIFIER_BASE_URL"),
        embedding_provider=g("NTK_EMBEDDING_PROVIDER", "mock"),
        embedding_model=g("NTK_EMBEDDING_MODEL"),
        embedding_api_key=g("NTK_EMBEDDING_API_KEY") or g("GEMINI_API_KEY"),
        embedding_dim=_int(g("NTK_EMBEDDING_DIM"), 3072),
        model_temperature=float(g("NTK_MODEL_TEMPERATURE", "0") or 0),
        model_timeout_seconds=_int(g("NTK_MODEL_TIMEOUT_SECONDS"), 120),
        model_max_retries=_int(g("NTK_MODEL_MAX_RETRIES"), 3),
        service_keys_json=g("NTK_SERVICE_KEYS", "{}"),
        signature_max_skew_seconds=_int(g("NTK_SIGNATURE_MAX_SKEW_SECONDS"), 300),
        cors_origins=g("NTK_CORS_ORIGINS"),
        ip_hash_salt=g("NTK_IP_HASH_SALT"),
        rate_limit_ask_per_minute=_int(g("NTK_RATE_LIMIT_ASK_PER_MINUTE"), 6),
        rate_limit_search_per_minute=_int(g("NTK_RATE_LIMIT_SEARCH_PER_MINUTE"), 30),
        rate_limit_public_per_minute=_int(g("NTK_RATE_LIMIT_PUBLIC_PER_MINUTE"), 120),
        max_question_chars=_int(g("NTK_MAX_QUESTION_CHARS"), 500),
        max_body_bytes=_int(g("NTK_MAX_BODY_BYTES"), 64 * 1024),
        wp_callback_url=g("WP_CALLBACK_URL"),
        wp_callback_secret=g("WP_CALLBACK_SECRET"),
        ocr_enabled=_bool(g("NTK_OCR_ENABLED"), True),
        ocr_langs=g("NTK_OCR_LANGS", "heb+eng"),
        log_level=g("NTK_LOG_LEVEL", "INFO"),
    )
    if allow:
        kwargs["fetch_allowlist"] = allow
    return Settings(**kwargs)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
