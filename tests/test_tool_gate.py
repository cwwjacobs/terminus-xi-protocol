"""Track B wrap-side pre-tool kill-switch: Tester's seven gates."""

from __future__ import annotations

import ast
import inspect
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import _support  # noqa: F401
from _support import FrozenClock, REPO_ROOT  # noqa: E402

from terminus_xi.engine import verify_artifact  # noqa: E402

from terminus_agent_wrap.gate import (  # noqa: E402
    ALLOW,
    HALT,
    HALT_CODE,
    evaluate_tool_proposal,
)
from terminus_agent_wrap.plan import execute_plan  # noqa: E402
from terminus_agent_wrap.wrap import (  # noqa: E402
    admit_run_artifact,
    default_contract_set,
    default_policy,
    wrap_run,
)

from test_agent_run_wrap import (  # noqa: E402
    DEMO_ROOT,
    WRAP_ROOT,
    XI_ROOT,
    _imported_from,
    _imported_modules,
    _python_files,
    load_demo_fixture,
)

CLOCK = "2026-09-08T12:00:00Z"

_POLICY_LEAKS = (
    "allowed_names",
    "DEFAULT_ALLOWED_NAMES",
    "SealedToolPolicy",
    "default-deny",
    "default_deny",
    "allowlist",
    "HALT unless",
    "not on the allow",
    "not allowlisted",
)

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


def _hostile_plan():
    return load_demo_fixture().synthesize_injected_hostile_plan()


def _package_text(directory: Path) -> str:
    chunks: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def _wrap_hostile(*, gate_disabled: bool = False) -> object:
    fixture = load_demo_fixture()
    scratch = Path(tempfile.mkdtemp(prefix="agent-wrap-gate-"))
    with FrozenClock(CLOCK):
        return wrap_run(
            plan=fixture.synthesize_injected_hostile_plan(),
            gate_disabled=gate_disabled,
            scratch_root=scratch,
            agent={
                "id": "demos.agent-run-wrap.injected-hostile",
                "kind": "fixture-synthetic",
                "version": "1",
            },
            config={
                "fixture_id": "injected-hostile-plan-v1",
                "event_timestamps": "fixture-fixed",
                "live_hooks": False,
            },
        )


def _gate_disabled_true_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "gate_disabled":
            value = node.value
            if isinstance(value, ast.Constant) and value.value is True:
                hits.append(node.lineno)
        if isinstance(node, ast.FunctionDef):
            defaults = node.args.defaults
            args = node.args.args
            # positional-or-keyword defaults pair from the right
            for arg, default in zip(args[-len(defaults) :], defaults) if defaults else []:
                if arg.arg == "gate_disabled" and isinstance(default, ast.Constant) and default.value is True:
                    hits.append(arg.lineno)
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                if (
                    arg.arg == "gate_disabled"
                    and default is not None
                    and isinstance(default, ast.Constant)
                    and default.value is True
                ):
                    hits.append(arg.lineno)
    return hits


class TestToolGate(unittest.TestCase):
    def test_1_opaque_policy_text_never_in_prompts_or_events(self):
        wrapped = _wrap_hostile()
        text = _package_text(wrapped.directory)
        events_text = json.dumps(list(wrapped.events), sort_keys=True)
        combined = text + "\n" + events_text
        for leak in _POLICY_LEAKS:
            self.assertNotIn(leak, combined, leak)
        fixture = load_demo_fixture()
        self.assertNotIn(fixture.HOSTILE_RAW_ARGS["command"], combined)
        self.assertNotIn("rm -rf", combined)
        self.assertFalse(list(wrapped.directory.glob("*prompt*")))
        self.assertFalse(any(path.name.startswith("prompt") for path in wrapped.directory.iterdir()))
        for event in wrapped.events:
            self.assertNotIn("args", event)
            self.assertNotIn("result", event)
            self.assertNotIn("reason", event)
            self.assertNotIn("policy", event)
            self.assertNotIn("prompt", event)
        self.assertIn(evaluate_tool_proposal("search"), (ALLOW, HALT))
        self.assertIn(evaluate_tool_proposal("injected.exec"), (ALLOW, HALT))

    def test_2_default_deny_unknown_tool_name_halts(self):
        self.assertEqual(evaluate_tool_proposal("search"), ALLOW)
        self.assertEqual(evaluate_tool_proposal("fetch"), ALLOW)
        self.assertEqual(evaluate_tool_proposal("injected.exec"), HALT)
        self.assertEqual(evaluate_tool_proposal("brand.new.injected.tool"), HALT)
        self.assertEqual(evaluate_tool_proposal(""), HALT)
        # Deny-list-only would miss novel names; default-deny must not.
        self.assertEqual(
            evaluate_tool_proposal("totally.unseen." + "x" * 8),
            HALT,
        )
        allowed = execute_plan(
            [{"name": "search", "args": {"query": "x"}, "args_redacted": {"query": "<redacted>"}}]
        )
        self.assertFalse(allowed.halted)
        self.assertEqual(allowed.side_effects[0]["name"], "search")
        self.assertFalse(allowed.side_effects[0]["harm"])

    def test_3_halt_before_harm_injected_plan_stops_before_side_effect(self):
        wrapped = _wrap_hostile()
        self.assertTrue(wrapped.halted)
        self.assertFalse(any(entry.get("harm") for entry in wrapped.side_effects))
        kinds = [event["kind"] for event in wrapped.events]
        self.assertEqual(kinds[0], "run_start")
        self.assertIn("error", kinds)
        self.assertEqual(kinds[-1], "run_end")
        self.assertNotIn("tool_call", kinds)
        self.assertNotIn("tool_result", kinds)
        halt_events = [
            event
            for event in wrapped.events
            if HALT_CODE in event["codes"]
        ]
        self.assertEqual(len(halt_events), 1)
        self.assertEqual(halt_events[0]["kind"], "error")
        self.assertEqual(halt_events[0]["status"], "halted")
        self.assertNotIn(
            load_demo_fixture().HOSTILE_TOOL_NAME,
            [event["name"] for event in wrapped.events],
        )

    def test_4_control_gate_disabled_test_only_shows_harm_would_have_run(self):
        wrapped = _wrap_hostile(gate_disabled=True)
        self.assertFalse(wrapped.halted)
        self.assertTrue(any(entry.get("harm") for entry in wrapped.side_effects))
        names = [event["name"] for event in wrapped.events]
        self.assertIn(load_demo_fixture().HOSTILE_TOOL_NAME, names)
        self.assertIn("tool_call", [event["kind"] for event in wrapped.events])
        self.assertIn("tool_result", [event["kind"] for event in wrapped.events])
        # Same fixture, gate on: harm does not run.
        halted = execute_plan(_hostile_plan())
        self.assertTrue(halted.halted)
        self.assertFalse(any(entry.get("harm") for entry in halted.side_effects))

    def test_5_receipt_non_admit_via_verify_artifact_after_halt(self):
        wrapped = _wrap_hostile()
        self.assertNotEqual(wrapped.admission, "ADMIT")
        self.assertFalse(wrapped.admitted)
        artifact = json.loads((wrapped.directory / "run-artifact.json").read_text(encoding="utf-8"))
        with FrozenClock(CLOCK):
            replay = verify_artifact(
                artifact,
                boundary_id=str(artifact["boundary_id"]),
                contract_set=default_contract_set(),
                policy=default_policy(),
            )
        self.assertIs(admit_run_artifact.__globals__["verify_artifact"], verify_artifact)
        self.assertNotEqual(replay.admission, "ADMIT")
        self.assertIn("EVIDENCE_INCOMPLETE", replay.decision.blocking_codes)

    def test_6_freeze_zero_terminus_xi_edits(self):
        for path in _python_files(XI_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = _imported_modules(tree)
            self.assertNotIn("terminus_agent_wrap", imported)
            self.assertFalse(any(name.startswith("terminus_agent_wrap") for name in imported))
        for args in (
            ["git", "diff", "--name-only", "origin/main", "--", "src/terminus_xi"],
            ["git", "diff", "--name-only", "--cached", "--", "src/terminus_xi"],
            ["git", "diff", "--name-only", "HEAD", "--", "src/terminus_xi"],
        ):
            diff = subprocess.check_output(args, cwd=REPO_ROOT, text=True)
            self.assertEqual(diff.strip(), "", diff)
        self.assertTrue(WRAP_ROOT.is_dir())
        self.assertFalse(str(WRAP_ROOT).startswith(str(XI_ROOT)))

    def test_7_anti_creep_gate_disabled_test_only_no_live_hook_not_a_planner(self):
        signature = inspect.signature(wrap_run)
        self.assertIn("gate_disabled", signature.parameters)
        self.assertIs(signature.parameters["gate_disabled"].default, False)
        self.assertNotIn("gate_disabled", inspect.signature(evaluate_tool_proposal).parameters)

        gate_source = (WRAP_ROOT / "gate.py").read_text(encoding="utf-8")
        self.assertIn("evaluate_tool_proposal", gate_source)
        self.assertNotIn("deny_names", gate_source)
        self.assertNotIn("DENIED", gate_source)
        self.assertNotIn("build_receipt", (WRAP_ROOT / "gate.py").read_text(encoding="utf-8"))
        self.assertNotIn("decide(", gate_source)

        demo_run = (DEMO_ROOT / "run.py").read_text(encoding="utf-8")
        self.assertNotIn("gate_disabled", demo_run)
        self.assertNotIn("--gate-disabled", demo_run)

        for path in _python_files(WRAP_ROOT, DEMO_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            overlap = _imported_modules(tree) & _FORBIDDEN_IMPORTS
            self.assertEqual(overlap, set(), f"{path} imports {sorted(overlap)}")
            self.assertNotIn("build_receipt", _imported_from(tree, "terminus_xi.receipt"))
            self.assertNotIn("decide", _imported_from(tree, "terminus_xi.admission"))
            self.assertEqual(_gate_disabled_true_lines(path), [], f"{path} sets gate_disabled=True")

        # The gate returns ALLOW|HALT; it does not emit a tool sequence.
        self.assertEqual(evaluate_tool_proposal("search"), ALLOW)
        self.assertEqual(evaluate_tool_proposal("injected.exec"), HALT)
        self.assertNotIsInstance(evaluate_tool_proposal("search"), list)


if __name__ == "__main__":
    unittest.main()
