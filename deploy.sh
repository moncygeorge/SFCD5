#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/ubuntu/SFCD5}"
SERVICE="${SERVICE:-sfcd5}"
BRANCH="${BRANCH:-main}"
BACKUP_ROOT="${BACKUP_ROOT:-/home/ubuntu/sfcd5-deploy-backups}"
cd "$APP_DIR"

[[ -d .git ]] || { echo 'ERROR: Not a Git checkout'; exit 1; }
command -v git >/dev/null
command -v python3 >/dev/null
command -v sudo >/dev/null

# Never discard uncommitted changes without explicit review.
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo 'STOP: Tracked files have uncommitted changes. Review git status first.'
  git status --short
  exit 1
fi

# The database normally lives in data/sfcd.db, but may be configured externally.
# Do not risk resetting any Git-tracked SQLite data or server-only config.
if git ls-files | grep -Eiq '(^|/)([^/]+\.(db|sqlite|sqlite3)|\.env($|\.)|.*\.pem|.*\.key)$'; then
  echo 'STOP: Git tracks database or sensitive configuration files. Review git ls-files first.'
  exit 1
fi

stamp="$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_ROOT"
backup="$BACKUP_ROOT/$stamp"
mkdir -p "$backup"
old_commit="$(git rev-parse HEAD)"
echo "$old_commit" > "$backup/previous-commit.txt"

# Back up current code including local commits and untracked files, excluding venv/cache.
tar -czf "$backup/application.tar.gz" --exclude='./venv' --exclude='./.git' --exclude='./__pycache__' -C "$APP_DIR" .
git bundle create "$backup/git-history.bundle" --all >/dev/null

# SQLite online backup; resolve app configuration from the systemd unit where possible.
service_env="$(sudo systemctl show "$SERVICE" -p Environment --value 2>/dev/null || true)"
configured_data="$(printf '%s\n' "$service_env" | sed -n 's/.*DATA_DIR=\([^ ]*\).*/\1/p')"
configured_db="$(printf '%s\n' "$service_env" | sed -n 's/.*DB_PATH=\([^ ]*\).*/\1/p')"
if [[ -n "$configured_db" ]]; then
  db="$configured_db"
elif [[ -n "$configured_data" ]]; then
  db="$configured_data/sfcd.db"
else
  db="$APP_DIR/data/sfcd.db"
fi
if [[ -f "$db" ]]; then
  python3 - "$db" "$backup/sfcd.db" <<'PY'
import sqlite3, sys
source = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True)
target = sqlite3.connect(sys.argv[2])
with target: source.backup(target)
target.close(); source.close()
PY
  echo "Database backed up from $db"
else
  echo "WARNING: No database found at $db. Confirm DB_PATH/DATA_DIR before proceeding."
  echo "Backup saved at $backup"
  exit 1
fi

# Fetch and replace tracked code; never delete untracked files.
git fetch origin "$BRANCH"
new_commit="$(git rev-parse "origin/$BRANCH")"
if [[ "$old_commit" == "$new_commit" ]]; then
  echo "Already at origin/$BRANCH ($new_commit); no deployment needed."
  exit 0
fi

echo "Deploying $old_commit -> $new_commit"
git reset --hard "$new_commit"
if ! python3 -m py_compile app.py init_db.py push.py; then
  echo 'Python syntax check failed. Restoring previous code commit.'
  git reset --hard "$old_commit"
  exit 1
fi

if ! sudo systemctl restart "$SERVICE" || ! sudo systemctl is-active --quiet "$SERVICE"; then
  echo 'Service restart failed. Restoring previous code commit and restarting.'
  git reset --hard "$old_commit"
  sudo systemctl restart "$SERVICE" || true
  echo "Check logs: sudo journalctl -u $SERVICE -n 80 --no-pager"
  exit 1
fi

echo "SUCCESS: $SERVICE deployed at $new_commit"
echo "Backup: $backup"
echo "Check logs: sudo journalctl -u $SERVICE -n 50 --no-pager"
