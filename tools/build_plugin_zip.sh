#!/usr/bin/env bash
# Build the installable WordPress plugin ZIP: dist/trial-knowledge-<version>.zip
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLUGIN="$ROOT/wordpress/trial-knowledge"
VERSION="$(grep -m1 "Version:" "$PLUGIN/trial-knowledge.php" | awk '{print $NF}')"
cd "$PLUGIN"
if [ -x node_modules/.bin/wp-scripts ]; then npm run build >/dev/null; fi
test -f build/blocks/claim-card/index.js || { echo "blocks not built (run npm install && npm run build)"; exit 1; }
for f in $(find . -name "*.php" -not -path "./node_modules/*"); do php -l "$f" >/dev/null; done
php tests/run.php
mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/trial-knowledge-$VERSION.zip"
rm -f "$OUT"
cd "$ROOT/wordpress"
zip -qr "$OUT" trial-knowledge -x "trial-knowledge/node_modules/*" "trial-knowledge/package-lock.json" "trial-knowledge/tests/*"
echo "$OUT"
