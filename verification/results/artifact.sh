#!/usr/bin/env bash
# Locate/read/restore an archived result without changing its historical identity.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
mode=${1:-help}
if [[ "$mode" == help || $# -ne 2 ]]; then
    echo 'Usage: verification/results/artifact.sh locate|cat|verify|restore results/ORIGINAL_PATH'
    [[ "$mode" == help ]] && exit 0 || exit 2
fi
artifact=$2
[[ "$artifact" == "$root/"* ]] && artifact=${artifact#"$root/"}
if [[ "$artifact" != results/* || "$artifact" =~ (^|/)\.\.?(/|$) ]]; then
    echo 'Expected a canonical path below results/' >&2; exit 2
fi
case "$mode" in locate|cat|verify|restore) ;; *) echo 'Unknown operation' >&2; exit 2;; esac
index="$root/results/catalog/artifacts.tsv"
if [[ -f "$root/$artifact" ]]; then
    case "$mode" in
        cat) cat -- "$root/$artifact";;
        verify)
            actual=$(sha256sum -- "$root/$artifact")
            expected=''
            if [[ -f "$index" ]]; then
                expected=$(awk -F '\t' -v target="$artifact" 'NR>1 && $1==target {print $5; exit}' "$index")
            fi
            if [[ -n "$expected" ]]; then
                [[ "${actual%% *}" == "$expected" ]] || { echo 'SHA256 mismatch' >&2; exit 1; }
                printf 'PASS %s\n' "$artifact"
            else
                printf '%s\n' "$actual"
            fi;;
        *) printf '%s\n' "$root/$artifact";;
    esac
    exit 0
fi
[[ -f "$index" ]] || { echo 'Archive catalog is unavailable' >&2; exit 1; }
record=$(awk -F '\t' -v target="$artifact" 'NR>1 && $1==target {print; exit}' "$index")
[[ -n "$record" ]] || { echo "No live or archived artifact: $artifact" >&2; exit 1; }
IFS=$'\t' read -r original archive member original_bytes digest <<< "$record"
case "$mode" in
    locate) printf 'archive=%s\nmember=%s\nsha256=%s\n' "$root/$archive" "$member" "$digest";;
    cat) tar -xOf "$root/$archive" -- "$member";;
    verify)
        actual=$(tar -xOf "$root/$archive" -- "$member" | sha256sum)
        [[ "${actual%% *}" == "$digest" ]] || { echo 'SHA256 mismatch' >&2; exit 1; }
        printf 'PASS %s\n' "$artifact";;
    restore)
        mkdir -p -- "$(dirname -- "$root/$artifact")"
        temporary=$(mktemp "$(dirname -- "$root/$artifact")/.restore.XXXXXXXX")
        trap 'rm -f -- "$temporary"' EXIT
        tar -xOf "$root/$archive" -- "$member" > "$temporary"
        actual=$(sha256sum -- "$temporary")
        [[ "${actual%% *}" == "$digest" ]] || { echo 'SHA256 mismatch' >&2; exit 1; }
        mv -n -- "$temporary" "$root/$artifact"
        printf 'Restored %s\n' "$artifact";;
esac
