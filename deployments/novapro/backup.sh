#!/bin/sh
# Back up Plane's Postgres database with pg_dump (custom format), verify it, prune old ones.
#
#   backup.sh            one backup, then exit
#   backup.sh --loop     back up every BACKUP_INTERVAL_HOURS forever (the db-backup service)
#
# Environment:
#   DATABASE_URL            postgresql://user:password@host:5432/db (required)
#   BACKUP_DIR              where dumps go (default /backups)
#   BACKUP_RETENTION_DAYS   delete dumps older than this; 0 keeps everything (default 14)
#   BACKUP_INTERVAL_HOURS   pause between backups with --loop (default 24)
#
# One-off from the Compose project:
#   docker compose run --rm --entrypoint /bin/sh db-backup /scripts/backup.sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
BACKUP_INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-24}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

backup_once() {
  mkdir -p "$BACKUP_DIR"
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  target="$BACKUP_DIR/plane-$stamp.dump"
  partial="$target.partial"

  log "Backing up to $target"
  if ! pg_dump --format=custom --compress=6 --no-owner --dbname="$DATABASE_URL" --file="$partial"; then
    rm -f "$partial"
    log "pg_dump failed"
    return 1
  fi
  # A dump that pg_restore cannot list is not a backup
  if ! pg_restore --list "$partial" >/dev/null; then
    rm -f "$partial"
    log "Verification failed; dump removed"
    return 1
  fi
  mv "$partial" "$target"
  log "Done: $(du -h "$target" | cut -f1) $target"

  if [ "$BACKUP_RETENTION_DAYS" -gt 0 ]; then
    find "$BACKUP_DIR" -maxdepth 1 -name 'plane-*.dump' -type f -mtime +"$BACKUP_RETENTION_DAYS" -print -delete |
      while read -r removed; do log "Pruned $removed"; done
  fi
}

if [ "${1:-}" = "--loop" ]; then
  log "Backing up every ${BACKUP_INTERVAL_HOURS}h, keeping ${BACKUP_RETENTION_DAYS} days"
  while true; do
    backup_once || log "Backup failed; retrying next interval"
    sleep "$((BACKUP_INTERVAL_HOURS * 3600))"
  done
else
  backup_once
fi
