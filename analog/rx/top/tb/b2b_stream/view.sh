#!/usr/bin/env bash
# Open the back-to-back stream view in GTKWave (latest campaign, or the one given).
#   analog/rx/top/tb/b2b_stream/view.sh [results/analog/rx/top/b2b_stream/<campaign>]
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../../.." && pwd)
cd "$root"
exec uv run python analog/rx/top/tb/b2b_stream/run.py view "${1:-latest}" --open
