"""Tests of loop.py with a deterministic fake agent and verifier. Run: python -m unittest discover -s tests"""
import os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import loop  # noqa: E402

AGENT = f'"{sys.executable}" "{os.path.join(HERE, "fake_agent.py")}" "{{prompt_file}}"'


def verify_cmd(only=None):
    """Verifier that checks only the files of the given tasks (or all files of TASKS.md)."""
    if only is None:
        return f'"{sys.executable}" "{os.path.join(HERE, "verify_files.py")}"'
    names = " ".join(only)
    code = ("import sys,os;n=sys.argv[1:];bad=[x for x in n if not os.path.exists(x) or open(x).read()!='ok'];"
            "print('FAIL '+','.join(bad) if bad else 'ok');sys.exit(1 if bad else 0)")
    return f'"{sys.executable}" -c "{code}" {names}'


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="atl_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def tasks(self, *lines, per_task_verify=True):
        """Each task gets its own check (the file it creates must contain "ok"), like a real per-task test."""
        def line(l):
            name = l.split()[1]
            return f"- [ ] {l} | verify: {verify_cmd([name])}" if per_task_verify else f"- [ ] {l}"
        with open(os.path.join(self.root, "TASKS.md"), "w", encoding="utf-8") as f:
            f.write("# Tasks\n\n" + "\n".join(line(l) for l in lines) + "\n")

    def statuses(self):
        _, t = loop.read_tasks(os.path.join(self.root, "TASKS.md"))
        return [s for _, s, _ in t]

    def run_loop(self, verify="", *extra):
        return loop.main(["--root", self.root, "--agent", AGENT, "--verify", verify, "--notify", "file", *extra])

    def test_all_tasks_done_in_order(self):
        self.tasks("create a.txt", "create b.txt", "create c.txt")
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.statuses(), ["x", "x", "x"])
        progress = open(os.path.join(self.root, "PROGRESS.md"), encoding="utf-8").read()
        self.assertIn("DONE: create a.txt", progress)
        self.assertIn("LOOP END: 3 done, 0 blocked, 0 left", progress)

    def test_retry_with_failure_then_success(self):
        self.tasks("second a.txt")
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.statuses(), ["x"])
        self.assertIn("(attempt 2)", open(os.path.join(self.root, "PROGRESS.md"), encoding="utf-8").read())

    def test_retry_prompt_contains_failure(self):
        self.tasks("second a.txt")
        self.run_loop()
        prompt = open(os.path.join(self.root, ".loop", "prompt.md"), encoding="utf-8").read()
        self.assertIn("Attempt 2", prompt)
        self.assertIn("FAIL", prompt)

    def test_same_failure_twice_blocks_early(self):
        self.tasks("stubborn a.txt", "create b.txt")
        self.assertEqual(self.run_loop(verify_cmd(["a.txt"]), "--max-attempts", "5"), 1)
        st = self.statuses()
        self.assertEqual(st[0], "!")          # blocked after 2 identical failures, not 5 attempts
        self.assertEqual(open(os.path.join(self.root, ".loop", "fake_a.txt.runs")).read(), "2")
        self.assertIn("same verification failure", open(os.path.join(self.root, "TASKS.md"), encoding="utf-8").read())

    def test_no_change_blocks(self):
        self.tasks("noop a.txt")
        self.assertEqual(self.run_loop("", "--max-attempts", "5"), 1)
        self.assertEqual(self.statuses(), ["!"])
        self.assertIn("changed nothing", open(os.path.join(self.root, "TASKS.md"), encoding="utf-8").read())

    def test_continue_after_block_and_stop_on_block(self):
        self.tasks("noop a.txt", "create b.txt")
        self.run_loop(verify_cmd(["b.txt"]))
        self.assertEqual(self.statuses(), ["!", "x"])
        os.remove(os.path.join(self.root, "b.txt"))
        shutil.rmtree(os.path.join(self.root, ".loop"))
        self.tasks("noop a.txt", "create b.txt")
        self.run_loop(verify_cmd(["b.txt"]), "--stop-on-block")
        self.assertEqual(self.statuses(), ["!", " "])

    def test_resume_keeps_done_tasks(self):
        self.tasks("create a.txt", "create b.txt")
        self.run_loop()
        with open(os.path.join(self.root, "TASKS.md"), "a", encoding="utf-8") as f:
            f.write(f"- [ ] create c.txt | verify: {verify_cmd(['c.txt'])}\n")
        self.run_loop()
        self.assertEqual(self.statuses(), ["x", "x", "x"])
        self.assertEqual(open(os.path.join(self.root, ".loop", "fake_a.txt.runs")).read(), "1")  # not redone

    def test_global_verify_also_required(self):
        self.tasks("create a.txt")
        fail = f'"{sys.executable}" -c "import sys; print(1); sys.exit(1)"'
        self.assertEqual(self.run_loop(fail, "--max-attempts", "2"), 1)
        self.assertEqual(self.statuses(), ["!"])

    def test_global_verify_alone(self):
        self.tasks("create a.txt", per_task_verify=False)
        self.assertEqual(self.run_loop(verify_cmd(["a.txt"])), 0)
        self.assertEqual(self.statuses(), ["x"])

    def test_config_file(self):
        import json
        self.tasks("create a.txt")
        with open(os.path.join(self.root, "loop.config.json"), "w", encoding="utf-8") as f:
            json.dump({"_comment": "test", "agent": AGENT, "notify": "file", "max-attempts": 2}, f)
        self.assertEqual(loop.main(["--root", self.root]), 0)
        self.assertEqual(self.statuses(), ["x"])

    def test_config_file_rejects_unknown_option(self):
        import json
        with open(os.path.join(self.root, "loop.config.json"), "w", encoding="utf-8") as f:
            json.dump({"agent": AGENT, "verfy": "x"}, f)
        with self.assertRaises(SystemExit):
            loop.main(["--root", self.root])

    def test_already_satisfied_task_is_done_not_blocked(self):
        self.tasks("create a.txt", "noop a.txt")   # the second task is already satisfied by the first
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.statuses(), ["x", "x"])
        with open(os.path.join(self.root, "PROGRESS.md"), encoding="utf-8") as f:
            self.assertIn("already satisfied", f.read())

    def test_prompt_names_the_verify_command(self):
        self.tasks("create a.txt")
        self.run_loop()
        with open(os.path.join(self.root, ".loop", "prompt.md"), encoding="utf-8") as f:
            prompt = f.read()
        self.assertIn("The verifier will run:", prompt)
        self.assertIn("a.txt", prompt.split("The verifier will run:")[1])

    def test_regression_of_a_done_task_is_caught(self):
        self.tasks("create a.txt", "clobber b.txt")   # b's own check passes, but the first run breaks a.txt
        self.assertEqual(self.run_loop(), 0)
        self.assertEqual(self.statuses(), ["x", "x"])
        with open(os.path.join(self.root, "PROGRESS.md"), encoding="utf-8") as f:
            self.assertIn("DONE: clobber b.txt (attempt 2)", f.read())
        with open(os.path.join(self.root, ".loop", "prompt.md"), encoding="utf-8") as f:
            self.assertIn("regression check of an earlier task", f.read())

    def test_blocked_task_is_not_rechecked_by_later_tasks(self):
        self.tasks("stubborn a.txt", "create b.txt", "create c.txt")   # a.txt stays wrong
        self.assertEqual(self.run_loop(), 1)
        self.assertEqual(self.statuses(), ["!", "x", "x"])            # no cascade of failures

    def test_agent_failure_pauses_the_loop_without_blocking_tasks(self):
        self.tasks("crash a.txt", "create b.txt")
        self.assertEqual(self.run_loop("", "--agent-error-wait", "0"), 3)
        self.assertEqual(self.statuses(), [" ", " "])   # nothing burnt: running again resumes on a.txt
        self.assertEqual(open(os.path.join(self.root, ".loop", "fake_a.txt.runs")).read(), "3")
        progress = open(os.path.join(self.root, "PROGRESS.md"), encoding="utf-8").read()
        self.assertIn("AGENT ERROR 3 (exit 1): crash a.txt - API Error: 402 credits exhausted", progress)
        self.assertIn("LOOP PAUSED", progress)

    def test_agent_failure_does_not_cost_an_attempt(self):
        self.tasks("flaky a.txt")
        self.assertEqual(self.run_loop("", "--agent-error-wait", "0", "--max-attempts", "1"), 0)
        self.assertEqual(self.statuses(), ["x"])
        self.assertIn("DONE: flaky a.txt (attempt 1)", open(os.path.join(self.root, "PROGRESS.md"), encoding="utf-8").read())

    def test_split_verify(self):
        self.assertEqual(loop.split_verify("Add login | verify: pytest -q tests/x.py"), ("Add login", "pytest -q tests/x.py"))
        self.assertEqual(loop.split_verify("Plain task"), ("Plain task", ""))
        self.assertEqual(loop.split_verify("T | verify: make test <!-- loop: x -->"), ("T", "make test"))

    def test_notification_file(self):
        self.tasks("create a.txt")
        self.run_loop()
        notes = open(os.path.join(self.root, ".loop", "NOTIFICATIONS.txt"), encoding="utf-8").read()
        self.assertIn("agent-task-loop finished: 1 done, 0 blocked, 0 left", notes)

    def test_parse_ignores_non_tasks(self):
        p = os.path.join(self.root, "TASKS.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write("# Title\nsome text\n- not a task\n- [x] done one\n* [ ] todo two\n- [!] blocked three\n")
        _, t = loop.read_tasks(p)
        self.assertEqual([(s, x) for _, s, x in t], [("x", "done one"), (" ", "todo two"), ("!", "blocked three")])

    def test_git_commit_per_task(self):
        if shutil.which("git") is None:
            self.skipTest("git not installed")
        subprocess.run(["git", "init", "-q"], cwd=self.root)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=self.root)
        subprocess.run(["git", "config", "user.name", "test"], cwd=self.root)
        self.tasks("create a.txt", "create b.txt")
        self.run_loop("", "--git")
        log = subprocess.run(["git", "log", "--oneline"], cwd=self.root, capture_output=True, text=True).stdout
        self.assertEqual(log.count("agent-task-loop:"), 2)


if __name__ == "__main__":
    unittest.main()
