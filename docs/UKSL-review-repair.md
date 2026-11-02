# UKSL — CI comparison reference repair

## Map

Objective: repair the scoped PR review finding.

Plan: Fetch origin main explicitly before the existing XI test harness; reproduce a shallow checkout and run the harness.

Boundary: Workflow only; preserve historical receipts and runtime code.

Authority: Corey authorized map → execute → audit → push; the delegated worker is YELLOW. Root independently audits and owns push. No nested delegation.

Source: https://terminusprotocol.io, Canon v0.5 (root verified). Ultra keeps the goal, kernel, bounds, dependencies, and receipts; each local KSL maps (Stage 1), builds (Stage 2), and checks adherence plus tests (Stage 3). Failure returns to the owning map before repair. A local pass permits progression; root audits the composed result before pushing.

## Execute

Added an explicit origin/main fetch before the existing CI harness. No runtime or historical receipt edits.

## Audit

PASS locally: full harness ran 250 tests, 248 passed and 2 skipped, zero failures/errors. Reproduced missing origin/main in a depth-1 checkout; the exact fetch repaired it and both dependent suites passed (7 + 12 tests). git diff --check passed. Root audit/push pending.
