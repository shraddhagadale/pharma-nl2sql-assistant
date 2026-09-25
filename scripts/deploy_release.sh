#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 GIT_COMMIT_SHA" >&2
    exit 2
fi

release_id="$1"
: "${AWS_RELEASE_BUCKET:?AWS_RELEASE_BUCKET is required}"
: "${AWS_INSTANCE_ID:?AWS_INSTANCE_ID is required}"
: "${AWS_RUNTIME_SECRET_ARN:?AWS_RUNTIME_SECRET_ARN is required}"
: "${AWS_DATA_PREFIX:?AWS_DATA_PREFIX is required}"
: "${APP_URL:?APP_URL is required}"

if [[ ! "$release_id" =~ ^[0-9a-f]{40}$ ]]; then
    echo "GIT_COMMIT_SHA must be a full 40-character lowercase commit SHA." >&2
    exit 2
fi

script_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(CDPATH='' cd -- "$script_dir/.." && pwd)"
release_key="releases/app/$release_id/source.tar.gz"
release_uri="s3://$AWS_RELEASE_BUCKET/$release_key"
data_uri="s3://$AWS_RELEASE_BUCKET/${AWS_DATA_PREFIX#/}"
upload_release="${UPLOAD_RELEASE:-true}"
artifact_dir="$(mktemp -d /tmp/pharma-code-release.XXXXXX)"

cleanup() {
    rm -rf "$artifact_dir"
}
trap cleanup EXIT

if [[ "$upload_release" == "true" ]]; then
    "$script_dir/package_release.sh" "$artifact_dir/source.tar.gz" "$release_id"
    aws s3 cp \
        "$artifact_dir/source.tar.gz" \
        "$release_uri" \
        --only-show-errors
elif [[ "$upload_release" != "false" ]]; then
    echo "UPLOAD_RELEASE must be true or false." >&2
    exit 2
fi

aws s3api head-object \
    --bucket "$AWS_RELEASE_BUCKET" \
    --key "$release_key" >/dev/null

remote_dir="/tmp/pharma-release-$release_id"
remote_command="rm -rf '$remote_dir' && mkdir -p '$remote_dir' && aws s3 cp '$release_uri' '$remote_dir/source.tar.gz' --only-show-errors && tar -xzf '$remote_dir/source.tar.gz' -C '$remote_dir' && bash '$remote_dir/scripts/aws_deploy_remote.sh' '$data_uri' '$AWS_RUNTIME_SECRET_ARN' '$release_id'"
parameters="$(jq -cn --arg command "$remote_command" '{commands:[$command],executionTimeout:["7200"]}')"

command_id="$(aws ssm send-command \
    --instance-ids "$AWS_INSTANCE_ID" \
    --document-name AWS-RunShellScript \
    --comment "Deploy pharma NL-to-SQL release $release_id" \
    --timeout-seconds 7200 \
    --parameters "$parameters" \
    --query 'Command.CommandId' \
    --output text)"

echo "Deployment command: $command_id"
for _ in {1..720}; do
    status="$(aws ssm get-command-invocation \
        --command-id "$command_id" \
        --instance-id "$AWS_INSTANCE_ID" \
        --query Status \
        --output text 2>/dev/null || true)"
    case "$status" in
        Success)
            break
            ;;
        Failed|Cancelled|TimedOut|Cancelling)
            aws ssm get-command-invocation \
                --command-id "$command_id" \
                --instance-id "$AWS_INSTANCE_ID" \
                --output json
            exit 1
            ;;
        *)
            sleep 10
            ;;
    esac
done

final_status="$(aws ssm get-command-invocation \
    --command-id "$command_id" \
    --instance-id "$AWS_INSTANCE_ID" \
    --query Status \
    --output text)"
if [[ "$final_status" != "Success" ]]; then
    echo "Deployment did not reach Success before the polling deadline: $final_status" >&2
    exit 1
fi

aws ssm get-command-invocation \
    --command-id "$command_id" \
    --instance-id "$AWS_INSTANCE_ID" \
    --query '{Status:Status,Output:StandardOutputContent,Errors:StandardErrorContent}' \
    --output json

"$repository_root/scripts/frontend_smoke_test.sh" "$APP_URL"
echo "Immutable AWS release passed: $release_id at $APP_URL"
