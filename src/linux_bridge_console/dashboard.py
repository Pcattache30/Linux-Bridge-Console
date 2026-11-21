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
        self.next_update = time.monotonic() + 20
        self.restart_requested = False
        package_version = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", "linux-bridge-console"],
            capture_output=True, text=True, check=False)
        self.version = package_version.stdout.strip() if package_version.returncode == 0 else "dev"
        runtime_path = Path(__file__).resolve()
        versions_dir = HOME / "versions"
        if versions_dir in runtime_path.parents:
            self.version = runtime_path.parents[3].name

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
            if not self.history or self.history[-1] != f"Job {jid}: {self.result.get('status', 'completed')}":
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

    def update_runtime(self):
        if self.processing:
            return
        path = Path(__file__).with_name("update-user.sh")
        if not path.exists():
            path = Path("/usr/lib/linux-bridge-console/update-user.sh")
        if not path.exists():
            self.note("Updater missing from this installed version")
            return
        command = subprocess.run(["bash", str(path)], capture_output=True, text=True,
                                 timeout=180, check=False)
        output = (command.stdout + "\\n" + command.stderr).strip()
        if command.returncode:
            raise RuntimeError(output[-600:] or f"Updater exit {command.returncode}")
        if "installed user runtime v" in output:
            self.note("New LBC version installed; restarting dashboard")
            self.restart_requested = True
        self.next_update = time.monotonic() + 60

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

def put(scr, y, x, value, width, attr=0):
    height, columns = scr.getmaxyx()
    if y < 0 or y >= height or x < 0 or x >= columns or width < 1:
        return
    try:
        scr.addnstr(y, x, str(value), min(width, columns-x-1), attr)
    except curses.error:
        pass

def panel(scr, y, x, height, width, title, color):
    if height < 3 or width < 5:
        return
    edge = "+" + "-" * (width-2) + "+"
    put(scr, y, x, edge, width, color)
    for row in range(y+1, y+height-1):
        put(scr, row, x, "|", 1, color)
        put(scr, row, x+width-1, "|", 1, color)
    put(scr, y+height-1, x, edge, width, color)
    put(scr, y, x+2, " " + title.upper() + " ", width-4, color | curses.A_BOLD)

def palette():
    if not curses.has_colors():
        return {name: curses.A_BOLD for name in ("accent", "good", "warn", "bad", "muted")}
    curses.start_color()
    curses.use_default_colors()
    for n, foreground in enumerate(
        (curses.COLOR_CYAN, curses.COLOR_GREEN, curses.COLOR_YELLOW,
         curses.COLOR_RED, curses.COLOR_WHITE), 1
    ):
        curses.init_pair(n, foreground, -1)
    return dict(zip(("accent", "good", "warn", "bad", "muted"),
                    (curses.color_pair(n) for n in range(1, 6))))

def display(scr, app, show_history, colors):
    scr.erase()
    h, w = scr.getmaxyx()
    if h < 20 or w < 80:
        put(scr, 1, 2, "Resize terminal to at least 80 x 20", max(1,w-4))
        put(scr, h-1, 0, "[Q] Quit", max(1,w-1), curses.A_REVERSE)
        scr.refresh()
        return

    state = app.phase.lower()
    status_style = (colors["bad"] if "error" in state or "fail" in state
                    else colors["good"] if "complete" in state
                    else colors["warn"] if "available" in state
                    else colors["accent"])
    now = time.monotonic()
    elapsed = int(now - app.started) if app.processing and app.started else 0
    left = max(34, min(49, int(w * .41)))
    right_x = left + 2
    right_w = w - right_x - 1
    top = 7
    middle_h = 10
    log_y = top + middle_h + 1
    log_h = max(3, h - log_y - 4)

    put(scr, 0, 1, "  LINUX BRIDGE CONSOLE  v" + app.version, w-3, colors["accent"] | curses.A_BOLD)
    put(scr, 0, max(2,w-25), "INTERACTIVE JOB RUNNER", 23, colors["muted"])
    put(scr, 1, 1, "=" * (w-3), w-3, colors["accent"])
    put(scr, 2, 2, "REPOSITORY", 12, colors["muted"])
    put(scr, 2, 16, app.repo + "  [" + app.branch + "]", w-19, curses.A_BOLD)
    put(scr, 3, 2, "CONNECTION", 12, colors["muted"])
    put(scr, 3, 16, "GitHub polling every 15s", w-18)
    put(scr, 4, 2, "AUTO RUN", 10, colors["muted"])
    put(scr, 4, 16, "ON" if app.prefs["autoRun"] else "OFF", 4,
        colors["good"] if app.prefs["autoRun"] else colors["warn"])
    put(scr, 4, 29, "AUTO SEND", 11, colors["muted"])
    put(scr, 4, 42, "ON" if app.prefs["autoSend"] else "OFF", 4,
        colors["good"] if app.prefs["autoSend"] else colors["warn"])
    put(scr, 5, 2, "STATUS", 10, colors["muted"])
    put(scr, 5, 16, app.phase, 24, status_style | curses.A_BOLD)
    put(scr, 5, 44, "NEXT CHECK " + str(max(0, int(app.next_check-now))) + "s", 20, colors["accent"])
    put(scr, 6, 1, "-" * (w-3), w-3, colors["muted"])

    panel(scr, top, 1, middle_h, left, "Current Job", colors["accent"])
    panel(scr, top, right_x, middle_h, right_w, "Execution & Activity", colors["accent"])
    job = app.job
    result = app.result
    job_details = [
        ("JOB ID", job.get("id", "--")),
        ("DESCRIPTION", job.get("description", "--")),
        ("SCRIPT", job.get("script", "--")),
        ("RESULT", result.get("status", "Not executed")),
        ("EXIT CODE", result.get("exitCode", "--")),
        ("DURATION", f"{elapsed//60:02}:{elapsed%60:02}" if app.processing else "--"),
        ("MODE", "Interactive session"),
    ]
    for idx, (label, value) in enumerate(job_details):
        put(scr, top+1+idx, 3, label, 12, colors["muted"])
        put(scr, top+1+idx, 16, value, max(1, left-19),
            status_style if label == "RESULT" else 0)

    actions = app.history[-(middle_h-2):]
    for idx, line in enumerate(actions):
        put(scr, top+1+idx, right_x+2, line, max(1,right_w-5))
    if not actions:
        put(scr, top+2, right_x+2, "Waiting for GitHub activity...", max(1,right_w-5))

    panel(scr, log_y, 1, log_h, w-2,
          "Activity History" if show_history else "Live Job Output", colors["accent"])
    lines = app.history if show_history else app.output()
    available = max(0, log_h-2)
    for idx, line in enumerate(lines[-available:]):
        put(scr, log_y+1+idx, 3, line, w-7,
            colors["bad"] if "error" in line.lower() else 0)

    put(scr, h-3, 2, "LAST: " + str(app.message), w-5, colors["muted"])
    footer = " F Fetch | R Run | A Auto Run | T Auto Send | S Send | L Logs | U Update | Q Quit "
    put(scr, h-1, 0, footer.ljust(w-1), w-1, curses.A_REVERSE)
    scr.refresh()

def screen(scr, app):
    curses.curs_set(0)
    scr.timeout(250)
    colors = palette()
    show_history = False
    app.submit("Fetch", app.fetch)
    while True:
        now = time.monotonic()
        if app.restart_requested and not app.processing and not app.busy:
            return "restart"
        if now >= app.next_update and not app.busy and not app.processing:
            app.next_update = now + 60
            app.submit("Update", app.update_runtime)
        if now >= app.next_check and not app.busy and not app.processing:
            app.next_check = now + POLL
            app.submit("Fetch", app.fetch)
        display(scr, app, show_history, colors)
        key = scr.getch()
        if key in (ord("q"), ord("Q"), ord("u"), ord("U")):
            if app.processing or app.busy:
                app.note("Job or GitHub operation active; finish before exiting/updating")
            else:
                return "update" if key in (ord("u"), ord("U")) else "quit"
        elif key in (ord("a"), ord("A")):
            app.prefs["autoRun"] = not app.prefs["autoRun"]
            save_prefs(app.prefs)
            app.note("Auto Run " + ("ON" if app.prefs["autoRun"] else "OFF"))
            if app.prefs["autoRun"] and app.job and not app.result and not app.processing:
                app.start_job()
        elif key in (ord("t"), ord("T")):
            app.prefs["autoSend"] = not app.prefs["autoSend"]
            save_prefs(app.prefs)
            app.note("Auto Send " + ("ON" if app.prefs["autoSend"] else "OFF"))
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
        action = curses.wrapper(screen, Console(args.repo, args.branch))
        if action in ("update", "restart"):
            if action == "restart":
                runtime = HOME / "current" / "usr" / "lib" / "linux-bridge-console" / "dashboard.py"
                if runtime.is_file():
                    os.execv(sys.executable, [sys.executable, str(runtime),
                                              "--repo", args.repo, "--branch", args.branch])
                print("Updated runtime not found; exiting safely.")
                return 1
            updater = Path(__file__).with_name("update-user.sh")
            if not updater.exists():
                updater = Path("/usr/lib/linux-bridge-console/update-user.sh")
            if not updater.exists():
                print("Updater unavailable in this installation.")
                return 1
            result = subprocess.run(["bash", str(updater)], check=False)
            if result.returncode:
                print(f"Update failed (exit {result.returncode}).")
                return result.returncode
            runtime = HOME / "current" / "usr" / "lib" / "linux-bridge-console" / "dashboard.py"
            if runtime.is_file():
                os.execv(sys.executable, [sys.executable, str(runtime),
                                          "--repo", args.repo, "--branch", args.branch])
            print("Updated runtime not found.")
            return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
