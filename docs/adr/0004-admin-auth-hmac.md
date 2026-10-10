# ADR-0004: Admin authentication with signed service-account requests

**Status:** accepted

**Options in spec §32:** OAuth2 client credentials *or* service-account signatures. **Chosen:** HMAC-SHA256 request signatures (no extra identity server to run for a single WordPress client).

**Protocol.** Headers `X-NTK-Key-Id`, `X-NTK-Timestamp` (±300 s), `X-NTK-Nonce` (single use, stored in Redis 15 min), `X-NTK-Actor` (WordPress user, signed so it cannot be swapped), `X-NTK-Signature = hex HMAC(secret, METHOD\nPATH\nsorted-query\nts\nnonce\nactor\nsha256(body))`. Keys and scopes come from `NTK_SERVICE_KEYS`; scopes: `admin:read|ingest|review|publish|claims|all`. Every admin action writes an audit event with the actor.

**Rate limiting through WordPress.** Public Ask/Search requests that WordPress proxies would otherwise share the WordPress server's IP. WordPress therefore vouches for the visitor with `X-NTK-Client-Hash/Ts/Sig = HMAC(secret, ts\nclient_hash)`; the API rate-limits per vouched client, per session and per front-end key. Direct callers are limited by the rightmost `X-Forwarded-For` entry (set by Railway's edge), never by client-supplied entries.

**Verified by** a shared test vector (`tests/unit/...::test_signature_vector_shared_with_wordpress`, `wordpress/.../tests/test-signing.php`), replay/skew/bad-signature tests, and the e2e suite.
