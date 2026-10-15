#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "::error::$*" >&2
  exit 1
}

if [ "$#" -lt 2 ]; then
  fail 'Usage: scripts/publish-refresh.sh "<commit message>" <path> [<path>...]'
fi

message="$1"
shift

refresh_page_dates() {
  python -m etl.pages.page_dates || fail "Page dates failed; refusing to publish."
  local output_list
  output_list=$(python -m etl.pages.page_dates --list-outputs) || fail "Cannot list page-date outputs."
  local -a outputs
  mapfile -t outputs <<< "$output_list"
  git add -- "${outputs[@]}" || fail "Cannot stage page-date outputs."
}

refresh_page_dates
git add -- "$@" || fail "Cannot stage refresh outputs."
if git diff --cached --quiet; then
  echo "No changes."
  exit 0
fi
git commit -m "$message" || fail "Cannot commit refresh outputs."

for attempt in 1 2 3; do
  if git push origin HEAD:main; then
    exit 0
  fi
  if [ "$attempt" -eq 3 ]; then
    fail "Publish failed after 3 push attempts."
  fi
  echo "Push attempt $attempt failed; rebasing onto origin/main."
  git fetch origin main || fail "Cannot fetch origin/main for retry."
  # During rebase, theirs is this job's commit: keep its fresh data on conflict.
  if ! git rebase -X theirs origin/main; then
    git rebase --abort || fail "Rebase failed and could not be aborted; refusing to publish."
    fail "Rebase failed; aborted and refusing to publish."
  fi
  # Merged content can differ from either job's tree, invalidating stored hashes.
  refresh_page_dates
  if ! git diff --cached --quiet; then
    git commit --amend --no-edit || fail "Cannot amend page dates after rebase."
  fi
done
