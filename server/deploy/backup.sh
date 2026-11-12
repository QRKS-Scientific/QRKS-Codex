#!/usr/bin/env bash
# Consistent online backup of the SQLite database. Run daily from cron:
#   17 3 * * *  /home/ubuntu/qrksdock-server/deploy/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
stamp=$(date -u +%Y%m%dT%H%M%SZ)
sqlite3 data/qrksdock.db ".backup 'backups/qrksdock-$stamp.db'"
gzip -f "backups/qrksdock-$stamp.db"
find backups -name 'qrksdock-*.db.gz' -mtime +30 -delete
echo "backup written: backups/qrksdock-$stamp.db.gz"
# Off-machine copy (a backup on the same disk is not a backup). Example with rclone and a Google Drive remote:
#   rclone copy backups/qrksdock-$stamp.db.gz gdrive:QRKS-server-backups/
