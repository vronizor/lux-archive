#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
BACKUP_DIR="${BACKUP_DIR:-../lux-archive-data}"
docker compose exec -T lux python -m app.backup export /backup
cd "$BACKUP_DIR"
git add -A
if ! git diff --cached --quiet; then
  git commit -qm "backup $(date +%F)"
  git push -q
fi
