#!/usr/bin/env bash
# Pull upstream earthtojake/text-to-cad changes into the vendored text-to-cad/
# tree on a branch and open a PR for review — local gencad patches are
# preserved via 3-way apply; conflicts land in the PR marked for manual fixup.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

UPSTREAM_URL="https://github.com/earthtojake/text-to-cad.git"
REC="text-to-cad/.upstream-commit"

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

git switch -c "$BRANCH"

# Lift gencad's local patches so the upstream diff applies onto a pristine
# tree — they are re-applied below, which is what keeps them from ever
# conflicting with upstream churn around the same lines.
bash scripts/apply-gencad-patches.sh --revert

# Excludes mirror what vendoring dropped (demo LFS assets, LFS config).
# Patterns appear with and without the text-to-cad/ prefix because git-apply
# matches them against the post---directory pathname on some versions.
CONFLICTS=0
git diff --binary "$OLD" "$NEW" | git apply --directory=text-to-cad --3way \
    --exclude='assets/*' --exclude='text-to-cad/assets/*' \
    --exclude='.lfsconfig' --exclude='text-to-cad/.lfsconfig' \
    --exclude='.gitattributes' --exclude='text-to-cad/.gitattributes' \
  || CONFLICTS=1

bash scripts/apply-gencad-patches.sh
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
gh pr create --base main --head "$BRANCH" \
  --title "vendor: pull text-to-cad ${NEW:0:8}" --body "$BODY"
