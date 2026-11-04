#!/usr/bin/env bash
# One-time repo setup for a scaffolded integration: the GitHub-side settings no file in
# the repo can carry. What each one is for, and what fails without it, is the
# ha-integration skill's reference/github-setup.md.
#
# Run from the repo root, once, after the first push:
#   bash scripts/bootstrap_repo.sh "One-line description of the integration"
# On a repo adopting the stack, --replace-all also deletes every other repository
# ruleset that still requires checks on the default branch:
#   bash scripts/bootstrap_repo.sh --replace-all "One-line description"
#
# Needs a gh login with admin on the repo. RELEASE_TOKEN is prompted for, never
# passed as an argument, so it stays out of shell history and process listings.
set -euo pipefail

REPLACE_ALL=""
DESC=""
for ARG in "$@"; do
  if [ "$ARG" = --replace-all ]; then
    REPLACE_ALL=1
  else
    DESC=$ARG
  fi
done
REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
DOMAIN=$(basename "$(ls -d custom_components/*/ | head -1)")

echo "Setting up $REPO (domain: $DOMAIN)"

if [ -n "$DESC" ]; then
  gh repo edit "$REPO" --description "$DESC"
  echo "  description set"
else
  echo "  no description given — HACS will fail its description check"
fi

gh repo edit "$REPO" \
  --add-topic home-assistant \
  --add-topic hacs \
  --add-topic home-assistant-custom-component \
  --enable-issues
echo "  topics and issues set"

# dependency-review.yml fails rather than skipping when the graph is off (the skill's
# reference/github-setup.md), so a repo that never enabled it carries a permanently
# red required check.
if gh api "repos/$REPO/dependency-graph/sbom" >/dev/null 2>&1; then
  echo "  dependency graph already enabled"
elif gh api -X PATCH "repos/$REPO" -F security_and_analysis[dependency_graph][status]=enabled \
     >/dev/null 2>&1; then
  echo "  dependency graph enabled"
else
  echo "  COULD NOT enable the dependency graph — do it at Settings -> Advanced Security,"
  echo "  or Dependency review stays red on every PR"
fi

if [ ! -f LICENSE ]; then
  echo "  no LICENSE — HACS fails with SPDX: NOASSERTION until one exists"
fi

# The hook is a file until this points at it.
git config core.hooksPath .githooks
echo "  commit-msg hook enabled"

# Why "Protect main" is replaced and every other ruleset requiring checks is named is
# the ha-integration skill's reference/github-setup.md.
if [ -f ruleset.json ]; then
  ID=$(gh api --paginate "repos/$REPO/rulesets" --jq '.[] | select(.source_type == "Repository"
    and .target == "branch" and .name == "Protect main") | .id')
  if [ -n "$ID" ]; then
    gh api -X PUT "repos/$REPO/rulesets/$ID" --input ruleset.json >/dev/null
    echo "  ruleset replaced from ruleset.json"
  else
    ID=$(gh api -X POST "repos/$REPO/rulesets" --input ruleset.json --jq .id)
    echo "  ruleset applied"
  fi
  MAIN=$(gh repo view --json defaultBranchRef --jq .defaultBranchRef.name)
  OTHERS=$(gh api --paginate "repos/$REPO/rules/branches/$MAIN" --jq ".[]
    | select(.type == \"required_status_checks\" and .ruleset_id != $ID)
    | \"\(.ruleset_id) \(.ruleset_source_type) \(.ruleset_source)\"" | sort -u)
  while read -r OTHER SOURCE OWNER; do
    if [ -z "$OTHER" ]; then
      continue
    elif [ "$SOURCE" = Repository ] && [ -n "$REPLACE_ALL" ]; then
      gh api -X DELETE "repos/$REPO/rulesets/$OTHER" >/dev/null
      echo "  ruleset $OTHER deleted"
    elif [ "$SOURCE" = Repository ]; then
      echo "  ruleset $OTHER also requires checks on $MAIN, so every PR waits on its"
      echo "  old contexts — delete it at https://github.com/$REPO/settings/rules/$OTHER"
      echo "  or re-run with --replace-all"
    else
      echo "  $OWNER's organisation ruleset $OTHER also requires checks on $MAIN —"
      echo "  remove $MAIN from it at https://github.com/organizations/$OWNER/settings/rules/$OTHER"
    fi
  done <<< "$OTHERS"
else
  echo "  no ruleset.json in the repo root — copy it from the skill's templates/"
fi

if gh secret list --json name --jq '.[].name' | grep -qx RELEASE_TOKEN; then
  echo "  RELEASE_TOKEN already set"
else
  echo
  echo "RELEASE_TOKEN is required by auto-draft-pr.yml. Create a fine-grained PAT with"
  echo "Contents: Read and write, Pull requests: Read and write, scoped to this repo."
  read -rsp "Paste it (or press Enter to skip): " TOKEN
  echo
  if [ -n "$TOKEN" ]; then
    printf '%s' "$TOKEN" | gh secret set RELEASE_TOKEN
    echo "  RELEASE_TOKEN set"
  else
    echo "  skipped — draft PRs will not open until it exists"
  fi
fi

echo
echo "Done. Remaining by hand: nothing, unless a step above said otherwise."
