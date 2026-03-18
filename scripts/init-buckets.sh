#!/bin/sh
set -e

mc alias set local http://minio:9000 "${MINIO_ROOT_USER:-minioadmin}" "${MINIO_ROOT_PASSWORD:-minioadmin_secret}"

BUCKETS="raw-payloads shipping-labels reports backups"

for BUCKET in $BUCKETS; do
  mc mb --ignore-existing "local/$BUCKET"
  echo "Bucket ready: $BUCKET"
done

echo "All buckets created."
