#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=scripts/test/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

cd "$REPO_ROOT"

section "Documentation checks"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && git lfs version >/dev/null 2>&1; then
  if git lfs ls-files --name-only | grep -q '^docs/public/hero/'; then
    git lfs pull --include="docs/public/hero/**" --exclude=""
  fi
fi
npm --prefix docs run check
