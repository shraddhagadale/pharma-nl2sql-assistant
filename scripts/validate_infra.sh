#!/usr/bin/env sh
set -eu

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(CDPATH= cd -- "$script_dir/.." && pwd)"
terraform_image="hashicorp/terraform:1.12.2"

run_terraform() {
  docker run --rm \
    --volume "$repository_root:/workspace" \
    --workdir /workspace/infra/terraform \
    "$terraform_image" "$@"
}

run_terraform fmt -check -recursive
run_terraform init -backend=false -input=false
run_terraform validate
run_terraform test

echo "Terraform formatting, initialization, validation, and mocked security tests passed."
