"""Read-only status report of Claude's long runs, for resuming after an interruption.

    uv run python verification/maintenance/run_status.py            # one report
    setsid nohup verification/maintenance/run_status.sh >/dev/null 2>&1 &   # every 30 min (restart after a reboot)

Writes results/maintenance/claude_runs/status.md (latest, overwritten) and appends one line per report to
status_history.log.  Content: boot time and the last health line; every running ngspice (campaign directory, elapsed);
per log in results/maintenance/claude_runs: finished (the results/ line) or its last lines; per known campaign the
progress counters (runs with a clean execution.json, MC chunks with rows); git HEAD and the working-tree summary.
Simulates and changes nothing.
"""
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "results/maintenance/claude_runs"
HEALTH = ROOT / "results/maintenance/vm_health/health.log"


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=ROOT, timeout=60).stdout.strip()
    except subprocess.TimeoutExpired:
        return "(timeout)"


def campaign_of(cwd):
    """The timestamped campaign directory above an ngspice working directory."""
    import re
    parts = Path(cwd).parts
    for i in range(len(parts) - 1, -1, -1):
        if re.match(r"\d{8}T\d{6}", parts[i]):
            return Path(*parts[: i + 1])
    return None


def counters(camp):
    clean = mc = 0
    for e in camp.rglob("execution.json"):
        try:
            if json.loads(e.read_text()).get("exit_code") == 0:
                clean += 1
        except (OSError, ValueError):
            pass
    mc = sum(1 for _ in camp.rglob("mc.tsv"))
    return f"{camp.relative_to(ROOT)}: {clean} runs/chunks with exit 0, {mc} MC chunks with rows"


def ngspice():
    out = []
    for pid in sh("pgrep -x ngspice").split():
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            continue
        et = sh(f"ps -o etime= -p {pid}")
        rss = sh(f"awk '/VmRSS/ {{print int($2/1024)}}' /proc/{pid}/status")
        out.append(f"| {cwd.split('/results/')[-1]} | {et} | {rss} MB |")
    return out


def campaign_progress(log_text):
    """Counters for the campaign a log names (results/... line or a campaign path in it)."""
    import re
    m = re.findall(r"results/[\w/.\-]+", log_text)
    if not m:
        return None
    camp = ROOT / m[-1].rstrip("/")
    while camp.name and not camp.exists():
        camp = camp.parent
    if not camp.exists() or camp == ROOT / "results":
        return None
    clean = mc = 0
    for e in camp.rglob("execution.json"):
        try:
            if json.loads(e.read_text()).get("exit_code") == 0:
                clean += 1
        except (OSError, ValueError):
            pass
    for t in camp.rglob("mc.tsv"):
        mc += 1
    return f"{camp.relative_to(ROOT)}: {clean} runs/chunks with exit 0, {mc} MC chunks with rows"


def main():
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"# Claude run status {now}", "", f"boot {sh('uptime -s')}; health: {sh(f'tail -1 {HEALTH}') if HEALTH.exists() else 'no log'}", ""]
    ng = ngspice()
    lines += [f"## ngspice running ({len(ng)})", "", "| campaign dir | elapsed | RSS |", "|---|---|---|"] + ng + [""]
    camps = []
    for pid in sh("pgrep -x ngspice").split():
        try:
            c = campaign_of(os.readlink(f"/proc/{pid}/cwd"))
        except OSError:
            c = None
        if c and c not in camps:
            camps.append(c)
    if camps:
        lines += ["## Progress of the running campaigns", ""] + [f"- {counters(c)}" for c in camps] + [""]
    lines += ["## Logs (results/maintenance/claude_runs)", ""]
    summary = []
    for log in sorted(RUNS.glob("*.log")):
        if log.name == "status_history.log":
            continue
        txt = log.read_text(errors="replace")
        tail = [l for l in txt.splitlines() if l.strip()][-6:]
        finished = any(l.startswith("results/") for l in tail)
        failed = any(k in txt for k in ("Traceback", "SmokeTestFailed", "RuntimeError"))
        state = "FAILED" if failed else ("finished" if finished else "running / no output yet")
        summary.append(f"{log.stem}={state}")
        lines += [f"### {log.stem}: {state}", ""]
        prog = campaign_progress(txt) if not finished else None
        if prog:
            lines += [f"progress: {prog}", ""]
        if tail:
            lines += ["```"] + [l[:200] for l in tail] + ["```", ""]
    lines += ["## Repository", "", f"HEAD {sh('git log --oneline -1')}", "", "```", sh("git status --short | head -40"), "```", ""]
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / "status.md").write_text("\n".join(lines))
    with open(RUNS / "status_history.log", "a") as f:
        f.write(f"{now} ngspice {len(ng)} | " + " ".join(summary) + f" | HEAD {sh('git rev-parse --short HEAD')}\n")


if __name__ == "__main__":
    main()
