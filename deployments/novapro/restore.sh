#!/bin/sh
# Restore a dump made by backup.sh into DATABASE_URL, replacing what is there.
#
#   docker compose stop api worker beat-worker live
#   docker compose run --rm --entrypoint /bin/sh db-backup /scripts/restore.sh /backups/plane-YYYYMMDD-HHMMSS.dump
#   docker compose up -d
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
dump="${1:?usage: restore.sh <dump file>}"
[ -f "$dump" ] || { echo "No such file: $dump" >&2; exit 1; }

pg_restore --list "$dump" >/dev/null
echo "Restoring $dump"
pg_restore --clean --if-exists --no-owner --exit-on-error --dbname="$DATABASE_URL" "$dump"
echo "Restored. Start the app containers again."
