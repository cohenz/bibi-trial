"""Runtime validation of layer contracts (spec §26).

Every hand-off between layers (L0 → A → B → C) and every model output is
validated here before anything is persisted. Invalid payloads raise
``ContractError`` with a structured list of errors; callers persist the
failure (model_runs.validation_errors / review task) and never store the
payload as a valid object.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import jsonschema
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SCHEMA_FILENAME = "ntk-contracts-2.0.json"
SUPPORTED_MAJOR = "2"


def _contracts_path() -> Path:
    env = os.environ.get("NTK_CONTRACTS_DIR")
    candidates = [Path(env)] if env else []
    here = Path(__file__).resolve()
    candidates += [here.parent / "_contracts", *[p / "contracts" for p in here.parents]]
    for c in candidates:
        if (c / SCHEMA_FILENAME).exists():
            return c / SCHEMA_FILENAME
    raise FileNotFoundError(f"{SCHEMA_FILENAME} not found (set NTK_CONTRACTS_DIR)")


_format_checker = FormatChecker()


@_format_checker.checks("date-time", raises=ValueError)
def _is_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if not re.match(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$", value):
        raise ValueError("not an RFC 3339 date-time")
    _dt.datetime.fromisoformat(value.replace("z", "+00:00").replace("Z", "+00:00"))
    return True


@_format_checker.checks("date", raises=ValueError)
def _is_date(value: object) -> bool:
    if not isinstance(value, str):
        return True
    _dt.date.fromisoformat(value)
    return len(value) == 10


@_format_checker.checks("uuid", raises=ValueError)
def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return True
    uuid.UUID(value)
    return True


@_format_checker.checks("uri", raises=ValueError)
def _is_uri(value: object) -> bool:
    if not isinstance(value, str):
        return True
    p = urlparse(value)
    if not p.scheme or not (p.netloc or p.scheme in {"urn", "s3", "file"}):
        raise ValueError("not an absolute URI")
    return True


@dataclass
class ContractError(Exception):
    contract: str
    errors: list[dict[str, Any]] = field(default_factory=list)

    def __str__(self) -> str:  # pragma: no cover - repr helper
        first = self.errors[0]["message"] if self.errors else ""
        return f"{self.contract}: {len(self.errors)} contract error(s): {first}"

    def to_dict(self) -> dict[str, Any]:
        return {"contract": self.contract, "errors": self.errors}


@lru_cache(maxsize=1)
def _document() -> dict[str, Any]:
    return json.loads(_contracts_path().read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _registry() -> Registry:
    doc = _document()
    return Registry().with_resource(doc["$id"], Resource.from_contents(doc))


@lru_cache(maxsize=64)
def _validator(name: str) -> Draft202012Validator:
    doc = _document()
    if name not in doc["$defs"]:
        raise KeyError(f"unknown contract {name!r}")
    schema = {"$schema": doc["$schema"], "$ref": f"{doc['$id']}#/$defs/{name}"}
    return Draft202012Validator(schema, registry=_registry(), format_checker=_format_checker)


def contract_names() -> list[str]:
    return sorted(_document()["$defs"].keys())


def json_schema_for(name: str) -> dict[str, Any]:
    return _document()["$defs"][name]


def errors_for(name: str, payload: Any) -> list[dict[str, Any]]:
    out = []
    for err in sorted(_validator(name).iter_errors(payload), key=lambda e: list(e.absolute_path)):
        out.append(
            {
                "path": "/" + "/".join(str(p) for p in err.absolute_path),
                "message": err.message[:500],
                "validator": err.validator,
            }
        )
    return out


def validate(name: str, payload: Any) -> Any:
    """Validate ``payload`` against contract ``name``; return it unchanged.

    Also rejects unknown major schema versions (spec §26)."""
    if isinstance(payload, dict) and "schema_version" in payload:
        sv = str(payload["schema_version"])
        if sv.split(".")[0] != SUPPORTED_MAJOR:
            raise ContractError(name, [{"path": "/schema_version", "message": f"unsupported schema version {sv}", "validator": "unsupported_schema"}])
    errs = errors_for(name, payload)
    if errs:
        raise ContractError(name, errs)
    return payload


def is_valid(name: str, payload: Any) -> bool:
    try:
        validate(name, payload)
        return True
    except ContractError:
        return False


__all__ = ["ContractError", "validate", "is_valid", "errors_for", "contract_names", "json_schema_for", "jsonschema"]
