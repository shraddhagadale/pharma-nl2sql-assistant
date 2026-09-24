#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 s3://bucket/path/backend-checkpoint.tar.gz" >&2
    exit 2
fi

bundle_uri="$1"
work_dir="$(mktemp -d /tmp/pharma-backend-checkpoint.XXXXXX)"
container_name="pharma-backend-checkpoint"
runtime_roles_enabled=false
master_username=""
master_password=""

cleanup() {
    set +e
    docker rm --force "$container_name" >/dev/null 2>&1
    docker image rm --force pharma-backend-checkpoint:latest >/dev/null 2>&1
    if [[ "$runtime_roles_enabled" == true && -n "$master_username" ]]; then
        export PGPASSWORD="$master_password"
        printf '%s\n' \
            "ALTER ROLE pharma_runtime_auth NOLOGIN;" \
            "ALTER ROLE pharma_runtime_limited NOLOGIN;" \
            "ALTER ROLE pharma_runtime_exec NOLOGIN;" \
            | psql \
                "host=$DATABASE_HOST port=$DATABASE_PORT dbname=$DATABASE_NAME user=$master_username sslmode=require" \
                --set ON_ERROR_STOP=1 >/dev/null
    fi
    unset PGPASSWORD master_password auth_password limited_password exec_password session_secret
    rm -rf "$work_dir"
}
trap cleanup EXIT

source /opt/pharma-nl2sql/infrastructure.env

if ! command -v psql >/dev/null 2>&1; then
    dnf install -y postgresql16 >/dev/null
fi

aws s3 cp "$bundle_uri" "$work_dir/source.tar.gz" --only-show-errors
tar -xzf "$work_dir/source.tar.gz" -C "$work_dir"

master_secret="$({
    aws secretsmanager get-secret-value \
        --secret-id "$DATABASE_SECRET_ARN" \
        --query SecretString \
        --output text
})"
master_username="$(jq -r '.username' <<<"$master_secret")"
master_password="$(jq -r '.password' <<<"$master_secret")"
unset master_secret

export PGPASSWORD="$master_password"
psql \
    "host=$DATABASE_HOST port=$DATABASE_PORT dbname=$DATABASE_NAME user=$master_username sslmode=require" \
    --set ON_ERROR_STOP=1 \
    --file "$work_dir/schema/migrations/005_runtime_access.sql" >/dev/null

auth_password="$(openssl rand -hex 24)"
limited_password="$(openssl rand -hex 24)"
exec_password="$(openssl rand -hex 24)"
session_secret="$(openssl rand -hex 32)"

runtime_roles_enabled=true
{
    printf "ALTER ROLE pharma_runtime_auth LOGIN PASSWORD '%s';\n" "$auth_password"
    printf "ALTER ROLE pharma_runtime_limited LOGIN PASSWORD '%s';\n" "$limited_password"
    printf "ALTER ROLE pharma_runtime_exec LOGIN PASSWORD '%s';\n" "$exec_password"
} | psql \
    "host=$DATABASE_HOST port=$DATABASE_PORT dbname=$DATABASE_NAME user=$master_username sslmode=require" \
    --set ON_ERROR_STOP=1 >/dev/null

cat >"$work_dir/backend.env" <<ENVFILE
PHARMA_ENVIRONMENT=demo
PHARMA_DB_HOST=$DATABASE_HOST
PHARMA_DB_PORT=$DATABASE_PORT
PHARMA_DB_NAME=$DATABASE_NAME
PHARMA_DB_AUTH_USER=pharma_runtime_auth
PHARMA_DB_AUTH_PASSWORD=$auth_password
PHARMA_DB_LIMITED_USER=pharma_runtime_limited
PHARMA_DB_LIMITED_PASSWORD=$limited_password
PHARMA_DB_EXEC_USER=pharma_runtime_exec
PHARMA_DB_EXEC_PASSWORD=$exec_password
PHARMA_SESSION_SECRET=$session_secret
PHARMA_COOKIE_SECURE=false
ENVFILE
chmod 600 "$work_dir/backend.env"

docker build --quiet --tag pharma-backend-checkpoint:latest "$work_dir/backend" >/dev/null
docker run \
    --detach \
    --name "$container_name" \
    --network host \
    --env-file "$work_dir/backend.env" \
    pharma-backend-checkpoint:latest >/dev/null

for _ in {1..30}; do
    if curl --fail --silent http://127.0.0.1:8000/ready >/dev/null; then
        break
    fi
    sleep 2
done

if ! curl --fail --silent http://127.0.0.1:8000/ready >/dev/null; then
    docker logs "$container_name" >&2
    exit 1
fi

python3 "$work_dir/scripts/backend_api_smoke_test.py" http://127.0.0.1:8000

echo "AWS backend checkpoint passed; cleanup will remove the container and disable runtime logins."
