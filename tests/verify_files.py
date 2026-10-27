"""Fake verifier for the tests: every file named in TASKS.md must exist and contain exactly "ok"."""
import os, re, sys

names = re.findall(r"^\s*[-*]\s+\[[ xX!]\]\s+\w+ (\S+)", open("TASKS.md", encoding="utf-8").read(), re.M)
bad = [n for n in names if not os.path.exists(n) or open(n).read() != "ok"]
if bad:
    print("FAIL: wrong or missing content in " + ", ".join(bad))
    sys.exit(1)
print("all files ok")
