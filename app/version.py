"""App version (from the installed package) and build commit, shown in the page footer."""

import os
import subprocess
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

APP_NAME = "Proud Ledger"


@lru_cache
def app_version() -> str:
    try:
        return version("proud-ledger")
    except PackageNotFoundError:
        return "dev"


@lru_cache
def app_commit() -> str | None:
    """Short git commit: APP_COMMIT (set at docker build time) or the local checkout."""
    commit = os.environ.get("APP_COMMIT", "").strip()
    if commit:
        return commit[:12]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True, text=True, timeout=2, check=True,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
