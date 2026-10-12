# Vendoring text-to-cad

`text-to-cad/` is vendored from
[earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad)
(release 0.4.20, upstream commit `02ecd59d`, MIT — see its bundled `LICENSE`).
Full credit to [@earthtojake](https://github.com/earthtojake) and the
text-to-cad contributors.

## What it provides

A library of agent skills for CAD, CAE and CAM: CAD generation with
STEP/STL/3MF export, a local CAD Viewer, DXF drawings, URDF/SRDF/SDF robot
descriptions, G-code slicing, off-the-shelf STEP part sourcing, and more. It
complements the MCP loop at gencad's core: gencad closes the
build/render/inspect cycle, text-to-cad supplies the surrounding fabrication
and hand-off workflows.

## Local changes

Local changes on top of upstream are marked with `gencad patch` comments.
Currently:

- The Viewer header's community links are hidden.
- Upstream demo GIF LFS assets and LFS config were dropped in vendoring.

Local patches live in the idempotent `scripts/apply-gencad-patches.sh` —
add future patches to vendored files there, not inline.

## Pulling upstream

Upstream additions keep flowing in as review PRs:
`scripts/pull-text-to-cad.sh` diffs upstream `main` against the commit
recorded in `text-to-cad/.upstream-commit` and opens one; a weekly GitHub
Action runs it automatically. The pull wraps the patch script as
revert → apply upstream → re-apply, so local patches never conflict with
upstream churn.

The pull fails without committing when the upstream diff does not apply
cleanly (3-way conflicts excepted, which land in the PR for review) or
when the local patches cannot be re-applied. If PR creation fails, the
script deletes the branch it pushed and exits non-zero. The weekly Action
needs Settings → Actions → General → "Allow GitHub Actions to create and
approve pull requests" enabled to open the PR; every scheduled run from
2026-08-24 to 2026-10-05 failed on that setting.

**Open as of 2026-10-11:** upstream `3eb1f9b8` ("cadgen 0.5.0") moved the
Viewer to `apps/` and deleted
`skills/cad-viewer/scripts/viewer/dist/index.html`, the file the local
patch edits. Until the patch is ported to the new location (or dropped),
the pull stops at the re-apply step and commits nothing.
