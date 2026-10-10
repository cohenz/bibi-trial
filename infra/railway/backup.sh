#!/bin/sh
# pg_dump → gzip → R2 (s3://$BACKUP_BUCKET/db/YYYY/MM/DD/ntk-<ts>.sql.gz). Never prints secrets.
set -eu
TS="$(date -u +%Y%m%dT%H%M%SZ)"
KEY="db/$(date -u +%Y/%m/%d)/ntk-$TS.sql.gz"
URL="$(echo "$DATABASE_URL" | sed 's#^postgresql+psycopg://#postgresql://#')"
pg_dump --format=plain --no-owner --no-privileges "$URL" | gzip -9 > /tmp/backup.sql.gz
AWS_ACCESS_KEY_ID="$BACKUP_ACCESS_KEY_ID" AWS_SECRET_ACCESS_KEY="$BACKUP_SECRET_ACCESS_KEY" \
  aws s3 cp /tmp/backup.sql.gz "s3://$BACKUP_BUCKET/$KEY" --endpoint-url "$S3_ENDPOINT_URL" --region auto --only-show-errors
echo "backup written: s3://$BACKUP_BUCKET/$KEY ($(wc -c < /tmp/backup.sql.gz) bytes)"
