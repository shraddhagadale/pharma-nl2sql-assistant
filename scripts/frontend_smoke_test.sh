#!/usr/bin/env bash
set -Eeuo pipefail

base_url="${1:-http://localhost:3000}"
cookie_file="$(mktemp /tmp/pharma-frontend-cookie.XXXXXX)"
headers_file="$(mktemp /tmp/pharma-frontend-headers.XXXXXX)"
body_file="$(mktemp /tmp/pharma-frontend-body.XXXXXX)"

cleanup() {
    rm -f "$cookie_file" "$headers_file" "$body_file"
}
trap cleanup EXIT

curl --fail --silent --show-error \
    --dump-header "$headers_file" \
    --output "$body_file" \
    "$base_url/"

grep --quiet '<title>Nova Insights</title>' "$body_file"
grep --ignore-case --quiet '^Content-Security-Policy:' "$headers_file"

health="$(curl --fail --silent --show-error "$base_url/health")"
[[ "$health" == '{"status":"ok"}' ]]

users="$(curl --fail --silent --show-error "$base_url/api/v1/demo/users")"
python3 -c 'import json, sys; users=json.loads(sys.argv[1]); assert any(u["role"] == "ram" for u in users); assert any(u["role"] == "exec" for u in users)' "$users"

curl --fail --silent --show-error \
    --cookie-jar "$cookie_file" \
    --header 'Content-Type: application/json' \
    --data '{"user_id":"U009"}' \
    "$base_url/api/v1/demo/session" >"$body_file"

python3 -c 'import json, sys; user=json.load(open(sys.argv[1])); assert user["role"] == "ram"; assert user["can_view_wac"] is False' "$body_file"

echo "Frontend smoke test passed: static UI, security headers, and same-origin session verified."
