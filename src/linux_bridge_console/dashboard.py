"""Linux Bridge Console: interactive Windows Bridge-like job console."""
import argparse
import curses
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from runner import HOME, repo_dir, sync, inspect, execute, publish

PREFS = HOME / "console-settings.json"
POLL = 15

def get_prefs():
    try:
        data = json.loads(PREFS.read_text())
        return {"autoRun": bool(data.get("autoRun", False)),
                "autoSend": bool(data.get("autoSend", True))}
    except (OSError, ValueError, TypeError):
        return {"autoRun": False, "autoSend": True}

def save_prefs(data):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = PREFS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, PREFS)

def read_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return {}

class Console:
    def __init__(self, repo, branch):
        self.repo, self.branch = repo, branch
        self.prefs = get_prefs()
        self.lock = threading.Lock()
        self.phase = "Starting"
        self.message = "Initializing GitHub connection"
        self.job = {}
        self.result = {}
        self.root = repo_dir(repo)
        self.next_check = 0
        self.running = False
        self.processing = False
        self.busy = False
        self.started = None
        self.last_refresh = 0
        self.history = []
        self.cancel_requested = False

    def note(self, message):
        with self.lock:
            self.message = message
            self.history.append(message)
            self.history = self.history[-30:]

    def submit(self, operation, fn):
        if self.busy:
            self.note("Another operation is in progress")
            return
        self.busy = True
        def perform():
            try:
                fn()
            except Exception as error:
                self.note(f"{operation} FAILED: {error}")
                self.phase = "Error"
            finally:
                self.busy = False
        threading.Thread(target=perform, daemon=True).start()

    def fetch(self):
        if self.processing:
            return
        self.phase = "Checking GitHub"
        self.root = sync(self.repo, self.branch)
        self.job, script = inspect(self.root)
        jid = self.job["id"]
        dest = self.root / "workspace" / "results" / jid
        self.result = read_json(dest / "result.json")
        self.next_check = time.monotonic() + POLL
        if self.result:
            self.phase = "Completed"
            self.note(f"Job {jid}: {self.result.get('status', 'completed')}")
        else:
            self.phase = "Job available"
            self.note(f"Received job {jid}: {self.job.get('description', '')}")
            if self.prefs["autoRun"]:
                self.start_job()

    def start_job(self):
        if self.processing:
            self.note("Job already running")
            return
        if not self.job or self.result:
            self.note("No new job available")
            return
        job = dict(self.job)
        root = self.root
        try:
            _, script = inspect(root)
        except Exception as error:
            self.note(str(error))
            return
        self.processing = True
        self.phase = "Running"
        self.started = time.monotonic()

        def task():
            try:
                claimdir = HOME / "claims"
                claimdir.mkdir(parents=True, exist_ok=True)
                claim = claimdir / (self.repo.replace("/", "__") + "__" + job["id"] + ".json")
                result_path = root / "workspace" / "results" / job["id"] / "result.json"
                if claim.exists() or result_path.exists():
                    raise RuntimeError("Job already claimed/completed; refusing rerun")
                fd = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as handle:
                    json.dump({"jobId": job["id"], "time": time.time()}, handle)
                with (HOME / "job.lock").open("a+") as handle:
                    fcntl.flock(handle, fcntl.LOCK_EX)
                    self.note(f"Running {job['id']}")
                    result, dest = execute(root, job, script, 900)
                    self.result = result
                    self.phase = "Completed"
                    self.note(f"Finished {job['id']}: {result['status']} (exit {result['exitCode']})")
                    if self.prefs["autoSend"]:
                        self.phase = "Sending results"
                        publish(root, dest, self.branch)
                        self.note("Results uploaded to GitHub")
                        self.phase = "Completed"
            except Exception as error:
                self.phase = "Error"
                self.note(f"Execution/upload failed: {error}")
            finally:
                self.processing = False
                self.next_check = time.monotonic() + POLL
        threading.Thread(target=task, daemon=True).start()

    def send(self):
        if not self.job:
            self.note("No job selected")
            return
        jid = self.job["id"]
        folder = self.root / "workspace" / "results" / jid
        if not (folder / "result.json").exists():
            self.note("No result to send")
            return
        self.phase = "Sending results"
        publish(self.root, folder, self.branch)
        self.phase = "Completed"
        self.note(f"Results for {jid} uploaded")

    def output(self):
        if not self.job:
            return []
        folder = self.root / "workspace" / "results" / self.job["id"]
        lines = []
        for name in ("stdout.log", "stderr.log"):
            path = folder / name
            try:
                part = path.read_text(errors="replace").splitlines()[-15:]
                if part:
                    lines.extend(([name + ":"] if name == "stderr.log" else []) + part)
            except OSError:
                pass
        return lines

def paint(scr, rows, footer):
    scr.erase()
    height, width = scr.getmaxyx()
    if height < 16 or width < 55:
        rows = ["Enlarge terminal to at least 55 columns x 16 lines"]
    for index, text in enumerate(rows[:max(0, height-2)]):
        try:
            attr = curses.A_BOLD if index in (0, 2) else 0
            scr.addnstr(index, 1, str(text), max(0, width - 2), attr)
        except curses.error:
            pass
    if height > 1 and width > 2:
        try:
            scr.addnstr(height-1, 0, footer.ljust(width-1), width-1, curses.A_REVERSE)
        except curses.error:
            pass
    scr.refresh()

def screen(scr, app):
    curses.curs_set(0)
    scr.timeout(250)
    show_history = False
    app.submit("Fetch", app.fetch)
    footer = "[F] Fetch [R] Run [A] Auto Run [T] Auto Send [S] Send [L] Logs [Q] Quit"
    while True:
        now = time.monotonic()
        if now >= app.next_check and not app.busy and not app.processing:
            app.next_check = now + POLL
            app.submit("Fetch", app.fetch)
        jid = app.job.get("id", "--")
        elapsed = int(now-app.started) if app.processing and app.started else 0
        result = app.result
        rows = [
            " LINUX BRIDGE CONSOLE  |  GitHub Job Runner",
            "=" * 70,
            f"Repository : {app.repo}  [{app.branch}]",
            f"Auto Run   : {'ON' if app.prefs['autoRun'] else 'OFF'}    Auto Send: {'ON' if app.prefs['autoSend'] else 'OFF'}",
            f"Phase      : {app.phase}   Elapsed: {elapsed//60:02}:{elapsed%60:02}",
            f"Next check : {max(0, int(app.next_check-now))}s",
            "-" * 70,
            f"Job        : {jid}",
            f"Description: {app.job.get('description', '--')}",
            f"Script     : {app.job.get('script', '--')}",
            f"Result     : {result.get('status', 'Pending')}",
            f"Exit code  : {result.get('exitCode', '--')}",
            "-" * 70,
            "JOB LOG" if not show_history else "ACTIVITY HISTORY",
        ]
        rows.extend(app.history[-12:] if show_history else app.output()[-12:])
        rows += ["", f"Status: {app.message}"]
        paint(scr, rows, footer)
        key = scr.getch()
        if key in (ord("q"), ord("Q")):
            if app.processing or app.busy:
                app.note("Operation in progress: finish before quitting")
            else:
                return
        elif key in (ord("a"), ord("A")):
            app.prefs["autoRun"] = not app.prefs["autoRun"]
            save_prefs(app.prefs)
            app.note(f"Auto Run {'enabled' if app.prefs['autoRun'] else 'disabled'}")
            if app.prefs["autoRun"] and app.job and not app.result and not app.processing:
                app.start_job()
        elif key in (ord("t"), ord("T")):
            app.prefs["autoSend"] = not app.prefs["autoSend"]
            save_prefs(app.prefs)
            app.note("Auto Send " + ("enabled" if app.prefs["autoSend"] else "disabled"))
        elif key in (ord("r"), ord("R")):
            app.start_job()
        elif key in (ord("f"), ord("F")):
            if not app.processing:
                app.submit("Fetch", app.fetch)
        elif key in (ord("s"), ord("S")):
            if not app.processing:
                app.submit("Send", app.send)
        elif key in (ord("l"), ord("L")):
            show_history = not show_history

def main():
    parser = argparse.ArgumentParser(description="Linux Bridge Console")
    parser.add_argument("--repo", default="Pcattache30/Linux-Bridge-Console")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Use LBC from an interactive terminal", file=sys.stderr)
        return 1
    HOME.mkdir(parents=True, exist_ok=True)
    with (HOME / "console.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another LBC console is already running", file=sys.stderr)
            return 1
        curses.wrapper(screen, Console(args.repo, args.branch))
    return 0

if __name__ == "__main__":
    sys.exit(main())
