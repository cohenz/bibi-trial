# Plugin tests

Dependency-free PHP tests (no WordPress install needed). `bootstrap.php` stubs the WordPress functions the plugin uses.

```bash
php tests/run.php
```

| file | covers |
|---|---|
| `test-signing.php` | HMAC canonical string and signature byte-identical to the Python API (shared test vector), query sorting and encoding |
| `test-settings-cache-webhook.php` | secret encrypted at rest (random IV, plaintext never stored), cache read-through and purge by tag, webhook signature: valid accepted, modified body / stale timestamp / missing secret rejected, purge tags derived from the event |
| `test-render.php` | HTML escaping of model/user text (no `<script>`, `<img>`, tags), weakness section always shown, judicial remark labelled as not-a-ruling, citation page/line text, RTL container, answer permalink + corpus version |

The end-to-end path (browser → presign → R2 PUT → job → review → publish → public block) is exercised against live services by `tools/e2e_live.py`, which performs exactly the calls the plugin makes.

Not covered here: `noindex`/JSON-LD output of the public pages, and a real WordPress install (Gutenberg editor UI, rewrite rules in a live site). Smoke-test those manually after installing the ZIP: activate → Settings → "בדיקת חיבור" → upload one PDF → approve → insert a "כרטיס טענה" block.
