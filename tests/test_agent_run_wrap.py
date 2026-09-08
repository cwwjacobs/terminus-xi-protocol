"""Agent-run wrap spike: Tester's table against the failing fixture trace."""

from __future__ import annotations

import ast
import copy
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

import _support  # noqa: F401
from _support import FrozenClock, REPO_ROOT  # noqa: E402

from terminus_xi.canonical import read_json, sha256_canonical, write_json  # noqa: E402
from terminus_xi.engine import verify_artifact  # noqa: E402
from terminus_xi.receipt import verify_receipt  # noqa: E402

from terminus_agent_wrap.checks import REQUIRED_KINDS  # noqa: E402
from terminus_agent_wrap.export import STATUS_EXPORTED, STATUS_STUBBED  # noqa: E402
from terminus_agent_wrap.prune import PruneRefused, prune_run_dir  # noqa: E402
from terminus_agent_wrap.wrap import (  # noqa: E402
    admit_run_artifact,
    default_contract_set,
    default_policy,
    wrap_run,
)

WRAP_ROOT = REPO_ROOT / "src" / "terminus_agent_wrap"
DEMO_ROOT = REPO_ROOT / "demos" / "agent-run-wrap"
XI_ROOT = REPO_ROOT / "src" / "terminus_xi"
CLOCK = "2026-09-08T12:00:00Z"

_FORBIDDEN_IMPORTS = frozenset(
    {
        "anthropic",
        "openai",
        "httpx",
        "requests",
        "aiohttp",
        "mcp",
        "socket",
        "http.client",
        "urllib.request",
        "websocket",
        "sseclient",
    }
)


def load_demo_fixture():
    path = DEMO_ROOT / "fixture.py"
    spec = importlib.util.spec_from_file_location("agent_run_wrap_demo_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load fixture from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def failing_events():
    return load_demo_fixture().synthesize_failing_multi_step_trace()


def wrap_fixture(scratch: Path, events=None):
    with FrozenClock(CLOCK):
        return wrap_run(events if events is not None else failing_events(), scratch_root=scratch)


def _python_files(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend(
            path for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts
        )
    return files


def _imported_modules(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
            names.add(node.module)
    return names


def _attr_names(tree: ast.AST) -> set[str]:
    return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def _imported_from(tree: ast.AST, module: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names.update(alias.name for alias in node.names)
    return names


class TestAgentRunWrap(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix="agent-wrap-"))

    def test_fixture_is_a_failing_multi_step_trace_with_one_canned_decision(self):
        fixture = load_demo_fixture()
        events = fixture.synthesize_failing_multi_step_trace()
        kinds = [event["kind"] for event in events]
        self.assertGreaterEqual(len(events), 5)
        self.assertIn("tool_call", kinds)
        self.assertIn("tool_result", kinds)
        self.assertTrue(any(event["status"] == "error" for event in events))
        decisions = [event for event in events if event["kind"] == "decision"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["name"], fixture.CANNED_DECISION_NAME)
        self.assertEqual(decisions[0]["status"], fixture.CANNED_DECISION_STATUS)
        for event in events:
            self.assertNotIn("args", event)
            self.assertNotIn("result", event)
            self.assertEqual(event["ts_utc"], fixture.fixture_ts(event["seq"]))

    def test_wrap_emits_the_package_layout_and_admits_the_well_formed_trace(self):
        wrapped = wrap_fixture(self.scratch)
        self.assertEqual(wrapped.admission, "ADMIT")
        self.assertTrue(wrapped.admitted)
        self.assertTrue(wrapped.run_id.startswith("run_"))
        self.assertEqual(wrapped.artifact["outcome"]["status"], "failed")
        for name in ("events.jsonl", "run-artifact.json", "receipt.json", "MANIFEST.json"):
            self.assertTrue((wrapped.directory / name).is_file(), name)
        self.assertEqual(wrapped.drive_export["status"], STATUS_STUBBED)
        artifact = read_json(wrapped.directory / "run-artifact.json")
        self.assertEqual(artifact["schema"], "terminus-agent-wrap.run-artifact.v1")
        self.assertEqual(artifact["boundary_id"], "agent.run.v1")
        self.assertEqual(wrapped.receipt["schema"], "terminus-xi.receipt.v2")
        self.assertEqual(wrapped.receipt["admission"], "ADMIT")

    def test_determinism_under_fixed_terminus_xi_now(self):
        first = wrap_fixture(self.scratch / "a")
        second = wrap_fixture(self.scratch / "b")
        self.assertEqual(first.events_sha256, second.events_sha256)
        self.assertEqual(first.artifact_sha256, second.artifact_sha256)
        self.assertEqual(
            first.receipt["stable_core_sha256"],
            second.receipt["stable_core_sha256"],
        )
        self.assertEqual(sha256_canonical(first.artifact), sha256_canonical(second.artifact))

    def test_drop_decision_kind_still_admits(self):
        """decision is fixture-synthetic and allowed, not a protocol invariant."""
        events = [event for event in failing_events() if event["kind"] != "decision"]
        self.assertTrue(any(event["kind"] == "tool_result" for event in events))
        wrapped = wrap_fixture(self.scratch, events)
        self.assertEqual(wrapped.admission, "ADMIT")
        self.assertNotIn("decision", [event["kind"] for event in wrapped.events])

    def test_drop_required_kind_is_not_admitted(self):
        events = [event for event in failing_events() if event["kind"] != "tool_result"]
        wrapped = wrap_fixture(self.scratch, events)
        self.assertNotEqual(wrapped.admission, "ADMIT")
        self.assertEqual(wrapped.admission, "REJECT")
        blocking = wrapped.outcome.decision.blocking_codes
        self.assertIn("EVIDENCE_INCOMPLETE", blocking)

    def test_corrupt_digest_is_not_admitted(self):
        wrapped = wrap_fixture(self.scratch)
        malformed = copy.deepcopy(dict(wrapped.artifact))
        malformed["events_sha256"] = "f" * 64
        with FrozenClock(CLOCK):
            outcome = admit_run_artifact(malformed)
        self.assertNotEqual(outcome.admission, "ADMIT")
        self.assertEqual(outcome.admission, "REJECT")
        self.assertIn("HASH_MISMATCH", outcome.decision.blocking_codes)

        events = failing_events()
        events[1] = dict(events[1])
        events[1]["args_sha256"] = "not-a-digest"
        corrupt_line = wrap_fixture(self.scratch / "corrupt-line", events)
        self.assertNotEqual(corrupt_line.admission, "ADMIT")
        self.assertEqual(corrupt_line.admission, "REJECT")
        self.assertIn("INPUT_SHAPE_INVALID", corrupt_line.outcome.decision.blocking_codes)

    def test_replay_verify_receipt_on_written_receipt_passes(self):
        wrapped = wrap_fixture(self.scratch)
        receipt = read_json(wrapped.directory / "receipt.json")
        verification = verify_receipt(receipt, artifact_sha256=wrapped.artifact_sha256)
        self.assertTrue(verification.ok, verification.errors)
        self.assertEqual(verification.admission, "ADMIT")

    def test_admit_path_is_engine_verify_artifact_only(self):
        found_verify = False
        for path in _python_files(WRAP_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = _imported_modules(tree)
            self.assertNotIn("terminus_xi.receipt.build_receipt", imported)
            self.assertNotIn("build_receipt", _imported_from(tree, "terminus_xi.receipt"))
            self.assertNotIn("decide", _imported_from(tree, "terminus_xi.admission"))
            self.assertNotIn("build_receipt", _attr_names(tree))
            if path.name == "wrap.py":
                self.assertIn("verify_artifact", _imported_from(tree, "terminus_xi.engine"))
                found_verify = True
                source = path.read_text(encoding="utf-8")
                self.assertIn("verify_artifact(", source)
                self.assertNotIn("build_receipt(", source)
        self.assertTrue(found_verify)
        self.assertEqual(admit_run_artifact.__globals__["verify_artifact"], verify_artifact)

    def test_prune_refuses_stubbed_export_and_sha_mismatch(self):
        wrapped = wrap_fixture(self.scratch)
        with self.assertRaises(PruneRefused) as stubbed:
            prune_run_dir(wrapped.directory)
        self.assertIn("stubbed", str(stubbed.exception).lower())
        self.assertTrue(wrapped.directory.is_dir())

        mismatch = {
            "schema": "terminus-agent-wrap.drive-export.v1",
            "status": STATUS_EXPORTED,
            "run_id": wrapped.run_id,
            "sha256": "a" * 64,
        }
        write_json(wrapped.directory / "drive_export.json", mismatch)
        with self.assertRaises(PruneRefused) as mismatched:
            prune_run_dir(wrapped.directory)
        self.assertIn("match", str(mismatched.exception).lower())
        self.assertTrue(wrapped.directory.is_dir())

        matching = dict(mismatch)
        matching["sha256"] = wrapped.artifact_sha256
        write_json(wrapped.directory / "drive_export.json", matching)
        prune_run_dir(wrapped.directory)
        self.assertFalse(wrapped.directory.exists())

    def test_no_live_hook_in_wrapper_or_demo_python(self):
        for path in _python_files(WRAP_ROOT, DEMO_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = _imported_modules(tree)
            overlap = imported & _FORBIDDEN_IMPORTS
            self.assertEqual(overlap, set(), f"{path} imports {sorted(overlap)}")
        fixture = load_demo_fixture()
        self.assertIn("fixture.synthetic", fixture.CANNED_DECISION_NAME)

    def test_freeze_zero_edits_under_terminus_xi(self):
        for path in _python_files(XI_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = _imported_modules(tree)
            self.assertNotIn("terminus_agent_wrap", imported)
            self.assertFalse(any(name.startswith("terminus_agent_wrap") for name in imported))
        diffs = subprocess.check_output(
            ["git", "diff", "--name-only", "origin/main", "--", "src/terminus_xi"],
            cwd=REPO_ROOT,
            text=True,
        )
        staged = subprocess.check_output(
            ["git", "diff", "--name-only", "--cached", "--", "src/terminus_xi"],
            cwd=REPO_ROOT,
            text=True,
        )
        self.assertEqual(diffs.strip(), "", diffs)
        self.assertEqual(staged.strip(), "", staged)
        self.assertTrue(WRAP_ROOT.is_dir())
        self.assertFalse(WRAP_ROOT.is_relative_to(XI_ROOT) if hasattr(WRAP_ROOT, "is_relative_to") else str(WRAP_ROOT).startswith(str(XI_ROOT)))

    def test_contracts_live_outside_the_freeze_set(self):
        freeze_contracts = REPO_ROOT / "contracts"
        for path in WRAP_ROOT.rglob("*.json"):
            self.assertFalse(path.is_relative_to(freeze_contracts))
        self.assertTrue((WRAP_ROOT / "contracts" / "agent-run.contracts.json").is_file())
        self.assertTrue((WRAP_ROOT / "policies" / "agent-run.policy.json").is_file())
        self.assertTrue(default_contract_set().contracts)
        self.assertEqual(default_policy().on_warn, "REVIEW")
        kinds_contract = next(
            contract for contract in default_contract_set().contracts
            if contract.check_id == "agent_wrap.required_kinds"
        )
        self.assertEqual(tuple(kinds_contract.config["kinds"]), REQUIRED_KINDS)
        self.assertNotIn("decision", kinds_contract.config["kinds"])
        self.assertEqual(REQUIRED_KINDS, ("run_start", "tool_call", "tool_result", "run_end"))


if __name__ == "__main__":
    unittest.main()
