"""Payload words of a cosim from its digital.vcd, for a run that never wrote summary.json.

    uv run python verification/mixed_signal/vcd_words.py <run directory> [--write]

cosim_words buffers words.tsv and writes summary.json at the end, so a killed run (a reboot) leaves
neither; digital.vcd, cal.tsv and progress.jsonl are flushed as it goes.  word_valid stays high once the
aligner is aligned, so the words are the changes of word_data.  The stream is training words (0xb5e3), then
payload(n) = 0x1200 + 0x137 n as in cosim_words.cpp.  --write records the result as rescued_summary.json.
"""
import argparse
import json
import re
from pathlib import Path


def payload(n):
    return (0x1200 + n * 0x137) & 0xffff


def word_changes(vcd):
    """(time_fs, value or None) for every change of word_data, and the last complete time in the file."""
    ident, out, t, last = None, [], 0, 0
    with open(vcd) as f:
        for line in f:
            s = line.strip()
            if ident is None:
                m = re.match(r"\$var \w+ +\d+ (\S+) word_data\b", s)
                if m:
                    ident = m[1]
                continue
            if s.startswith("#"):
                try:
                    t = int(s[1:])
                    last = max(last, t)
                except ValueError:
                    pass
            elif s.startswith("b"):
                p = s[1:].split()
                if len(p) == 2 and p[1] == ident:
                    out.append((t, int(p[0], 2) if set(p[0]) <= set("01") else None))
    return out, last


def cal_result(path):
    if not path.exists():
        return None
    for line in path.read_text().splitlines()[1:]:
        f = line.split()
        if len(f) >= 7 and f[2] == "1":
            return dict(cal_done_ns=float(f[0]) * 1e9, codes=dict(zip(("d0", "d1", "e0", "e1"), map(int, f[3:7]))))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    run = Path(a.run)
    ch, last = word_changes(run / "digital.vcd")
    first = next((k for k, (_, v) in enumerate(ch) if k and v != 0xb5e3 and ch[k - 1][1] == 0xb5e3), None)
    words = ch[first:] if first is not None else []
    errors = sum(v != payload(n) for n, (_, v) in enumerate(words))
    r = dict(run=run.name, vcd_end_ns=last / 1e6, calibration=cal_result(run / "cal.tsv"),
             training_seen=any(v == 0xb5e3 for _, v in ch), payload_words=len(words), payload_errors=errors,
             first_payload_ns=words[0][0] / 1e6 if words else None, last_payload_ns=words[-1][0] / 1e6 if words else None)
    print(json.dumps(r, indent=1))
    if a.write:
        (run / "rescued_summary.json").write_text(json.dumps(r, indent=1))


if __name__ == "__main__":
    main()
