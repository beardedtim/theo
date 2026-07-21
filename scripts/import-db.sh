#!/bin/sh

#
# Imports a dump produced by scripts/export-db.sh into the production
# database, replacing whatever data is currently there.
#
# Assumes `docker compose` is installed and set up on the host.
#
# Usage: scripts/import-db.sh <dump-file> [-y|--yes]
#   -y, --yes   skip the "this will overwrite prod" confirmation prompt
#

set -e

cd "$(dirname "$0")/.."

DUMP_FILE=""
ASSUME_YES=false

for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=true ;;
    *) DUMP_FILE="$arg" ;;
  esac
done

if [ -z "$DUMP_FILE" ]; then
  echo "Usage: scripts/import-db.sh <dump-file> [-y|--yes]" >&2
  exit 1
fi

if [ ! -f "$DUMP_FILE" ]; then
  echo "No such file: $DUMP_FILE" >&2
  exit 1
fi

if [ "$ASSUME_YES" != true ]; then
  printf 'This will REPLACE all data in the PRODUCTION database with %s. Continue? [y/N] ' "$DUMP_FILE"
  read -r REPLY
  case "$REPLY" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 1 ;;
  esac
fi

# Make sure the prod db is up before restoring into it
docker compose -f docker-compose.prod.yaml up -d --wait db

echo "Restoring $DUMP_FILE into the production database ..."

# --clean --if-exists: drop existing objects first (safe to rerun; also
# handles the tables/indexes/extensions that docker-compose.prod.yaml's own
# init.sql already created on first boot). --no-owner/--no-privileges: dev
# and prod use the same POSTGRES_USER, but skip role-specific statements
# regardless so this stays portable if that ever changes.
docker compose -f docker-compose.prod.yaml exec -T db sh -c '
  set -e
  PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges
' < "$DUMP_FILE"

echo "Done."
