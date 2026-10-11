#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$task_root"
mkdir -p work/tmp
export TMPDIR="$task_root/work/tmp"
work/venv-linux/bin/python -m ruff check custom_components simulator tools tests
work/venv-linux/bin/python -m pytest -q --capture=sys --basetemp=work/pytest --junitxml=work/test-results.xml | tee work/test-run.log
