"""Long-running Linux Bridge worker. Execution is opt-in, never implicit."""
import argparse
import datetime as datetime
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback

from runner import HOME, execute, inspect, publish, sync

STATE = HOME / "worker-state.json"
RUNNING = True

def stop(signum, frame):
    global RUNNING
    RUNNING = False

def store(**values):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if STATE.exists():
        try:
            data = json.loads(STATE.read_text())
        except (OSError, ValueError):
            pass
    data.update(values, checkedAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
    temp = STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(temp, STATE)

def tick(repo, branch, auto_run, timeout):
    store(service="running", repository=repo, branch=branch, autoRun=auto_run,
          phase="syncing", lastError="")
    root = sync(repo, branch)
    job, script = inspect(root)
    jid = job["id"]
    result_file = root / "workspace" / "results" / jid / "result.json"
    if result_file.exists():
        result = json.loads(result_file.read_text())
        store(phase="completed", jobId=jid, description=job.get("description", ""),
              lastResult=result.get("status", "unknown"))
        return
    if not auto_run:
        store(phase="pending", jobId=jid, description=job.get("description", ""),
              lastResult="Awaiting manual approval (auto-run disabled)")
        return
    # Guard against replay: create a persistent marker before executing,
    # so a crash never silently runs a potentially destructive job again.
    marker_dir = HOME / "claims"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / (repo.replace("/", "__") + "__" + jid + ".json")
    if marker.exists():
        store(phase="needs-review", jobId=jid,
              lastError="Local claim exists; refusing replay. Review job and results.")
        return
    claim = {"jobId": jid, "repository": repo, "claimedAt": time.time()}
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(claim, stream)
    store(phase="running-job", jobId=jid, description=job.get("description", ""))
    result, output_dir = execute(root, job, script, timeout)
    store(phase="uploading", lastResult=result["status"])
    publish(root, output_dir, branch)
    store(phase="completed", lastResult=result["status"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="Pcattache30/Linux-Bridge-Console")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--auto-run", action="store_true",
                        help="Explicitly allow unattended execution of repository scripts")
    args = parser.parse_args()
    if args.interval < 5 or args.timeout < 1:
        parser.error("Interval must be >= 5; timeout must be > 0")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    store(service="starting", autoRun=args.auto_run, phase="starting")
    try:
        while RUNNING:
            try:
                tick(args.repo, args.branch, args.auto_run, args.timeout)
            except Exception as exc:
                store(phase="error", lastError=f"{type(exc).__name__}: {exc}")
                print(traceback.format_exc(), flush=True)
            for _ in range(args.interval * 2):
                if not RUNNING:
                    break
                time.sleep(0.5)
    finally:
        store(service="stopped", phase="stopped")
    return 0

if __name__ == "__main__":
    sys.exit(main())
