#!/usr/bin/env bash
# Move the project's results/ onto the /opt partition and bind-mount it back at the same path.
#
#   sudo bash verification/maintenance/results_on_opt.sh
#
# Why: the 200 GB disk is cut into fixed partitions; /home (this project) has 47 GB, /opt has 76 GB mostly free.
# A bind mount, unlike a symlink, keeps Path.resolve() under the project root, so every recorded path
# (tb.cir includes, boundary records, relative_to(ROOT)) stays valid.
#
# Safe order: refuses while ngspice runs; copies with rsync; a checksum pass must find no difference before
# anything is touched; the old tree is renamed, the bind mount and an fstab entry are added, the mounted tree is
# compared with the old one again, and only then the old copy is removed.  Re-running after success does nothing.
set -euo pipefail
PROJ=/home/host/Desktop/workspace/simple_serdes_fork1
SRC=$PROJ/results
DST=/opt/serdes/results
OWNER=host
FSTAB_LINE="$DST $SRC none bind,nofail,x-systemd.requires-mounts-for=/opt,x-systemd.requires-mounts-for=/home 0 0"

[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
if mountpoint -q "$SRC"; then echo "$SRC is already a mount point; nothing to do"; findmnt "$SRC"; exit 0; fi
if pgrep -x ngspice >/dev/null; then echo "ngspice is running; stop the simulations first"; exit 1; fi
[ -d "$SRC" ] || { echo "$SRC missing"; exit 1; }
[ ! -e "$SRC.moved" ] || { echo "$SRC.moved exists from an earlier attempt; inspect it first"; exit 1; }
need=$(du -sb "$SRC" | cut -f1); free=$(df -B1 --output=avail /opt | tail -1)
[ "$need" -lt $((free - 5000000000)) ] || { echo "/opt has too little space: need $need, free $free"; exit 1; }

echo "1/5 copy $(du -sh "$SRC" | cut -f1) to $DST"
mkdir -p "$DST"; chown "$OWNER:$OWNER" /opt/serdes "$DST"
rsync -aH "$SRC/" "$DST/"
echo "2/5 checksum comparison"
diff=$(rsync -aHc --dry-run --itemize-changes "$SRC/" "$DST/")
[ -z "$diff" ] || { echo "copy differs, nothing removed:"; echo "$diff" | head; exit 1; }

echo "3/5 swap in the bind mount"
mv "$SRC" "$SRC.moved"
mkdir "$SRC"; chown "$OWNER:$OWNER" "$SRC"
grep -qF " $SRC " /etc/fstab || { cp /etc/fstab /etc/fstab.before_results_bind; echo "$FSTAB_LINE" >> /etc/fstab; }
systemctl daemon-reload
mount "$SRC"
mountpoint -q "$SRC" || { echo "bind mount failed; restoring"; rmdir "$SRC"; mv "$SRC.moved" "$SRC"; exit 1; }

echo "4/5 compare mounted tree with the old one"
diff=$(rsync -aH --dry-run --itemize-changes "$SRC.moved/" "$SRC/")
[ -z "$diff" ] || { echo "mounted tree differs; old tree kept at $SRC.moved:"; echo "$diff" | head; exit 1; }

echo "5/5 remove the old copy on /home"
rm -rf "$SRC.moved"
findmnt "$SRC"
df -h /home /opt
