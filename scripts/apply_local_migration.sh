#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 path/to/migration.sql" >&2
  exit 2
fi

migration_path="$1"
if [ ! -f "$migration_path" ]; then
  echo "Migration not found: $migration_path" >&2
  exit 2
fi

db_name="${POSTGRES_DB:-pharma}"
db_user="${POSTGRES_USER:-pharma_admin}"

docker compose exec -T postgres psql \
  --username "$db_user" \
  --dbname "$db_name" \
  --set ON_ERROR_STOP=1 < "$migration_path"
