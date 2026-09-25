#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(CDPATH= cd -- "$script_dir/.." && pwd)"
aws_config_dir="${AWS_CONFIG_DIR:-$repository_root/.aws-local}"
terraform_image="hashicorp/terraform:1.12.2"
aws_image="amazon/aws-cli:latest"
release_prefix="releases/full-data-v1"
artifact_dir="$(mktemp -d /tmp/pharma-aws-release.XXXXXX)"

cleanup() {
    rm -rf "$artifact_dir"
}
trap cleanup EXIT

if [[ ! -f "$aws_config_dir/config" ]]; then
    echo "Missing AWS CLI configuration at $aws_config_dir/config" >&2
    exit 2
fi

for csv in organizations.csv products.csv sales.csv zip_territory.csv; do
    if [[ ! -f "$repository_root/schema/generated/$csv" ]]; then
        echo "Missing schema/generated/$csv; run python3 schema/generate_data.py first." >&2
        exit 2
    fi
done

terraform_output() {
    docker run --rm \
        --volume "$repository_root:/workspace" \
        --workdir /workspace/infra/terraform \
        "$terraform_image" output -raw "$1"
}

aws_cli() {
    docker run --rm \
        --volume "$aws_config_dir:/root/.aws" \
        "$aws_image" "$@"
}

bucket="$(terraform_output data_bucket_name)"
instance_id="$(terraform_output ssm_instance_id)"
runtime_secret_arn="$(terraform_output app_runtime_secret_arn)"
app_url="$(terraform_output app_url)"
bundle_key="$release_prefix/source.tar.gz"
data_prefix="$release_prefix/data"

COPYFILE_DISABLE=1 tar --no-xattrs \
    --exclude='.git' \
    --exclude='.aws-local' \
    --exclude='.venv' \
    --exclude='assignment' \
    --exclude='frontend/node_modules' \
    --exclude='frontend/dist' \
    --exclude='infra/terraform/.terraform' \
    --exclude='infra/terraform/*.tfstate*' \
    --exclude='infra/terraform/*.tfplan' \
    --exclude='schema/generated' \
    -czf "$artifact_dir/source.tar.gz" \
    -C "$repository_root" .

docker run --rm \
    --volume "$aws_config_dir:/root/.aws" \
    --volume "$artifact_dir:/artifacts:ro" \
    "$aws_image" s3 cp /artifacts/source.tar.gz "s3://$bucket/$bundle_key" --only-show-errors

docker run --rm \
    --volume "$aws_config_dir:/root/.aws" \
    --volume "$repository_root/schema/generated:/data:ro" \
    "$aws_image" s3 sync /data "s3://$bucket/$data_prefix" \
        --exclude '*' --include '*.csv' --size-only --only-show-errors

bundle_uri="s3://$bucket/$bundle_key"
data_uri="s3://$bucket/$data_prefix"
remote_command="rm -rf /tmp/pharma-release && mkdir -p /tmp/pharma-release && aws s3 cp '$bundle_uri' /tmp/pharma-release/source.tar.gz --only-show-errors && tar -xzf /tmp/pharma-release/source.tar.gz -C /tmp/pharma-release && bash /tmp/pharma-release/scripts/aws_deploy_remote.sh '$data_uri' '$runtime_secret_arn'"
parameters="$(jq -cn --arg command "$remote_command" '{commands:[$command],executionTimeout:["7200"]}')"

command_id="$(aws_cli ssm send-command \
    --instance-ids "$instance_id" \
    --document-name AWS-RunShellScript \
    --comment "Deploy pharma NL-to-SQL application" \
    --timeout-seconds 7200 \
    --parameters "$parameters" \
    --query 'Command.CommandId' \
    --output text)"

echo "Deployment command: $command_id"
while true; do
    status="$(aws_cli ssm get-command-invocation \
        --command-id "$command_id" \
        --instance-id "$instance_id" \
        --query Status \
        --output text 2>/dev/null || true)"
    case "$status" in
        Success)
            break
            ;;
        Failed|Cancelled|TimedOut|Cancelling)
            aws_cli ssm get-command-invocation \
                --command-id "$command_id" \
                --instance-id "$instance_id" \
                --output json
            exit 1
            ;;
        *)
            sleep 15
            ;;
    esac
done

aws_cli ssm get-command-invocation \
    --command-id "$command_id" \
    --instance-id "$instance_id" \
    --query '{Status:Status,Output:StandardOutputContent,Errors:StandardErrorContent}' \
    --output json

"$repository_root/scripts/frontend_smoke_test.sh" "$app_url"
echo "AWS deployment passed: $app_url"
