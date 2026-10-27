#!/usr/bin/env python3
"""agent-task-loop: run a coding agent through a task list, one task at a time, with independent verification.

For each unchecked task in TASKS.md the loop:
  1. writes a prompt to .loop/prompt.md and runs your agent command on it;
  2. runs YOUR verify command itself (build, tests, lint) - the agent never grades itself;
  3. green: checks the task, appends to PROGRESS.md, optionally commits with git;
     red: retries with the end of the failure log;
  4. stops a task early (marks it "- [!]") when the same failure repeats, when the agent changed nothing,
     or when the retry limit is reached - so the agent cannot loop forever;
     when the agent itself fails (exit code not 0 and no file changed: quota, network, login), the task is not
     charged; after a few such failures in a row the loop pauses instead of blocking every task;
  5. saves its state in .loop/state.json, so running the command again resumes where it stopped;
  6. notifies you when it finishes or when a task is blocked.

Standard library only. Python 3.9+. Windows, macOS and Linux.

Example:
  python loop.py --agent "claude -p --permission-mode acceptEdits < {prompt_file}" --verify "python -m pytest -q"
"""
import argparse, datetime, hashlib, json, os, re, shlex, subprocess, sys, time, urllib.request

TASK_RE = re.compile(r"^(\s*[-*]\s+\[)([ xX!])(\]\s+)(.*)$")
STATE_DIR = ".loop"


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_tasks(path):
    """Return a list of (line_index, status, text). status: ' ' todo, 'x' done, '!' blocked."""
    lines = read_text(path).splitlines()
    out = []
    for i, line in enumerate(lines):
        m = TASK_RE.match(line)
        if m:
            out.append((i, m.group(2).lower(), m.group(4).strip()))
    return lines, out


def split_verify(text):
    """'Add login | verify: pytest tests/test_login.py' -> ('Add login', 'pytest tests/test_login.py')."""
    m = re.match(r"^(.*?)\s*\|\s*verify:\s*(.+?)\s*(<!--.*-->)?$", text)
    return (m.group(1).strip(), m.group(2).strip()) if m else (re.sub(r"\s*<!--.*-->$", "", text).strip(), "")


def set_status(path, line_index, status, note=""):
    lines = read_text(path).splitlines()
    m = TASK_RE.match(lines[line_index])
    text = m.group(4)
    if note:
        text = re.sub(r"\s*<!-- loop:.*?-->$", "", text) + f" <!-- loop: {note} -->"
    lines[line_index] = f"{m.group(1)}{status}{m.group(3)}{text}"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def log_progress(root, message):
    with open(os.path.join(root, "PROGRESS.md"), "a", encoding="utf-8", newline="\n") as f:
        f.write(f"- {now()} {message}\n")


def load_state(root):
    p = os.path.join(root, STATE_DIR, "state.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"started": now(), "attempts": {}, "last_failure_hash": {}, "no_change": {}}


def save_state(root, state):
    os.makedirs(os.path.join(root, STATE_DIR), exist_ok=True)
    with open(os.path.join(root, STATE_DIR, "state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def tree_fingerprint(root, ignore=(STATE_DIR, ".git", "__pycache__", "PROGRESS.md")):
    """Hash of every file (path + content) except loop bookkeeping: detects 'the agent changed nothing'."""
    h = hashlib.sha256()
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in ignore and not x.startswith(".venv"))
        for f in sorted(files):
            if f in ignore or f.endswith(".pyc"):
                continue
            p = os.path.join(d, f)
            h.update(os.path.relpath(p, root).replace("\\", "/").encode())
            try:
                with open(p, "rb") as fh:
                    h.update(fh.read())
            except OSError:
                pass
    return h.hexdigest()


def run(cmd, root, timeout):
    """Run the user's own agent or verify command through the shell (like a Makefile line); return (exit code, output).
    These commands come from the user's command line or config, never from task text or agent output."""
    try:
        r = subprocess.run(cmd, cwd=root, shell=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        return 124, out + f"\n[agent-task-loop] command timed out after {timeout}s"


def failure_hash(output):
    """Fingerprint of a failure, ignoring numbers that change between runs (timings, line counts, addresses)."""
    tail = "\n".join(output.strip().splitlines()[-40:])
    tail = re.sub(r"\d+(\.\d+)?", "#", tail)
    return hashlib.sha256(tail.encode()).hexdigest()[:16]


def build_prompt(task, attempt, failure_tail, progress_tail, rules, verify_cmds=()):
    parts = [
        "You are working through a task list with an automatic verifier.",
        f"Current task: {task}",
        "Do only this task. Make the smallest correct change. Do not edit, delete or skip tests to make them pass.",
        "When you think the task is done, stop: the verifier will run the build and tests itself.",
    ]
    if verify_cmds:
        # Telling the agent what will judge it: without this it guesses the expected names, types and formats.
        parts.append("The verifier will run:\n" + "\n".join(f"    {c}" for c in verify_cmds) + "\n"
                     "Read the tests or checks these commands run before changing code, and match exactly what they "
                     "expect. The checks of tasks already done are run again too: do not break them.")
    if rules:
        parts.append("Project rules:\n" + rules.strip())
    if progress_tail:
        parts.append("Recent progress (from PROGRESS.md):\n" + progress_tail)
    if attempt > 1 and failure_tail:
        parts.append(f"Attempt {attempt}. The verifier failed last time. End of its output:\n```\n{failure_tail}\n```\n"
                     "Find the root cause before changing code. Do not repeat the previous approach if it did not work.")
    return "\n\n".join(parts) + "\n"


def notify(method, title, message, root):
    if not method or method == "none":
        return
    try:
        if method == "file":
            with open(os.path.join(root, STATE_DIR, "NOTIFICATIONS.txt"), "a", encoding="utf-8") as f:
                f.write(f"{now()} {title}: {message}\n")
        elif method.startswith("ntfy:"):
            req = urllib.request.Request(method[5:], data=message.encode("utf-8"), headers={"Title": title})
            urllib.request.urlopen(req, timeout=10)
        elif method == "desktop":
            if sys.platform.startswith("win"):
                ps = ("[void][Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
                      "$n=New-Object System.Windows.Forms.NotifyIcon;$n.Icon=[System.Drawing.SystemIcons]::Information;"
                      f"$n.Visible=$true;$n.ShowBalloonTip(10000,'{title.replace(chr(39), '')}','{message.replace(chr(39), '')}',"
                      "[System.Windows.Forms.ToolTipIcon]::Info);Start-Sleep 6;$n.Dispose()")
                subprocess.Popen(["powershell", "-NoProfile", "-Command", ps])
            elif sys.platform == "darwin":
                subprocess.run(["osascript", "-e", f'display notification "{message}" with title "{title}"'])
            else:
                subprocess.run(["notify-send", title, message])
    except Exception as e:  # a failed notification must never stop the loop
        print(f"[agent-task-loop] notification failed: {e}")


def git_commit(root, message):
    """Commit everything after a verified task. Argument lists, no shell: the task text cannot inject commands."""
    if subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True).returncode != 0:
        return
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=root, capture_output=True)


def quote_arg(text):
    """Quote the prompt for the platform's shell (the agent command itself is written by the user)."""
    return subprocess.list2cmdline([text]) if sys.platform.startswith("win") else shlex.quote(text)


def main(argv=None):
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default="")
    pre.add_argument("--root", default=".")
    known, _ = pre.parse_known_args(argv)
    config = {}
    cfg_path = known.config or os.path.join(known.root, "loop.config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            config = {k.replace("-", "_"): v for k, v in json.load(f).items() if not k.startswith("_")}

    ap = argparse.ArgumentParser(description="Run a coding agent through TASKS.md with independent verification. "
                                             "Defaults can be stored in loop.config.json (command-line options win).")
    ap.add_argument("--config", default="", help="JSON file with default options (default: <root>/loop.config.json)")
    ap.add_argument("--root", default=".", help="project folder (default: current folder)")
    ap.add_argument("--tasks", default="TASKS.md", help="task list with Markdown checkboxes")
    ap.add_argument("--agent", required="agent" not in config,
                    help="agent command; {prompt_file} is replaced by the prompt path, {prompt} by its text (quoted)")
    ap.add_argument("--verify", default="",
                    help="project-wide command that must exit 0 after every task (build, lint). "
                         "A task can add its own check with '| verify: <command>' at the end of its line; both must pass.")
    ap.add_argument("--rules", default="", help="optional file with project rules added to every prompt")
    ap.add_argument("--max-attempts", type=int, default=3, help="attempts per task before it is blocked")
    ap.add_argument("--agent-timeout", type=int, default=1800, help="seconds allowed for one agent run")
    ap.add_argument("--verify-timeout", type=int, default=900, help="seconds allowed for one verification")
    ap.add_argument("--max-hours", type=float, default=8.0, help="stop the whole loop after this many hours")
    ap.add_argument("--notify", default="file", help="none | file | desktop | ntfy:<url of your topic>")
    ap.add_argument("--git", action="store_true", help="commit after each verified task")
    ap.add_argument("--stop-on-block", action="store_true", help="stop the loop when a task is blocked")
    ap.add_argument("--no-regress", action="store_true",
                    help="do not re-run the '| verify:' checks of the tasks already done after each task")
    ap.add_argument("--max-agent-errors", type=int, default=3,
                    help="pause the loop after this many agent failures in a row (exit code not 0, no file changed)")
    ap.add_argument("--agent-error-wait", type=int, default=60,
                    help="seconds to wait after an agent failure, multiplied by the number of failures in a row")
    unknown = set(config) - {act.dest for act in ap._actions}
    if unknown:
        ap.error(f"unknown option(s) in config file: {', '.join(sorted(unknown))}")
    ap.set_defaults(**config)
    a = ap.parse_args(argv)

    root = os.path.abspath(a.root)
    tasks_path = os.path.join(root, a.tasks)
    rules = read_text(os.path.join(root, a.rules)) if a.rules else ""
    state = load_state(root)
    os.makedirs(os.path.join(root, STATE_DIR), exist_ok=True)
    deadline = time.time() + a.max_hours * 3600
    done_now, blocked_now, paused = 0, 0, ""

    while time.time() < deadline:
        _, tasks = read_tasks(tasks_path)
        todo = [t for t in tasks if t[1] == " "]
        if not todo:
            break
        idx, _, raw = todo[0]
        text, task_verify = split_verify(raw)
        key = text
        verify_cmds = [c for c in (task_verify, a.verify) if c]
        # Regression checks: the per-task checks of the tasks already done must stay green. Blocked tasks are left
        # out, so one blocked task does not make every later task fail.
        regress_cmds = [] if a.no_regress else list(dict.fromkeys(
            v for _, st, r in tasks if st == "x" for v in [split_verify(r)[1]] if v and v not in verify_cmds))
        if not verify_cmds:
            print("[agent-task-loop] no verify command: give --verify or '| verify: <command>' on the task line")
            return 2
        attempt = state["attempts"].get(key, 0) + 1
        state["attempts"][key] = attempt

        progress = ""
        pp = os.path.join(root, "PROGRESS.md")
        if os.path.exists(pp):
            progress = "\n".join(read_text(pp).splitlines()[-10:])
        failure_tail = state.get("last_failure_tail", {}).get(key, "")
        prompt = build_prompt(text, attempt, failure_tail, progress, rules, verify_cmds)
        prompt_file = os.path.join(root, STATE_DIR, "prompt.md")
        with open(prompt_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(prompt)
        save_state(root, state)

        before = tree_fingerprint(root)
        cmd = a.agent.replace("{prompt_file}", prompt_file).replace("{prompt}", quote_arg(prompt))
        print(f"[{now()}] task: {text} (attempt {attempt})")
        code, agent_out = run(cmd, root, a.agent_timeout)
        with open(os.path.join(root, STATE_DIR, "last_agent_output.txt"), "w", encoding="utf-8") as f:
            f.write(agent_out)
        changed = tree_fingerprint(root) != before

        vcode, vout = 0, ""
        for vc in verify_cmds + regress_cmds:
            c, o = run(vc, root, a.verify_timeout)
            label = "(regression check of an earlier task) " if vc in regress_cmds else ""
            vout += f"$ {label}{vc}\n{o}\n"
            if c != 0:
                vcode = c
                break
        if vcode == 0:
            # Green without any change: an earlier task already did this work (agents often get ahead).
            # Counted as done, but logged differently so a too-weak verify command can be spotted.
            note = "" if changed else ", already satisfied: verify green with no change"
            set_status(tasks_path, idx, "x")
            log_progress(root, f"DONE: {text} (attempt {attempt}{note})")
            if a.git:
                git_commit(root, f"agent-task-loop: {text}")
            done_now += 1
            for d in ("last_failure_hash", "no_change", "last_failure_tail"):
                state.setdefault(d, {}).pop(key, None)
            save_state(root, state)
            continue

        if code != 0 and not changed:
            # The agent itself failed (quota, network, login): not the task's fault. The attempt is not counted,
            # and after a few failures in a row the loop pauses, so a night run does not block every task.
            state["attempts"][key] = attempt - 1
            errors = state.get("agent_errors", 0) + 1
            state["agent_errors"] = errors
            last = next((l.strip() for l in reversed(agent_out.splitlines()) if l.strip()), "")[:200]
            log_progress(root, f"AGENT ERROR {errors} (exit {code}): {text} - {last}")
            save_state(root, state)
            if errors >= a.max_agent_errors:
                paused = f"the agent failed {errors} times in a row (quota, network or login?); fix it and run again"
                log_progress(root, f"LOOP PAUSED: {paused}")
                break
            time.sleep(a.agent_error_wait * errors)
            continue
        state["agent_errors"] = 0

        reason = None
        if not changed:
            state["no_change"][key] = state["no_change"].get(key, 0) + 1
            if state["no_change"][key] >= 2:
                reason = reason or "the agent changed nothing twice in a row"
        fh = failure_hash(vout)
        if vcode != 0 and state["last_failure_hash"].get(key) == fh:
            reason = reason or "the same verification failure happened twice in a row"
        state["last_failure_hash"][key] = fh
        state.setdefault("last_failure_tail", {})[key] = "\n".join(vout.strip().splitlines()[-30:])
        if reason is None and attempt >= a.max_attempts:
            reason = f"still failing after {attempt} attempts"
        log_progress(root, f"FAILED attempt {attempt}: {text} (verify exit {vcode})")
        save_state(root, state)

        if reason:
            set_status(tasks_path, idx, "!", reason)
            log_progress(root, f"BLOCKED: {text} - {reason}")
            blocked_now += 1
            notify(a.notify, "agent-task-loop: task blocked", f"{text}: {reason}", root)
            save_state(root, state)
            if a.stop_on_block:
                break

    _, tasks = read_tasks(tasks_path)
    left = sum(1 for t in tasks if t[1] == " ")
    summary = f"{done_now} done, {blocked_now} blocked, {left} left" + (f", paused: {paused}" if paused else "")
    log_progress(root, f"LOOP END: {summary}")
    notify(a.notify, "agent-task-loop paused" if paused else "agent-task-loop finished", summary, root)
    print(f"[{now()}] {summary}")
    if paused:
        return 3
    return 0 if blocked_now == 0 and left == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
