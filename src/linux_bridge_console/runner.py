"""Linux Bridge Console: GitHub job runner (manual execution, v0.1)."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

HOME = Path.home() / ".local" / "share" / "linux-bridge-console"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

def run(args, cwd=None, check=True, capture=True):
    return subprocess.run(args, cwd=cwd, text=True, check=check,
                          capture_output=capture)

def ensure_identity():
    for executable in ("git", "gh", "bash"):
        if not shutil.which(executable):
            raise RuntimeError(f"{executable} is required")
    run(["gh", "auth", "status"])

def repo_dir(slug):
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", slug):
        raise ValueError("Invalid repository name")
    return HOME / "repos" / slug.replace("/", "__")

def sync(slug, branch):
    ensure_identity()
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or ".." in branch:
        raise ValueError("Invalid branch")
    target = repo_dir(slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not (target / ".git").exists():
        run(["gh", "repo", "clone", slug, str(target), "--", "--branch", branch])
    # Protect local modifications and unrelated work from being overwritten.
    if run(["git", "status", "--porcelain"], cwd=target).stdout.strip():
        raise RuntimeError("Local workspace changes detected; refusing to pull")
    run(["git", "pull", "--ff-only", "origin", branch], cwd=target)
    return target

def inspect(root):
    path = root / "workspace" / "current.json"
    if not path.exists():
        raise RuntimeError("No workspace/current.json in repository")
    job = json.loads(path.read_text())
    jid, script = job.get("id"), job.get("script")
    if not isinstance(jid, str) or not ID_RE.fullmatch(jid):
        raise ValueError("Invalid job ID")
    if not isinstance(script, str) or not ID_RE.fullmatch(script):
        raise ValueError("Invalid script name")
    if not script.endswith(".sh"):
        raise ValueError("v0.1 accepts .sh jobs only")
    script_path = root / "workspace" / "jobs" / script
    if not script_path.is_file():
        raise FileNotFoundError(script_path)
    return job, script_path

def execute(root, job, script, timeout):
    jid = job["id"]
    result_dir = root / "workspace" / "results" / jid
    if result_dir.exists():
        raise RuntimeError("Results for this job already exist; refusing duplicate execution")
    result_dir.mkdir(parents=True)
    started = dt.datetime.now(dt.timezone.utc)
    code = None
    status = "failed"
    with (result_dir / "stdout.log").open("w") as out, (result_dir / "stderr.log").open("w") as err:
        proc = subprocess.Popen(["bash", str(script)], cwd=root, stdout=out,
                                stderr=err, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
            status = "success" if code == 0 else "failed"
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            code = proc.returncode
            status = "timeout"
        except KeyboardInterrupt:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait()
            code = proc.returncode
            status = "cancelled"
    finished = dt.datetime.now(dt.timezone.utc)
    result = {
        "jobId": jid,
        "description": job.get("description", ""),
        "status": status,
        "exitCode": code,
        "startedAt": started.isoformat(),
        "finishedAt": finished.isoformat(),
        "hostname": os.uname().nodename,
        "runner": "linux-bridge-console/0.1",
    }
    (result_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result, result_dir

def publish(root, result_dir, branch):
    # Stage only the three result files. Git identity is deliberately local.
    files = [str(p.relative_to(root)) for p in
             (result_dir / "result.json", result_dir / "stdout.log",
              result_dir / "stderr.log")]
    run(["git", "add", "--", *files], cwd=root)
    run(["git", "-c", "user.name=Linux Bridge Console",
         "-c", "user.email=linux-bridge-console@localhost",
         "commit", "-m", f"Record job result: {result_dir.name}"], cwd=root)
    run(["git", "push", "origin", f"HEAD:{branch}"], cwd=root)

def main():
    parser = argparse.ArgumentParser(description="Linux Bridge Console (v0.1)")
    parser.add_argument("--repo", required=True, help="owner/repository")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--run", action="store_true", help="Execute job after confirmation")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    try:
        root = sync(args.repo, args.branch)
        job, script = inspect(root)
        print(f"Repository: {args.repo} ({args.branch})")
        print(f"Job: {job['id']}")
        print(f"Description: {job.get('description', '')}")
        print(f"Script: {script.name}")
        print(f"SHA256: {__import__('hashlib').sha256(script.read_bytes()).hexdigest()}")
        if not args.run:
            print("Read-only inspection complete. Add --run to execute.")
            return 0
        answer = input("Execute this Bash job and publish results? Type YES: ")
        if answer != "YES":
            print("Cancelled")
            return 1
        result, result_dir = execute(root, job, script, args.timeout)
        try:
            publish(root, result_dir, args.branch)
            print(f"Result uploaded: {result['status']} (exit {result['exitCode']})")
        except Exception:
            print(f"Upload failed. Local results preserved at {result_dir}", file=sys.stderr)
            raise
        return 0 if result["status"] == "success" else 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
