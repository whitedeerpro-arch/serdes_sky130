"""Project root plus simulator and PDK locations, read from config/*.toml."""
import subprocess
import tomllib
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@cache
def config(name: str) -> dict:
    return tomllib.loads((ROOT / "config" / name).read_text())


def ngspice() -> str:
    return config("tools.toml")["simulators"]["ngspice"]["executable"]


def model_library() -> Path:
    """SKY130 ngspice corner library; select the corner with `.lib "<path>" tt`."""
    pdk = config("pdk.toml")["pdk"]
    return Path(pdk["path"]) / pdk["model_library"]


def pdk_installation_id() -> str:
    return config("pdk.toml")["pdk"]["installation_id"]


def git_revision() -> str | None:
    """Commit of the working tree, suffixed with -dirty when there are local edits."""
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return rev + ("-dirty" if dirty else "")
