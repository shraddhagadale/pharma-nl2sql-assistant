#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 OUTPUT_ARCHIVE GIT_COMMIT_SHA" >&2
    exit 2
fi

output_archive="$1"
commit_sha="$2"
script_dir="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(CDPATH='' cd -- "$script_dir/.." && pwd)"

if [[ ! "$commit_sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "GIT_COMMIT_SHA must be a full 40-character lowercase commit SHA." >&2
    exit 2
fi

if ! git -C "$repository_root" cat-file -e "$commit_sha^{commit}"; then
    echo "Commit $commit_sha does not exist in this checkout." >&2
    exit 2
fi

mkdir -p "$(dirname -- "$output_archive")"
git -C "$repository_root" archive \
    --format=tar.gz \
    --output="$output_archive" \
    "$commit_sha"

echo "Packaged immutable release $commit_sha at $output_archive"
