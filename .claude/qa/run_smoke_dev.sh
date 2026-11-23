#!/usr/bin/env bash
# Run smoke_dev.py against the deployed dev environment (Railway, service `web`).
# Usage: bash .claude/qa/run_smoke_dev.sh <spec.json>
# Prints the QA_RESULT / QA_SUMMARY lines; exits 0 only if every check passed.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: stop path mangling

SPEC_FILE="$1"
HERE="$(cd "$(dirname "$0")" && (pwd -W 2>/dev/null || pwd))"   # pwd -W: Windows path for Windows python
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

# Django bootstrap + SPEC (as a Python literal) + the script itself.
PYTHONIOENCODING=utf-8 python - "$SPEC_FILE" "$HERE/smoke_dev.py" > "$TMP" <<'PY'
import json, sys
spec = json.load(open(sys.argv[1], encoding="utf-8"))
print("import os, sys")
print("sys.path.insert(0, os.getcwd())")
print("os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')")
print("import django")
print("django.setup()")
print("SPEC = " + repr(spec))
print(open(sys.argv[2], encoding="utf-8").read())
PY

# base64 avoids every quoting layer (Windows -> railway ssh -> remote shell).
# railway ssh truncates long command lines (~4 KB), so upload in chunks.
# The whole remote command is ONE string: railway re-parses it remotely.
B64="$(base64 -w0 "$TMP")"
REMOTE=/tmp/qa_smoke_$$
# railway ssh fails intermittently (timeouts): retry each call up to 3 times.
ssh_dev() {
  local out
  for _ in 1 2 3; do
    if out="$(railway ssh --environment dev --service web -- "$1" 2>&1)"; then
      printf '%s
' "$out"; return 0
    fi
    sleep 3
  done
  printf '%s
' "$out" >&2; return 1
}
ssh_dev "rm -f $REMOTE.b64" >/dev/null
for ((i = 0; i < ${#B64}; i += 3000)); do
  ssh_dev "printf %s ${B64:i:3000} >> $REMOTE.b64" >/dev/null
done
OUT="$(ssh_dev "base64 -d $REMOTE.b64 > $REMOTE.py && python $REMOTE.py; rm -f $REMOTE.b64 $REMOTE.py" || true)"
echo "$OUT" | grep -E "^QA_(RESULT|SUMMARY)" || { echo "$OUT" | tail -20; exit 2; }
echo "$OUT" | grep -q '^QA_SUMMARY {"passed": [0-9]*, "failed": 0}'
