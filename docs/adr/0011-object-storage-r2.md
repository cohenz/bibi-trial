# ADR-0011: Cloudflare R2 as object storage

**Decision.** Use R2 through the S3 API (`S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com`, `S3_REGION=auto`). Browsers upload with presigned PUT URLs signed for the exact `Content-Type` and `Content-Length`; credentials never reach WordPress pages or browsers.

**Content addressing.** Keys are `sources/sha256/<aa>/<sha256>.pdf`. R2 has no object versioning, so immutability comes from the key: a key can only ever hold one content. If the object already exists the presign call returns `already_exists` and no upload happens. The worker always re-hashes the downloaded bytes; ETag is stored for operations only. `s3_version_id` stays empty on R2.

**Retention.** Configure an R2 Bucket Lock (retention) rule on `sources/` so source files cannot be deleted or overwritten for the retention period.
