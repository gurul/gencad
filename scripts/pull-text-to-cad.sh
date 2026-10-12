#!/usr/bin/env bash
# Pull upstream earthtojake/text-to-cad changes into the vendored text-to-cad/
# tree on a branch and open a PR for review — local gencad patches are
# preserved via 3-way apply; conflicts land in the PR marked for manual fixup.
#
# Fails (non-zero) rather than commit a .upstream-commit bump without the
# upstream diff, and never leaves a pushed branch behind without its PR.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

UPSTREAM_URL="https://github.com/earthtojake/text-to-cad.git"
REC="text-to-cad/.upstream-commit"
PR_SETTING='Settings > Actions > General > "Allow GitHub Actions to create and approve pull requests"'

die() { echo "error: $*" >&2; exit 1; }

# git apply --3way needs index == worktree for every file it touches, and the
# commit below stages all of text-to-cad/ — start from a clean tree.
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "working tree has uncommitted changes — commit or stash them first"
fi

OLD=$(cat "$REC")
git fetch --no-tags "$UPSTREAM_URL" main
NEW=$(git rev-parse FETCH_HEAD)

if [ "$OLD" = "$NEW" ]; then
  echo "vendored text-to-cad is up to date at ${OLD:0:8}"
  exit 0
fi

BRANCH="vendor/text-to-cad-${NEW:0:8}"
if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
  echo "update branch $BRANCH already pushed — merge or close its PR first"
  exit 0
fi

START=$(git rev-parse --abbrev-ref HEAD)
git switch -c "$BRANCH"

# Undo the local branch so a failed run leaves the checkout as it found it.
abort_local() {
  echo "error: $*" >&2
  git reset -q --hard
  git switch -q "$START"
  git branch -q -D "$BRANCH"
  exit 1
}

# Lift gencad's local patches so the upstream diff applies onto a pristine
# tree — they are re-applied below, which is what keeps them from ever
# conflicting with upstream churn around the same lines. Stage the revert:
# --3way applies to the index too and rejects the whole patch when any file
# it touches differs between index and worktree.
bash scripts/apply-gencad-patches.sh --revert
git add -A text-to-cad

# Excludes mirror what vendoring dropped (demo LFS assets, LFS config).
# Patterns appear with and without the text-to-cad/ prefix because git-apply
# matches them against the post---directory pathname on some versions.
APPLY_RC=0
git diff --binary "$OLD" "$NEW" | git apply --directory=text-to-cad --3way \
    --exclude='assets/*' --exclude='text-to-cad/assets/*' \
    --exclude='.lfsconfig' --exclude='text-to-cad/.lfsconfig' \
    --exclude='.gitattributes' --exclude='text-to-cad/.gitattributes' \
  || APPLY_RC=$?

CONFLICTS=0
if [ "$APPLY_RC" != 0 ]; then
  # Unmerged paths mean --3way applied the diff and left conflict markers for
  # the PR. Anything else means it applied nothing — committing now would
  # bump .upstream-commit without the upstream changes.
  if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
    CONFLICTS=1
  else
    abort_local "git apply failed (exit $APPLY_RC) without conflicts;" \
      "upstream diff ${OLD:0:8}..${NEW:0:8} was not applied — nothing committed"
  fi
fi

bash scripts/apply-gencad-patches.sh \
  || abort_local "could not re-apply gencad patches onto ${NEW:0:8} — upstream" \
       "may have moved a patched file; port scripts/apply-gencad-patches.sh"
echo "$NEW" > "$REC"
git add -A text-to-cad
git commit -m "vendor: pull text-to-cad ${OLD:0:8}..${NEW:0:8}"
git push -u origin "$BRANCH"

BODY="Upstream changes: https://github.com/earthtojake/text-to-cad/compare/${OLD:0:8}...${NEW:0:8}"
if [ "$CONFLICTS" = 1 ]; then
  BODY="$BODY

**3-way apply reported conflicts** — search the diff for conflict markers
(<<<<<<<) and resolve before merging. Local gencad patches are marked with
\`gencad patch\` comments."
fi
if ! gh pr create --base main --head "$BRANCH" \
    --title "vendor: pull text-to-cad ${NEW:0:8}" --body "$BODY"; then
  echo "error: gh pr create failed — deleting pushed branch $BRANCH so the" \
    "next run retries instead of skipping it" >&2
  git push origin --delete "$BRANCH" \
    || echo "error: could not delete origin/$BRANCH — delete it by hand" >&2
  die "if this ran in GitHub Actions, enable $PR_SETTING for this repository"
fi
