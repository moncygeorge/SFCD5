#!/usr/bin/env bash
set -euo pipefail
APP_DIR="${APP_DIR:-/home/ubuntu/SFCD5}"
DB_PATH="${DB_PATH:-$APP_DIR/data/sfcd.db}"
BACKUP_DIR="${BACKUP_DIR:-/home/ubuntu/sfcd5-backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
mkdir -p "$BACKUP_DIR"
stamp=$(date -u +%Y%m%d-%H%M%S)
dest="$BACKUP_DIR/sfcd-$stamp.db"
sqlite3 "$DB_PATH" ".backup '$dest'"
gzip "$dest"
find "$BACKUP_DIR" -type f -name 'sfcd-*.db.gz' -mtime +"$KEEP_DAYS" -delete
echo "Backup created: $dest.gz"
