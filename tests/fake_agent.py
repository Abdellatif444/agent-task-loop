"""Deterministic fake agent for the tests. It reads the prompt file and acts on the task text:
  "create NAME"   -> writes NAME with content "ok"
  "second NAME"   -> first run writes "bad", second run writes "ok"
  "stubborn NAME" -> always writes "bad" plus a run counter (files change, the same failure repeats)
  "noop NAME"     -> changes nothing
  "clobber NAME"  -> writes NAME "ok"; on its first run it also breaks a.txt (a regression), then repairs it
  "crash NAME"    -> exits 1 and changes nothing, like an agent out of quota
  "flaky NAME"    -> first run like "crash", then writes NAME "ok"
"""
import os, re, sys

prompt = open(sys.argv[1], encoding="utf-8").read()
task = re.search(r"Current task: (\w+) (\S+)", prompt)
verb, name = task.group(1), task.group(2)
os.makedirs(".loop", exist_ok=True)
counter = os.path.join(".loop", "fake_" + name + ".runs")   # outside the watched tree, like an agent's own memory
runs = int(open(counter).read()) + 1 if os.path.exists(counter) else 1
open(counter, "w").write(str(runs))
if verb == "create":
    open(name, "w").write("ok")
elif verb == "second":
    open(name, "w").write("ok" if runs >= 2 else "bad")
elif verb == "clobber":
    open(name, "w").write("ok")
    open("a.txt", "w").write("bad" if runs == 1 else "ok")
elif verb == "crash" or (verb == "flaky" and runs == 1):
    print("API Error: 402 credits exhausted")
    sys.exit(1)
elif verb == "flaky":
    open(name, "w").write("ok")
elif verb == "stubborn":
    open(name, "w").write(f"bad {runs}")
print(f"fake agent: {verb} {name} run {runs}")
