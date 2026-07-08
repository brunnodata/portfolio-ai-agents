#!/bin/sh
# Rotina de backup do PostgreSQL (RF-33)
# Uso: ./scripts/backup.sh
# Configure PGHOST, PGUSER, PGPASSWORD, PGDATABASE via ambiente

set -e

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"

PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-postgres}"
PGDATABASE="${PGDATABASE:-gastozap}"

FILE="$BACKUP_DIR/gastozap_${TIMESTAMP}.sql.gz"

echo "Gerando backup em $FILE ..."
PGPASSWORD="$PGPASSWORD" pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$PGDATABASE" | gzip > "$FILE"
echo "Backup concluído: $FILE"
