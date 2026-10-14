#!/usr/bin/env bash
# Asyntai AI Docs Sync: send the documentation in the repository to the Asyntai
# knowledge base. The work is done by sync.py; this script only turns the Step
# inputs into arguments for it and exports the summary for later Steps.
set -euo pipefail

THIS_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

docs_path="${docs_path:-}"
file_patterns="${file_patterns:-*.md,*.mdx,*.txt}"
exclude="${exclude:-}"
title_prefix="${title_prefix:-}"
website_id="${website_id:-}"
prune="${prune:-no}"
dry_run="${dry_run:-no}"
base_url="${base_url:-https://asyntai.com}"

if [[ -z "$docs_path" ]]; then
  echo "Error: the Step needs a Documentation path, for example docs" >&2
  exit 1
fi

for pair in "prune:$prune" "dry_run:$dry_run"; do
  value="${pair#*:}"
  if [[ "$value" != "yes" && "$value" != "no" ]]; then
    echo "Error: ${pair%%:*} must be yes or no, not '$value'." >&2
    exit 1
  fi
done

# A relative path is read from the source directory, the same place Git Clone
# puts the repository, whatever the working directory of the Step is.
if [[ "$docs_path" != /* && -n "${BITRISE_SOURCE_DIR:-}" ]]; then
  docs_path="${BITRISE_SOURCE_DIR%/}/$docs_path"
fi

PYTHON_BIN=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Error: this Step needs Python 3 on the build machine, and none was found." >&2
  exit 1
fi

ARGS=(
  --path "$docs_path"
  --patterns "$file_patterns"
  --exclude "$exclude"
  --title-prefix "$title_prefix"
  --website-id "$website_id"
  --base-url "$base_url"
)
[[ "$prune" == "yes" ]] && ARGS+=(--prune)
[[ "$dry_run" == "yes" ]] && ARGS+=(--dry-run)

HAS_ENVMAN="no"
command -v envman >/dev/null 2>&1 && HAS_ENVMAN="yes"

# Print every line to the build log as it comes. The summary line (the last
# "Done.", "Dry run." or "Error:" line) becomes the Step output; a later
# envman add with the same key replaces an earlier one.
set +e
ASYNTAI_API_KEY="${asyntai_api_key:-}" "$PYTHON_BIN" -u "$THIS_SCRIPT_DIR/sync.py" "${ARGS[@]}" 2>&1 |
  while IFS= read -r line || [[ -n "$line" ]]; do
    printf '%s\n' "$line"
    case "$line" in
      Done.* | "Dry run."* | Error:*)
        if [[ "$HAS_ENVMAN" == "yes" ]]; then
          envman add --key ASYNTAI_DOCS_SYNC_SUMMARY --value "$line"
        fi
        ;;
    esac
  done
STATUS="${PIPESTATUS[0]}"
set -e

exit "$STATUS"
