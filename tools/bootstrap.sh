#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$task_root"
mkdir -p work/pip-cache work/tmp work/cache
export PIP_CACHE_DIR="$task_root/work/pip-cache"
export TMPDIR="$task_root/work/tmp"
export XDG_CACHE_HOME="$task_root/work/cache"
python3 -m venv --without-pip work/venv-linux
if ! work/venv-linux/bin/python -m pip --version >/dev/null 2>&1; then
  curl --fail --silent --show-error https://bootstrap.pypa.io/get-pip.py -o work/get-pip.py
  work/venv-linux/bin/python work/get-pip.py --no-compile
fi
work/venv-linux/bin/python -m pip install --no-compile -r requirements-lock.txt
