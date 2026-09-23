#!/usr/bin/env bash
# Pre-submission check from a fresh clone: venv, install, eval, submission diff, tests.
#
#   tools/final_check.sh              # clones this repo's committed HEAD (what you will push)
#   tools/final_check.sh <git-url>    # clones that URL instead, e.g. the GitHub remote
#
# Prints one PASS/FAIL line per step; exits 1 if any step fails.
# OPENAI_API_KEY is unset for every step so the run is deterministic.
# The temp dir is removed on success and kept (with step logs) on failure.

set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="${1:-$REPO_ROOT}"
TMP_BASE="${TMPDIR:-/tmp}"
WORK="$(mktemp -d "${TMP_BASE%/}/final_check.XXXXXX")"
CLONE="$WORK/repo"
LOGS="$WORK/logs"
mkdir -p "$LOGS"
FAILED=0

# step <name> <command...>: run in the clone, log output, print PASS/FAIL.
step() {
    local name="$1"; shift
    local log="$LOGS/$name.log"
    if (cd "$CLONE" && env -u OPENAI_API_KEY "$@") >"$log" 2>&1; then
        echo "PASS  $name"
        return 0
    fi
    echo "FAIL  $name  (log: $log)"
    tail -n 5 "$log" | sed 's/^/      /'
    FAILED=1
    return 1
}

# fatal: later steps cannot run without this one.
abort() {
    echo "FAIL  aborted, remaining steps skipped; logs in $LOGS"
    exit 1
}

echo "source: $SOURCE"
echo "python: $(command -v python3) ($(python3 --version 2>&1))"

if git clone --quiet "$SOURCE" "$CLONE" >"$LOGS/clone.log" 2>&1; then
    echo "PASS  clone  ($(git -C "$CLONE" log -1 --format='%h %s'))"
else
    echo "FAIL  clone  (log: $LOGS/clone.log)"
    abort
fi

PY="$CLONE/.venv/bin/python"
step venv python3 -m venv .venv || abort
step pip_install "$PY" -m pip install --quiet -r requirements.txt || abort

# local_eval.py catches agent exceptions itself (prints "Агент упал" and goes on),
# so these steps check its output, not only the exit code.
eval_one() {
    "$PY" local_eval.py > eval.out 2>&1; local rc=$?
    cat eval.out
    grep -q "Статус: PASS" eval.out && ! grep -q "Агент упал" eval.out; local ok=$?
    rm -f eval.out
    [ "$rc" -eq 0 ] && [ "$ok" -eq 0 ]
}
eval_runs() {
    "$PY" local_eval.py --runs 10 > eval.out 2>&1; local rc=$?
    cat eval.out
    grep -q "прогонов в плюс" eval.out && ! grep -q "Агент упал" eval.out; local ok=$?
    rm -f eval.out
    [ "$rc" -eq 0 ] && [ "$ok" -eq 0 ]
}
export -f eval_one eval_runs
export PY

step local_eval bash -c eval_one
step local_eval_runs10 bash -c eval_runs
step make_submission "$PY" make_submission.py
step submission_diff git diff --exit-code -- submission.csv
step pytest "$PY" -m pytest tests -q

if [ "$FAILED" -eq 0 ]; then
    echo "PASS  all steps"
    rm -rf "$WORK"
    exit 0
fi
echo "FAIL  one or more steps failed; clone and logs kept in $WORK"
exit 1
