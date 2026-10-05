"""Paths and helpers shared by every step: git, gh, dbt, and JSON files."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()                                   # always run from the repo root
STATE = ROOT / ".four_eyes"                         # local "warehouse" and production artifacts
DUCKDB = STATE / "warehouse.duckdb"
PROD = STATE / "prod"                               # manifest + run_results of the last production build
EVIDENCE = ROOT / "evidence"                        # one bundle per PR head commit
WORKTREES = Path(tempfile.gettempdir()) / "four-eyes"   # outside the repo, so agents can't wander into evidence/
REPO = "repos/{owner}/{repo}"                       # gh fills in owner/repo from the git remote
DBT = Path(sys.executable).parent / "dbt"           # this venv's dbt-core, not whatever dbt is on PATH


def git(*args, cwd=ROOT):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def gh(path, method="GET", body=None):
    """Call the GitHub REST API through the gh CLI, which handles auth."""
    cmd = ["gh", "api", "-X", method, path] + (["--input", "-"] if body is not None else [])
    out = subprocess.run(cmd, input=json.dumps(body) if body is not None else None,
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out) if out.strip() else None


def dbt(*args, cwd, schema="ci"):
    """Run dbt against the local DuckDB warehouse. Returns True if every node and test passed."""
    env = {**os.environ, "DUCKDB_PATH": str(DUCKDB), "CI_SCHEMA": schema, "DBT_PARTIAL_PARSE": "false"}
    result = subprocess.run([str(DBT), *args, "--profiles-dir", str(ROOT)], cwd=cwd, env=env)
    return result.returncode == 0


def worktree(ref, name):
    """Fresh, detached checkout of `ref` in its own folder. Used for PR builds and the checker's workspace."""
    path = WORKTREES / name
    shutil.rmtree(path, ignore_errors=True)
    git("worktree", "prune")
    git("worktree", "add", "--detach", "--force", str(path), ref)
    return path


def from_main(path):
    """Read a control-plane file from main, so a PR can never change the rules it's judged by."""
    return git("show", f"origin/main:{path}")


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))
