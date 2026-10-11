"""Object storage for source files (S3 API: Cloudflare R2, AWS S3, MinIO).

Design (ADR-0011):
* the bucket is private; browsers upload with short-lived presigned PUT URLs
  and never see credentials;
* objects are content-addressed: ``<prefix>sha256/<aa>/<sha256>.pdf``. A key
  can only ever hold one content, so no object is overwritten even on R2,
  which has no object versioning;
* the worker re-computes SHA-256 after download; ETag is stored for operations
  only and is never treated as a content hash;
* the public citation link goes through the Knowledge API, never to the object.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import Settings

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class ObjectInfo:
    bucket: str
    key: str
    size: int
    etag: str | None
    version_id: str | None
    content_type: str | None


@dataclass
class ListedObject:
    key: str
    size: int
    etag: str
    last_modified: str | None


@dataclass
class PresignedUpload:
    url: str
    method: str
    headers: dict[str, str]
    bucket: str
    key: str
    expires_in: int
    already_exists: bool = False


class StorageError(RuntimeError):
    pass


class Storage(Protocol):
    bucket: str

    def content_key(self, sha256: str, ext: str = "pdf") -> str: ...
    def presign_put(self, key: str, *, mime_type: str, size: int, sha256: str, ttl: int) -> PresignedUpload: ...
    def head(self, key: str) -> ObjectInfo | None: ...
    def get_bytes(self, key: str, *, max_bytes: int) -> bytes: ...
    def put_bytes(self, key: str, data: bytes, *, mime_type: str) -> ObjectInfo: ...
    def uri(self, key: str) -> str: ...
    def list(self, prefix: str) -> list[ListedObject]: ...
    def presign_get(self, key: str, *, ttl: int, filename: str | None = None) -> str: ...
    def delete_intake_copy(self, key: str, *, prefix: str, expected_etag: str | None) -> bool: ...


def _check_deletable(key: str, prefix: str) -> None:
    """Only intake copies may be deleted: keys under the inbox prefix, never the immutable sources/ area."""
    if not prefix or not prefix.endswith("/") or prefix.startswith("sources") or not key.startswith(prefix) \
            or ".." in key.split("/"):
        raise StorageError(f"refusing to delete {key!r}: not under the intake prefix {prefix!r}")


def content_key(prefix: str, sha256: str, ext: str = "pdf") -> str:
    sha = sha256.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("sha256 must be 64 hex characters")
    ext = _SAFE.sub("", ext)[:8] or "bin"
    return f"{prefix.rstrip('/')}/sha256/{sha[:2]}/{sha}.{ext}".lstrip("/")


class S3Storage:
    def __init__(self, settings: Settings, client=None, presign_client=None):
        if not settings.s3_bucket:
            raise StorageError("S3_BUCKET is not configured")
        self.settings = settings
        self.bucket = settings.s3_bucket
        self._client = client or self._make_client(settings.s3_endpoint_url)
        public_ep = settings.s3_public_endpoint_url or settings.s3_endpoint_url
        self._presign_client = presign_client or (
            self._client if public_ep == settings.s3_endpoint_url else self._make_client(public_ep)
        )

    def _make_client(self, endpoint: str | None):
        import boto3
        from botocore.config import Config

        return boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            region_name=self.settings.s3_region or "auto",
            aws_access_key_id=self.settings.s3_access_key_id or None,
            aws_secret_access_key=self.settings.s3_secret_access_key or None,
            config=Config(signature_version="s3v4", s3={"addressing_style": self.settings.s3_addressing_style},
                          retries={"max_attempts": 4, "mode": "standard"}),
        )

    def content_key(self, sha256: str, ext: str = "pdf") -> str:
        return content_key(self.settings.s3_prefix, sha256, ext)

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def head(self, key: str) -> ObjectInfo | None:
        from botocore.exceptions import ClientError

        try:
            r = self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise StorageError(f"head_object failed: {code}") from exc
        return ObjectInfo(self.bucket, key, int(r.get("ContentLength", 0)), (r.get("ETag") or "").strip('"') or None,
                          r.get("VersionId"), r.get("ContentType"))

    def presign_put(self, key: str, *, mime_type: str, size: int, sha256: str, ttl: int) -> PresignedUpload:
        existing = self.head(key)
        if existing is not None and existing.size == size:
            return PresignedUpload("", "NONE", {}, self.bucket, key, 0, already_exists=True)
        params = {"Bucket": self.bucket, "Key": key, "ContentType": mime_type, "ContentLength": size}
        headers = {"Content-Type": mime_type}
        if self.settings.extra.get("presign_checksum"):
            b64 = base64.b64encode(bytes.fromhex(sha256)).decode()
            params["ChecksumSHA256"] = b64
            headers["x-amz-checksum-sha256"] = b64
        url = self._presign_client.generate_presigned_url("put_object", Params=params, ExpiresIn=ttl, HttpMethod="PUT")
        return PresignedUpload(url, "PUT", headers, self.bucket, key, ttl)

    def get_bytes(self, key: str, *, max_bytes: int) -> bytes:
        info = self.head(key)
        if info is None:
            raise StorageError(f"object not found: {key}")
        if info.size > max_bytes:
            raise StorageError(f"object too large: {info.size} > {max_bytes}")
        r = self._client.get_object(Bucket=self.bucket, Key=key)
        data = r["Body"].read(max_bytes + 1)
        if len(data) > max_bytes:
            raise StorageError("object exceeded size limit while reading")
        return data

    def put_bytes(self, key: str, data: bytes, *, mime_type: str) -> ObjectInfo:
        if self.head(key) is None:
            self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=mime_type)
        info = self.head(key)
        assert info is not None
        return info

    def presign_get(self, key: str, *, ttl: int, filename: str | None = None) -> str:
        from urllib.parse import quote

        params = {"Bucket": self.bucket, "Key": key, "ResponseContentType": "application/pdf"}
        if filename:
            params["ResponseContentDisposition"] = f"inline; filename*=UTF-8''{quote(filename)}"
        return self._presign_client.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl, HttpMethod="GET")

    def list(self, prefix: str) -> list[ListedObject]:
        out: list[ListedObject] = []
        for page in self._client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            for o in page.get("Contents", []) or []:
                if o["Key"].endswith("/"):
                    continue  # folder placeholder created by the dashboard
                lm = o.get("LastModified")
                out.append(ListedObject(o["Key"], int(o.get("Size", 0)), (o.get("ETag") or "").strip('"'),
                                        lm.isoformat() if lm is not None else None))
        return out


    def _etag(self, key: str) -> str | None:
        try:
            r = self._client.head_object(Bucket=self.bucket, Key=key)
        except Exception:  # noqa: BLE001 - missing object
            return None
        return (r.get("ETag") or "").strip('"')

    def delete_intake_copy(self, key: str, *, prefix: str, expected_etag: str | None) -> bool:
        """Delete one intake object. Returns False if it is already gone; refuses if it changed since it was scanned."""
        _check_deletable(key, prefix)
        etag = self._etag(key)
        if etag is None:
            return False
        if expected_etag and etag != expected_etag:
            raise StorageError(f"{key} changed since it was scanned (etag {etag} != {expected_etag}); not deleted")
        self._client.delete_object(Bucket=self.bucket, Key=key)
        return True


class LocalStorage:
    """Filesystem storage for tests and offline development (no presign)."""

    def __init__(self, root: str, bucket: str = "local"):
        self.root = Path(root)
        self.bucket = bucket
        self.root.mkdir(parents=True, exist_ok=True)

    def content_key(self, sha256: str, ext: str = "pdf") -> str:
        return content_key("sources/", sha256, ext)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise StorageError("key escapes storage root")
        return p

    def uri(self, key: str) -> str:
        return f"file://{self._path(key)}"

    def head(self, key: str) -> ObjectInfo | None:
        p = self._path(key)
        if not p.exists():
            return None
        return ObjectInfo(self.bucket, key, p.stat().st_size, None, None, "application/pdf")

    def presign_put(self, key: str, *, mime_type: str, size: int, sha256: str, ttl: int) -> PresignedUpload:
        if self.head(key) is not None:
            return PresignedUpload("", "NONE", {}, self.bucket, key, 0, already_exists=True)
        # tests upload with put_bytes; the URL is informational only
        return PresignedUpload(f"file://{self._path(key)}", "PUT", {"Content-Type": mime_type}, self.bucket, key, ttl)

    def get_bytes(self, key: str, *, max_bytes: int) -> bytes:
        p = self._path(key)
        if not p.exists():
            raise StorageError(f"object not found: {key}")
        if p.stat().st_size > max_bytes:
            raise StorageError("object too large")
        return p.read_bytes()

    def put_bytes(self, key: str, data: bytes, *, mime_type: str) -> ObjectInfo:
        p = self._path(key)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        info = self.head(key)
        assert info is not None
        return info

    def presign_get(self, key: str, *, ttl: int, filename: str | None = None) -> str:
        return f"file://{self._path(key)}"

    def delete_intake_copy(self, key: str, *, prefix: str, expected_etag: str | None) -> bool:
        import hashlib as _hl

        _check_deletable(key, prefix)
        p = self._path(key)
        if not p.exists():
            return False
        if expected_etag and _hl.md5(p.read_bytes()).hexdigest() != expected_etag:  # noqa: S324
            raise StorageError(f"{key} changed since it was scanned; not deleted")
        p.unlink()
        return True

    def list(self, prefix: str) -> list[ListedObject]:
        import datetime as _dt
        import hashlib as _hl

        base = self.root.resolve()
        out = []
        for p in sorted(base.rglob("*")):
            if p.is_file():
                key = p.relative_to(base).as_posix()
                if key.startswith(prefix):
                    st = p.stat()
                    etag = _hl.md5(p.read_bytes()).hexdigest()  # noqa: S324 - mirrors S3 ETag semantics for tests
                    out.append(ListedObject(key, st.st_size, etag, _dt.datetime.fromtimestamp(st.st_mtime, _dt.UTC).isoformat()))
        return out


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "local":
        return LocalStorage(settings.local_storage_dir)
    return S3Storage(settings)
