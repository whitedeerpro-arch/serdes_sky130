#!/bin/bash
# Keeps /home from filling up: when it has less than MIN_GB free, moves result waveforms to /opt
# (verification/maintenance/waveform_archive.py archive; symlinks stay, live ngspice directories are skipped).
# Runs from cron every hour (survives reboots):
#   17 * * * * /home/host/Desktop/workspace/simple_serdes_fork1/verification/maintenance/disk_guard.sh
# One line per action in results/maintenance/disk_guard.log.  Remove the crontab line to stop it.
MIN_GB=${MIN_GB:-15}
cd "$(dirname "$0")/../.." || exit 1
LOG=results/maintenance/disk_guard.log
mkdir -p "$(dirname "$LOG")"
exec 9> /tmp/serdes_disk_guard.lock
flock -n 9 || exit 0
free_gb=$(df --output=avail -BG /home | tail -1 | tr -dc '0-9')
[ "$free_gb" -ge "$MIN_GB" ] && exit 0
opt_gb=$(df --output=avail -BG /opt | tail -1 | tr -dc '0-9')
if [ "$opt_gb" -lt 10 ]; then
  echo "$(date '+%F %T') /home ${free_gb}G free, /opt only ${opt_gb}G free: NOT archiving, needs a decision" >> "$LOG"
  exit 1
fi
out=$(/home/host/.local/bin/uv run python verification/maintenance/waveform_archive.py archive 2>&1 | tail -1)
echo "$(date '+%F %T') /home ${free_gb}G free -> archive: $out; now $(df --output=avail -BG /home | tail -1 | tr -dc '0-9')G" >> "$LOG"
