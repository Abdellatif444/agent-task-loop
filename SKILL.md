---
name: agent-task-loop
description: Works through a TASKS.md checklist one task at a time, runs the project's verify command after each task, logs progress in PROGRESS.md and stops a task that keeps failing the same way. Use when the user asks to work through a task list, a backlog or a multi-step plan unattended, or to resume such a list after an interruption.
license: MIT
metadata:
  version: "0.3"
---

# Agent task loop

Long task lists fail in three ways: the agent declares "done" without checking, it loses track after an interruption, or it repeats a fix that already failed. This procedure prevents all three. The same method is automated by `loop.py` (see "Files" below); use this file when you work through the list yourself, inside a session.

## Rules (in priority order)

1. **Verification decides, not you.** A task is done only when its verify command exits 0 after your change. Reason: the agent's own "it should work" is the most common false "done".
2. **Never edit, delete or skip a test to make it pass.** If a test looks wrong, stop and report it. Reason: a green run obtained this way hides the bug.
3. **One task at a time, in file order.** Do not start the next task while the current one is red. Reason: mixed changes make failures impossible to attribute.
4. **Stop instead of looping.** Block the task (`- [!]`) and move on when any of these happens: the same failure appears twice in a row; you changed nothing in two attempts; three attempts failed. Reason: a fourth identical attempt almost never succeeds and burns time.
5. **Write down what happened** in PROGRESS.md after every attempt. Reason: it is the only memory that survives a restart.

If rules conflict, the lower number wins (for example rule 2 beats "finish the task").

## Task list format

```markdown
- [ ] Add the /health endpoint | verify: mvn -q test -Dtest=HealthTest
- [ ] Reject empty emails at signup | verify: python -m pytest -q tests/test_signup.py
- [x] Create the project skeleton
- [!] Migrate to Postgres 16 <!-- loop: the same verification failure happened twice in a row -->
```

- `- [ ]` to do, `- [x]` done, `- [!]` blocked (the reason goes in the `<!-- loop: ... -->` comment).
- `| verify: <command>` is the task's own check. A project-wide check (build, lint) may also be given by the user; when both exist, both must pass.
- The checks of tasks already done (`- [x]`) must stay green: run them again after each task. Do not re-run the checks of blocked tasks; they are expected to fail.
- No verify command at all: ask the user for one before starting. Do not invent "verified by reading the code".

## Procedure

1. **Resume first.** Read PROGRESS.md (last 10 lines) and TASKS.md. Continue with the first `- [ ]` task; never redo a `- [x]` task.
2. **Run the verify command(s) once before changing anything.** Already green: an earlier task did this work; mark it done and log `DONE: <task> (attempt 1, already satisfied: verify green with no change)`. Otherwise **do the task** with the smallest correct change.
3. **Run the verify command(s)** exactly as written, from the project root, then the checks of the tasks already done.
4. **Green:** change `- [ ]` to `- [x]`, append `- <date time> DONE: <task> (attempt N)` to PROGRESS.md, and commit if the project uses git (`agent-task-loop: <task>`).
5. **Red:** append `- <date time> FAILED attempt N: <task> (verify exit <code>)`. Read the end of the output, find the root cause, then retry with a different approach. Do not repeat a change that already failed.
6. **Block** when rule 4 applies: write `- [!] <task> <!-- loop: <reason> -->`, append `BLOCKED: <task> - <reason>` to PROGRESS.md, tell the user in one line, and continue with the next task.
7. **End:** append `LOOP END: <n> done, <n> blocked, <n> left` and give the user the same summary, with the blocked tasks and their reasons.

## Example

<example>
Task: "- [ ] Add VAT to invoice totals | verify: python -m pytest -q tests/test_invoice.py"
Attempt 1: totals multiplied by 1.2 → test fails "expected 120.00, got 120.0000001".
Attempt 2 (different approach, root cause = float rounding): use Decimal with 2 places → test passes.
TASKS.md: "- [x] Add VAT to invoice totals | verify: ..."; PROGRESS.md: "FAILED attempt 1 ...", "DONE: Add VAT to invoice totals (attempt 2)".
</example>

<example>
Task: "- [ ] Make slug tests pass | verify: python -m pytest -q tests/test_slug.py"
Two tests expect "hello-world" and "hello_world" for the same title: no change can satisfy both.
Do not edit either test. Block: "- [!] Make slug tests pass <!-- loop: tests contradict each other (hyphen vs underscore) -->", and tell the user which decision is needed.
</example>

## Files

- `loop.py`: runs any command-line agent through TASKS.md with the same rules, without a human (state in `.loop/`, notifications). Read its `--help` only when the user wants unattended runs.
- `templates/TASKS.md`, `templates/loop.config.json`: starting points for Java, Python and .NET projects. Read them when the user has no task list or config yet.
- `README.md`: installation, agent commands, limits and measured results. Read it when the user asks how to install or what has been tested.
