# agent-task-loop

Run your coding agent through a task list **unattended**: one task at a time, checked by **your own** build and tests, retried with the error log, stopped when it starts going in circles, resumable after a crash, with a notification at the end.

```
TASKS.md  ->  agent (Claude Code, Codex, any CLI)  ->  YOUR verify command  ->  green: next task / red: retry or block
```

## What it does

| Feature | How |
|---|---|
| One task at a time | first `- [ ]` line of `TASKS.md`, in file order |
| Independent verification | your command (`pytest`, `mvn verify`, `dotnet test`…) decides; the agent never grades itself |
| Per-task checks | `- [ ] Add /health | verify: mvn -q test -Dtest=HealthTest`, plus an optional project-wide check (build, lint) |
| Regression checks | after each task, the checks of the tasks already done run again; blocked tasks are left out so they do not make every later task fail |
| Agent knows its judge | the prompt names the verify commands and asks the agent to read those tests before coding |
| Retry with context | the next prompt contains the end of the failing output and "do not repeat the previous approach" |
| Loop guard | a task is blocked (`- [!]` + reason) when the same failure repeats, when the agent changed nothing twice, or after N attempts |
| Agent failures | an agent call that fails without changing anything (quota, network, login) is not charged to the task; after 3 in a row the loop pauses, tasks untouched, and resumes when run again |
| Resume | state in `.loop/state.json`; run the same command again after a crash or reboot |
| Log | `PROGRESS.md` (DONE / FAILED / BLOCKED / AGENT ERROR / LOOP PAUSED / LOOP END lines) |
| Git | optional commit after each verified task |
| Notifications | `file`, `desktop` (Windows balloon, macOS, Linux `notify-send`) or `ntfy:<your topic URL>` |
| Limits | attempts per task, timeout per agent run and per verification, maximum hours |

It does **not** make the agent smarter. It organises and checks its work, so you can leave it running.

## Install

- Python 3.9 or newer. No package to install (standard library only).
- Copy `loop.py` into your project (or anywhere) and `templates/` as a starting point.
- Works on Windows, macOS and Linux.

As a skill (in-session use, without `loop.py`): copy this folder to `.agents/skills/agent-task-loop/` or `.claude/skills/agent-task-loop/`. `SKILL.md` describes the same method for an agent working inside a session.

## Quick start

1. Write `TASKS.md` (see `templates/TASKS.md`): small, testable tasks, each with `| verify: <command>` when possible.
2. Copy `templates/loop.config.json` to your project root as `loop.config.json`, keep one `verify` line.
3. Run:

```bash
python loop.py
```

Command-line options override the config file: `python loop.py --max-attempts 5 --notify ntfy:https://ntfy.sh/<your-private-topic>`. See `python loop.py --help`.

### Agent commands

- **Claude Code**: `claude -p --permission-mode acceptEdits < {prompt_file}`
  The prompt is sent on standard input. `acceptEdits` lets it edit files without asking; tests are run by `loop.py`, not by the agent. Use your own subscription or API key.
- **Codex CLI**: check `codex exec --help` for how your version reads a prompt from a file or standard input, then put that command in `agent` with `{prompt_file}`. *(Not tested yet: see "Tested so far".)*
- **Any other CLI**: `{prompt_file}` is replaced by the path of `.loop/prompt.md`; `{prompt}` by the prompt text, quoted for your shell.

### Windows notes

- Run from PowerShell or `cmd`. Commands go through the system shell, so `&&` works in `cmd`; in PowerShell 5.1 prefer `;` or a script.
- `desktop` notifications use a standard Windows balloon (no module to install).
- Keep the PC awake for long runs (Settings > Power > Sleep: Never while plugged in).

## Safety

- `agent` and `verify` are **your** commands, from your config or command line, run through the shell like a Makefile line. Task text and agent output are never executed.
- The only network call made by `loop.py` itself is the optional `ntfy:` notification to the URL you choose.
- Give the agent the minimum permissions it needs. Run it in a git repository so every change can be reviewed and reverted.

## Tested so far (honest status)

| What | Result | Date |
|---|---|---|
| Orchestrator logic with a deterministic fake agent: order, already-satisfied task, retry with failure log, same-failure guard, no-change guard, attempt limit, continue or stop on block, resume, per-task and global checks, regression of a done task caught, blocked task not re-checked, verify command shown in the prompt, agent failure paused without blocking tasks, config file, git commits, notification file | **21 automated tests pass** (`python -m unittest discover -s tests`) | 2026-10-27 |
| Real agent: Claude Code with free models, on the 10-task demo project | one call for the whole list: **8/10** tasks in 3 runs out of 3 (about 4 min). `loop.py`: **9/10** in 2 valid runs out of 2 (14 to 19 min); the extra task was fixed after the agent saw the test failure. Small sample, models changed from call to call: details and limits in the pack's `RESULTS.md` | 2026-10-27 |
| Codex, other agents | not tested | — |

Further results will be published here as measured, with the model, the agent and the number of tasks completed without intervention.

## Limits

- Value depends on your checks: a weak `verify` command lets wrong work through.
- One task at a time: no parallel agents.
- The loop guard compares the end of the failure output with numbers ignored; two different failures that end with the same lines count as "the same".
- Long runs use your agent's quota or credits.

## Pack (optional, paid)

Everything above is free. A paid pack adds a practical guide (writing tasks an agent can finish, settings, Windows notes, reading the results, troubleshooting), the demo project with its reference solution, the script to measure your own agent on it, and the measured results with their method. Pack: not published yet.

## Credits and licence

- Written by Abdellatif Gourri with the help of an AI coding assistant (Claude); every line was reviewed and tested as listed above.
- Core (`loop.py`, `SKILL.md`, templates, tests): MIT licence.
