#!/usr/bin/env bash
# One-shot git initialisation for this repo.
#
# The integration was built on a single working tree (no incremental commits),
# so a true task-by-task history can't be reconstructed — a file's final content
# can't be split back into its per-task diffs. This imports the tree as a clean,
# readable set of thematic commits on `main`. Run once, from the repo root:
#   bash scripts/init-git.sh
#
# The hooks are enabled only after these commits: the prek hooks guard `main`
# with no-commit-to-branch, which would refuse every commit below. Each subject
# is checked against .githooks/commit-msg here instead.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -d .git ]; then
  if git rev-parse --verify -q HEAD >/dev/null 2>&1; then
    echo "Repo already has commits — aborting." >&2
    exit 1
  fi
  echo "Existing empty repo — keeping it (remote/config preserved), adding commits."
else
  git init -b main
fi

git symbolic-ref HEAD refs/heads/main  # ensure the branch is main, not master

msg_file=$(mktemp)
trap 'rm -f "$msg_file"' EXIT

commit() {  # commit <subject> <path>...
  local msg="$1"; shift
  printf '%s\n' "$msg" > "$msg_file"
  bash .githooks/commit-msg "$msg_file"
  git add -- "$@"
  git -c core.hooksPath=/dev/null commit -q -F "$msg_file"
  echo "  ✓ $msg"
}

commit "feat: add the pure e-mail parsing core" \
  custom_components/email_parcel_tracking/const.py \
  custom_components/email_parcel_tracking/models.py \
  custom_components/email_parcel_tracking/api.py \
  custom_components/email_parcel_tracking/linking.py

commit "feat: add the push coordinator with entry setup" \
  custom_components/email_parcel_tracking/__init__.py \
  custom_components/email_parcel_tracking/coordinator.py \
  custom_components/email_parcel_tracking/entity.py \
  custom_components/email_parcel_tracking/config_flow.py \
  custom_components/email_parcel_tracking/services.py \
  custom_components/email_parcel_tracking/diagnostics.py

commit "feat: add the entity platforms" \
  custom_components/email_parcel_tracking/sensor.py \
  custom_components/email_parcel_tracking/button.py \
  custom_components/email_parcel_tracking/calendar.py

commit "feat: add the integration metadata" \
  custom_components/email_parcel_tracking/manifest.json \
  custom_components/email_parcel_tracking/translations \
  custom_components/email_parcel_tracking/services.yaml \
  custom_components/email_parcel_tracking/icons.json \
  custom_components/email_parcel_tracking/quality_scale.yaml \
  custom_components/email_parcel_tracking/brand

commit "test: add the test suite" tests

commit "chore: add the project tooling" \
  .gitignore .githooks .github scripts LICENSE \
  pyproject.toml mypy.ini ruleset.json requirements.test.txt hacs.json \
  .pre-commit-config.yaml .yamllint .prettierrc.js .prettierignore CLAUDE.md

commit "docs: add the project documentation" README.md docs

git config core.hooksPath .githooks    # commit-msg + prek hooks from here on

echo
echo "Done — $(git rev-list --count HEAD) commits on main; hooks enabled."
if git remote get-url origin >/dev/null 2>&1; then
  echo "Remote already set ($(git remote get-url origin)). Push with:"
  echo "  git push -u origin main"
else
  echo "Next: create the GitHub repo, then:"
  echo "  git remote add origin git@github.com:PineappleEmperor/ha-email-tracking.git"
  echo "  git push -u origin main"
fi
echo "Then apply the GitHub settings: bash scripts/bootstrap_repo.sh \"<description>\""
