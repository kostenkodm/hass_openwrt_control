#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$task_root"
work/venv-linux/bin/python -m tools.create_lab
exec work/venv-linux/bin/python -m simulator.server
