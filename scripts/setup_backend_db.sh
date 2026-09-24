#!/usr/bin/env sh
set -eu

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(dirname "$script_dir")"

cd "$project_dir"

./scripts/apply_local_migration.sh schema/migrations/005_runtime_access.sql
./scripts/bootstrap_runtime_roles.sh

echo "Backend database roles are ready."
