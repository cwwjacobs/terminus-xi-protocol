# Test report provenance and count semantics

- File in question: [`receipts/test-report.json`](../receipts/test-report.json)
- Determination: **frozen historical baseline**, recorded 2026-08-31 as the
  observed input to the XI v1 freeze and the UKSL closure. It is not a
  live tracker of HEAD.

## What the file is

`python tools/run_tests.py --report receipts/test-report.json` runs the suite
and writes a machine-readable observation of that run. The freeze receipt and
the UKSL receipt do not trust a claim about tests; they embed a copy of this
observation (`tools/freeze_xi_v1.py --test-report ...`,
`tools/build_uksl_receipt.py --test-report ...`). The checked-in copy is the
observation that fed those two builds.

## Why it is a historical baseline, not HEAD

1. **It is identical to the test blocks embedded in both frozen receipts.**
   [`receipts/xi-v1-freeze-receipt.json`](../receipts/xi-v1-freeze-receipt.json)
   (`created_at_utc` 2026-08-31T02:48:11Z) and
   [`receipts/uksl-receipt.json`](../receipts/uksl-receipt.json)
   (2026-08-31T02:48:47Z) each embed `tests_run: 221, failures: 0, errors: 0,
   skipped: 0, passed: true` — exactly the checked-in report. Those receipts
   are frozen documents; the report is the observation they were built from.
2. **HEAD no longer produces 221.** Running the same command today discovers
   250 tests. A file intended to track HEAD would have been regenerated when
   the suite grew; it was not.
3. **The 29-test delta is exactly the agent-wrap spike.** The three test
   modules that reference `terminus_agent_wrap` —
   `tests/test_agent_run_wrap.py` (12), `tests/test_drive_export.py` (10),
   `tests/test_tool_gate.py` (7) — total 29 tests, and neither frozen receipt
   mentions the agent wrap. 221 (XI v1 + proof engine suite at the freeze) +
   29 (agent wrap, added later) = 250 (HEAD).
4. **Commit provenance is bounded by the public squash.** The public
   repository has a single commit (`424014f`, "Initial public release"), so
   the pre-public tree the report was recorded against is not addressable in
   this clone. The report is instead bound by content to the two receipts
   above, and
   [`receipts/bootstrap-receipt.json`](../receipts/bootstrap-receipt.json)
   names the private bootstrap commit
   `98283c8462d8e9b67b53304da875040c606e5290`.

## Count semantics

The report is produced by `unittest` discovery over `tests/test_*.py`:

- `tests_run` counts every test case that was **started**, including cases
  that were subsequently skipped. It is not a count of tests that ran to
  completion. At HEAD: 250 started = 223 executed + 27 skipped.
- `skipped` counts cases whose skip condition evaluated true (see below).
  Skips are environment gates, not failures, and `passed` remains true with
  skips outstanding.
- `failures` and `errors` count assertion failures and unexpected exceptions.

## Skip reasons

Every skip in the suite is one of two environment gates. Nothing is skipped
by configuration, by v1 contract semantics, or to force a count.

| Gate | Tests at HEAD | Where |
|---|---|---|
| `ffmpeg`/`ffprobe` not on `PATH` (`_support.ffmpeg_available()`) | 25 | `tests/test_proof_verify.py` `TestVerifyAdmittedPackage` (3) and `TestTamperDetection` (17); `tests/test_media_and_docs.py` `TestRenderedMedia` (5) |
| `jsonschema` package not installed (the `dev` extra) | 2 | `tests/test_schema_lite.py` `test_cases_agree_with_jsonschema`, `test_shipped_schemas_are_valid_json_schema` |

The ffmpeg-gated tests build or verify the rendered media of the canonical
proof package; the jsonschema-gated tests cross-check the standard-library
validator against the reference implementation. Both gates are declared in
the test sources as `skipUnless`/`skipIf` with explicit reasons.

## Reconciling the three numbers

| Source | tests_run | skipped | Environment |
|---|---|---|---|
| Checked-in report (2026-08-31) | 221 | 0 | Freeze-time development machine: ffmpeg/ffprobe present (the UKSL receipt's `media_probe` is real `ffprobe` output) and the `jsonschema` dev extra installed, so no gate triggered; agent-wrap tests did not exist yet. |
| CI (ubuntu-latest, Python 3.12) | 250 | 27 | No ffmpeg installed, no `dev` extra installed; all 27 environment-gated tests skip. |
| Local reproduction (2026-09-24) | 250 | 27 | Same gates: no ffmpeg, no `jsonschema`. Suite OK. |

There is no contradiction between the report and CI: they are observations of
different trees (pre-agent-wrap vs HEAD) in different environments (with vs
without ffmpeg and jsonschema). The frozen v1 contract is untouched by this
reconciliation; nothing was skipped or un-skipped to make numbers agree.

## Regenerating

`python tools/run_tests.py --report receipts/test-report.json` overwrites the
file with a fresh observation of the current tree and environment, dropping
the provenance label. That is correct behaviour when building *new* freeze or
UKSL receipts; it is not a way to restate history. The 2026-08-31 observation
remains bound by content to the two frozen receipts regardless of what this
working file later holds.
