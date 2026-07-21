#!/bin/sh

#
# Exports the whole dev database (schema + data) to a single file, so it can
# later be loaded into production with scripts/import-db.sh.
#
# Assumes `docker compose` is installed and set up on the host, and that the
# dev stack (docker-compose.yml) is running.
#
# Usage: scripts/export-db.sh [output-file]
#   Defaults to backups/theo-dev-<UTC timestamp>.dump
#

set -e

cd "$(dirname "$0")/.."

OUT_FILE="${1:-backups/theo-dev-$(date -u +%Y%m%dT%H%M%SZ).dump}"
mkdir -p "$(dirname "$OUT_FILE")"

echo "Exporting dev database to $OUT_FILE ..."

# Custom format (-Fc): compressed, and restorable with pg_restore regardless
# of table/index order. Run pg_dump inside the container itself so its
# version always matches the server (rather than relying on a host install).
docker compose exec -T db sh -c '
  set -e
  PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc
' > "$OUT_FILE"

echo "Done: $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"
