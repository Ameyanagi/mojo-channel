#!/usr/bin/env bash
# Called after the complete incoming candidate, ledger and solve checks pass.
set -euo pipefail
: "${EXPECTED_PACKAGE:?}"
: "${EXPECTED_VERSION:?}"
: "${EXPECTED_SHA:?}"
: "${GITHUB_OUTPUT:?}"
: "${GITHUB_STEP_SUMMARY:?}"
: "${GH_TOKEN:?}"
[[ "$EXPECTED_PACKAGE" =~ ^(mojo-[a-z]+|yuragi)$ ]]
[[ "$EXPECTED_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]
branch="release/${EXPECTED_PACKAGE}-${EXPECTED_VERSION}-${EXPECTED_SHA}"
git diff --cached --check
if git diff --cached --quiet; then
  echo "The exact package bytes are already published."
  echo "already_published=true" >> "$GITHUB_OUTPUT"
  echo 'The exact package bytes are already published; no release branch created.' >> "$GITHUB_STEP_SUMMARY"
  exit 0
fi
# A retry may reuse an existing proposal only when the complete tree is identical.
# A changed proposal is never overwritten, and no path uses force push.
existing="$(git ls-remote --heads origin "refs/heads/$branch")"
if [[ -n "$existing" ]]; then
  git fetch origin "refs/heads/$branch:refs/remotes/origin/$branch"
  proposed_tree="$(git write-tree)"
  existing_tree="$(git rev-parse "refs/remotes/origin/$branch^{tree}")"
  if [[ "$proposed_tree" != "$existing_tree" ]]; then
    echo "Existing proposal $branch has different bytes or base; review it before retrying." >&2
    exit 1
  fi
  proposal_sha="$(git rev-parse "refs/remotes/origin/$branch")"
else
  git commit -m "Publish ${EXPECTED_PACKAGE} ${EXPECTED_VERSION} from ${EXPECTED_SHA}"
  proposal_sha="$(git rev-parse HEAD)"
  # The credential helper expands the token only in its subprocess.
  # shellcheck disable=SC2016
  git \
    -c credential.helper= \
    -c 'credential.helper=!f() { printf "%s\n" username=x-access-token "password=$GH_TOKEN"; }; f' \
    push origin "HEAD:refs/heads/$branch"
fi
# GITHUB_TOKEN pushes do not trigger push/PR workflows. Explicit workflow_dispatch
# is the documented exception; no PR-creation or review-approval permission is used.
gh workflow run ci.yml --ref "$branch"
{
  echo "branch=$branch"
  echo "sha=$proposal_sha"
  echo "already_published=false"
} >> "$GITHUB_OUTPUT"
{
  echo '## Reviewed publication required'
  echo "Source commit: \`$EXPECTED_SHA\`"
  echo "Release branch: \`$branch\`"
  echo "Exact proposal commit: \`$proposal_sha\`"
  echo "Create a pull request: https://github.com/Ameyanagi/mojo-channel/compare/main...$branch?expand=1"
  echo 'Wait for Validate package gate on that exact commit, review the additive archives and merge normally.'
  echo 'This workflow did not update the public channel.'
} >> "$GITHUB_STEP_SUMMARY"
printf 'Publication proposal: %s at %s\n' "$branch" "$proposal_sha"
