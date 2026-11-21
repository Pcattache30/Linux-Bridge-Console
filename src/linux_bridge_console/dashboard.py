"""Interactive Linux Bridge Console dashboard (standard-library curses)."""
import argparse
import curses
import json
from pathlib import Path
import subprocess
import sys
import time

from runner import repo_dir, sync

REFRESH_SECONDS = 15

def read_state(slug, branch):
    root = repo_dir(slug)
    config = root / "workspace" / "current.json"
    if not config.is_file():
        return {"error": "No job queue in local repository", "root": root}
    try:
        job = json.loads(config.read_text())
    except (ValueError, OSError) as exc:
        return {"error": str(exc), "root": root}
    jid = job.get("id", "")
    result_dir = root / "workspace" / "results" / jid
    result = {}
    result_path = result_dir / "result.json"
    if result_path.is_file():
        try:
            result = json.loads(result_path.read_text())
        except (ValueError, OSError):
            pass
    log = result_dir / "stdout.log"
    lines = log.read_text(errors="replace").splitlines()[-12:] if log.exists() else []
    errlog = result_dir / "stderr.log"
    errors = errlog.read_text(errors="replace").splitlines()[-5:] if errlog.exists() else []
    return {"root": root, "job": job, "result": result,
            "lines": lines, "errors": errors}

def draw(scr, rows):
    scr.erase()
    height, width = scr.getmaxyx()
    if height < 13 or width < 42:
        try:
            scr.addnstr(0, 0, "Enlarge terminal (minimum 42x13). Q to quit.", max(0, width-1))
        except curses.error:
            pass
        scr.refresh()
        return
    for index, item in enumerate(rows[:height-2]):
        text = str(item)
        try:
            scr.addnstr(index, 1, text, width - 2,
                        curses.A_BOLD if index in (0, 2) else curses.A_NORMAL)
        except curses.error:
            pass
    try:
        scr.addnstr(height-1, 1, "[Q] Quit    [F] Fetch    [R] Run job    [L] Show logs", width-2,
                    curses.A_REVERSE)
    except curses.error:
        pass
    scr.refresh()

def confirm(scr, message):
    height, width = scr.getmaxyx()
    prompt = message + " [y/N]: "
    curses.echo()
    curses.curs_set(1)
    try:
        scr.move(height-2, 0)
        scr.clrtoeol()
        scr.addnstr(height-2, 1, prompt, width-2)
        scr.refresh()
        data = scr.getstr(height-2, min(width-2, len(prompt)+1), 3)
        return data.decode(errors="replace").strip().lower() == "yes"
    finally:
        curses.noecho()
        curses.curs_set(0)

def ui(scr, slug, branch):
    curses.curs_set(0)
    scr.timeout(500)
    last_fetch = 0
    last_msg = "Starting..."
    state = {}
    show_logs = False
    while True:
        now = time.monotonic()
        if now - last_fetch >= REFRESH_SECONDS:
            try:
                sync(slug, branch)
                last_msg = "GitHub sync OK"
            except Exception as exc:
                last_msg = f"GitHub sync failed: {exc}"
            last_fetch = time.monotonic()
        try:
            state = read_state(slug, branch)
        except Exception as exc:
            state = {"error": str(exc)}
        job = state.get("job", {})
        result = state.get("result", {})
        remaining = max(0, int(REFRESH_SECONDS - (time.monotonic() - last_fetch)))
        rows = [
            "LINUX BRIDGE CONSOLE                          v0.2",
            "=" * 64,
            f"Repository : {slug}",
            f"Branch     : {branch}",
            f"Next fetch : {remaining}s",
            "",
            f"Job ID     : {job.get('id','--')}",
            f"Description: {job.get('description','--')}",
            f"Script     : {job.get('script','--')}",
            f"Status     : {result.get('status', 'Pending / not executed')}",
            f"Exit code  : {result.get('exitCode', '--')}",
            f"Host       : {result.get('hostname', '--')}",
            "",
            "LAST SYNC: " + last_msg,
            "",
            "JOB OUTPUT" if show_logs else "RECENT OUTPUT  (L toggles more logs)",
            "-" * 64,
        ]
        rows.extend(state.get("lines", []) if show_logs else state.get("lines", [])[-6:])
        if state.get("errors"):
            rows += ["STDERR:"] + state["errors"]
        if state.get("error"):
            rows.append("ERROR: " + state["error"])
        draw(scr, rows)
        key = scr.getch()
        if key in (ord("q"), ord("Q")):
            return
        if key in (ord("l"), ord("L")):
            show_logs = not show_logs
        if key in (ord("f"), ord("F")):
            last_fetch = 0
        if key in (ord("r"), ord("R")):
            if not job:
                last_msg = "No job available to execute"
                continue
            if result:
                last_msg = "Job already completed; duplicate execution blocked"
                continue
            if not confirm(scr, "Type yes to run job"):
                last_msg = "Job execution cancelled"
                continue
            # Execute with interactive confirmation already given. Output is
            # redirected to a file and persisted even if SSH is disconnected.
            # v0.2 foreground: no claims of background-safe operation.
            scr.clear()
            draw(scr, ["Executing job (foreground). Do not close SSH.", job.get("id", "")])
            command = [sys.executable, str(Path(__file__).resolve().with_name("runner.py")),
                       "--repo", slug, "--branch", branch, "--run"]
            completed = subprocess.run(command, input="YES\n", text=True, capture_output=True)
            last_msg = (completed.stdout + completed.stderr).strip()[-300:]
            last_fetch = 0

def main():
    parser = argparse.ArgumentParser(description="Linux Bridge Console")
    parser.add_argument("--repo", default="Pcattache30/Linux-Bridge-Console")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Run lbc from an interactive SSH or Linux terminal.", file=sys.stderr)
        return 1
    try:
        curses.wrapper(ui, args.repo, args.branch)
    except KeyboardInterrupt:
        pass
    return 0

if __name__ == "__main__":
    sys.exit(main())
