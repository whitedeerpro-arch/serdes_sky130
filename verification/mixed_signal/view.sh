#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
waves="$root/results/acceptance/20261029-rx-functional/waveforms"
# The desktop's VS Code GTK3 environment conflicts with this GTKWave GTK2 build.
exec env -u GTK_PATH GTK_MODULES= GTK2_RC_FILES=/dev/null gtkwave \
  "$waves/rx_mixed.fst" "$waves/rx_mixed.gtkw" \
  --script "$root/verification/mixed_signal/view.tcl"
