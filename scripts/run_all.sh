#!/usr/bin/env bash
# The whole pipeline.   scripts/run_all.sh [--skip-download] [--fast]
# download -> fair value -> bound -> quoter -> monitor -> figures -> summary -> README -> tests
set -euo pipefail
cd "$(dirname "$0")/.."
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-2}"
PY="${PYTHON:-python}"
FAST=""
SKIP=""
for a in "$@"; do
  case "$a" in
    --fast) FAST="--fast" ;;
    --skip-download) SKIP=1 ;;
  esac
done
if [ -z "$SKIP" ]; then
  $PY scripts/download.py
fi
$PY scripts/build_fair.py
$PY scripts/run_bound.py
$PY scripts/run_quoter.py $FAST
$PY scripts/run_monitor.py $FAST
$PY scripts/make_figures.py
$PY scripts/summarize.py
$PY scripts/readme.py
$PY -m pytest -q
