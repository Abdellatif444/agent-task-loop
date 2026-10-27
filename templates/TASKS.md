# Tasks

<!--
One task per line, in the order they must be done.
Markers: "[ ]" to do, "[x]" done, "[!]" blocked (agent-task-loop writes the reason in a comment).
Give each task its own check with "| verify: <command>" when you can: it must exit 0 only when the task is really done.
After each task, the checks of the tasks already done are run again (regressions); blocked tasks are not.
A project-wide check that must pass after every task (build, lint) goes in loop.config.json ("verify").
Write tasks as small, testable steps: "Add X so that Y" is better than "Improve the app".
-->

## Python (pytest)
- [ ] Add a `slugify(title)` function in `app/text.py` that lowercases and joins words with "-" | verify: python -m pytest -q tests/test_text.py
- [ ] Reject empty email addresses in `create_user` with a ValueError | verify: python -m pytest -q tests/test_users.py

## Java (Maven)
- [ ] Add GET /health returning {"status":"UP"} | verify: mvn -q test -Dtest=HealthControllerTest
- [ ] Validate that order quantity is between 1 and 100 | verify: mvn -q test -Dtest=OrderValidationTest

## .NET
- [ ] Add `Money.Round()` using midpoint "away from zero" | verify: dotnet test --filter FullyQualifiedName~MoneyTests
- [ ] Return 404 instead of 500 when a customer is missing | verify: dotnet test --filter FullyQualifiedName~CustomerApiTests
