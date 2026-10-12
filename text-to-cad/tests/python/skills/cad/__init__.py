from tests.python.support.paths import add_repo_path

add_repo_path("skills/cad/scripts")
# cadgen is the installed distribution, not a vendored tree under the skill. test-python.sh
# puts the repo's own packages/cadgen/src on the path so a checkout tests its own source.
