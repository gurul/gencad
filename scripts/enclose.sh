#!/usr/bin/env bash
# Set up and drive Enclose (the enclose/ submodule, AGPL-3.0) from gencad.
#
#   scripts/enclose.sh setup             init the submodule, build .venv-enclose with build123d
#   scripts/enclose.sh app [PROJECT]     run the Enclose desktop app (npm run dev), optionally on PROJECT
#   scripts/enclose.sh project ARGS...   scaffold an Enclose project (tools/enclose_project.py ARGS)
#   scripts/enclose.sh update            fetch the submodule and list what upstream moved (no bump)
#
# setup is idempotent. update never moves the pin; bump it by hand with
# `git -C enclose checkout <sha>` and commit the submodule change. See docs/enclose.md.
#
# The repo is found from this script's own location, not the current
# directory, and the script does not cd before `project` runs: relative paths
# given to `project` and `app` resolve against the directory you call it from.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

VENV="$ROOT/.venv-enclose"
VENV_PY="$VENV/bin/python"
# build123d (via OCP / cadquery-ocp) ships wheels for a bounded set of Pythons;
# 3.12 is inside it.
BUILD_PYTHON_VERSION="3.12"
NODE_MIN=22

die() { echo "error: $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
usage: scripts/enclose.sh <subcommand> [args]

  setup             init the enclose submodule; create .venv-enclose (Python 3.12)
                    with build123d installed; print its python path. Idempotent.
  app [PROJECT]     run the Enclose desktop app from enclose/apps/desktop
                    (npm install on first run, then npm run dev [-- PROJECT]).
                    Needs Node 22 or newer. macOS only upstream.
  project ARGS...   python3 tools/enclose_project.py ARGS, run from the current
                    directory (relative paths resolve there); adds
                    --build-python .venv-enclose/bin/python when that exists
                    and ARGS has no --build-python.
  update            fetch the enclose submodule and list upstream commits past
                    the pin. Does not change the pin.
EOF
}

ensure_submodule() {
  if [ ! -f "$ROOT/enclose/kit/enclose.py" ]; then
    echo "initialising enclose submodule"
    git -C "$ROOT" submodule update --init enclose
  fi
  [ -f "$ROOT/enclose/kit/enclose.py" ] || die "enclose/kit/enclose.py missing after git submodule update --init enclose"
}

venv_ready() {
  [ -x "$VENV_PY" ] && "$VENV_PY" -c "import build123d, OCP" >/dev/null 2>&1
}

cmd_setup() {
  ensure_submodule
  if venv_ready; then
    echo "build123d already installed in $VENV"
  elif command -v uv >/dev/null 2>&1; then
    [ -x "$VENV_PY" ] || uv venv --python "$BUILD_PYTHON_VERSION" "$VENV"
    uv pip install --python "$VENV_PY" build123d
  else
    echo "uv not found; falling back to python3 -m venv + pip"
    if [ ! -x "$VENV_PY" ]; then
      PY=""
      for cand in "python$BUILD_PYTHON_VERSION" python3; do
        if command -v "$cand" >/dev/null 2>&1; then PY=$cand; break; fi
      done
      [ -n "$PY" ] || die "no python3 found; install uv (https://docs.astral.sh/uv/) or Python $BUILD_PYTHON_VERSION"
      "$PY" -m venv "$VENV"
    fi
    "$VENV_PY" -m pip install --upgrade pip
    "$VENV_PY" -m pip install build123d
  fi
  venv_ready || die "build123d does not import in $VENV_PY (is its Python one build123d supports? try: rm -rf .venv-enclose && install uv)"
  echo "build123d $("$VENV_PY" -c 'import build123d; print(build123d.__version__)')"
  echo "$VENV_PY"
}

cmd_app() {
  [ $# -le 1 ] || die "app takes at most one PROJECT argument"
  ensure_submodule
  command -v node >/dev/null 2>&1 || die "node not found; Enclose needs Node $NODE_MIN or newer"
  command -v npm >/dev/null 2>&1 || die "npm not found; Enclose needs Node $NODE_MIN or newer with npm"
  local ver major
  ver=$(node -p 'process.versions.node')
  major=${ver%%.*}
  [ "$major" -ge "$NODE_MIN" ] || die "Node $ver found; Enclose needs Node $NODE_MIN or newer"
  [ "$(uname -s)" = "Darwin" ] || echo "warning: Enclose has only been tried on macOS" >&2

  local project=""
  if [ $# -eq 1 ]; then
    [ -e "$1" ] || die "no such project: $1"
    # absolute (from the caller's directory), because npm run dev runs from
    # enclose/apps/desktop
    if [ -d "$1" ]; then
      project=$(cd "$1" && pwd)
    else
      project="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
    fi
  fi

  cd "$ROOT/enclose/apps/desktop"
  if [ ! -d node_modules ]; then
    echo "installing Enclose desktop dependencies (npm install)"
    npm install
  fi
  if [ -n "$project" ]; then
    exec npm run dev -- "$project"
  else
    exec npm run dev
  fi
}

cmd_project() {
  [ -f "$ROOT/tools/enclose_project.py" ] || die "tools/enclose_project.py not found in $ROOT"
  local has_build_python=0 arg
  for arg in "$@"; do
    case "$arg" in
      --build-python|--build-python=*) has_build_python=1 ;;
    esac
  done
  if [ "$has_build_python" -eq 0 ] && [ -x "$VENV_PY" ]; then
    set -- "$@" --build-python "$VENV_PY"
  fi
  exec python3 "$ROOT/tools/enclose_project.py" "$@"
}

cmd_update() {
  ensure_submodule
  local subdir="$ROOT/enclose"
  git -C "$subdir" fetch --no-tags origin main
  local pin
  pin=$(git -C "$subdir" rev-parse --short HEAD)
  echo "enclose pinned at $pin; upstream main is $(git -C "$subdir" rev-parse --short origin/main)"
  local moved
  moved=$(git -C "$subdir" log --oneline HEAD..origin/main)
  if [ -z "$moved" ]; then
    echo "no upstream commits past the pin"
  else
    echo "$moved"
    echo
    echo "pin not changed. To bump: git -C enclose checkout <sha> && git add enclose"
  fi
}

[ $# -ge 1 ] || { usage >&2; exit 2; }
sub=$1
shift
case "$sub" in
  setup)   cmd_setup "$@" ;;
  app)     cmd_app "$@" ;;
  project) cmd_project "$@" ;;
  update)  cmd_update "$@" ;;
  -h|--help|help) usage ;;
  *) echo "unknown subcommand: $sub" >&2; usage >&2; exit 2 ;;
esac
