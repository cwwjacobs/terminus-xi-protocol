"""Shared test fixtures.

The canonical proof is expensive to build (it shells out to ffmpeg seven
times), so it is built once per test process and reused. Tests that mutate a
package copy it first.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEMO_SPEC = REPO_ROOT / "demos" / "claim-boundary-audit.demo.json"
NEGATIVE_DEMOS = sorted((REPO_ROOT / "demos" / "negative").glob("*.demo.json"))

_CACHE: dict[str, Any] = {}


def selftest_artifact() -> dict[str, Any]:
    return {"kind": "selftest", "records": [{"id": "a"}, {"id": "b"}]}


def selftest_contracts():
    from terminus_xi.contracts import load_contract_set

    return load_contract_set(REPO_ROOT / "contracts" / "xi-selftest.contracts.json")


def selftest_policy():
    from terminus_xi.admission import load_policy

    return load_policy(REPO_ROOT / "policies" / "xi-selftest.policy.json")


def build_canonical_proof(*, render: bool = True):
    """Build the canonical demo once and cache the resulting directory."""
    key = f"proof-{render}"
    if key in _CACHE:
        return _CACHE[key]

    from terminus_proof.engine import build_proof
    from terminus_proof.package import write_package
    from terminus_proof.spec import load_spec

    out_root = Path(tempfile.mkdtemp(prefix="terminus-proof-tests-"))
    spec = load_spec(DEMO_SPEC)
    build = build_proof(spec)
    result = write_package(build, out_root=out_root, render=render)
    _CACHE[key] = (build, result, out_root)
    return _CACHE[key]


def copy_proof(directory: Path) -> Path:
    """Copy a built proof so a test can tamper with it in isolation."""
    target = Path(tempfile.mkdtemp(prefix="terminus-proof-copy-")) / directory.name
    shutil.copytree(directory, target)
    return target


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


class FrozenClock:
    """Context manager pinning ``TERMINUS_XI_NOW``."""

    def __init__(self, value: str) -> None:
        self.value = value
        self._previous: str | None = None

    def __enter__(self) -> "FrozenClock":
        self._previous = os.environ.get("TERMINUS_XI_NOW")
        os.environ["TERMINUS_XI_NOW"] = self.value
        return self

    def __exit__(self, *exc: object) -> None:
        if self._previous is None:
            os.environ.pop("TERMINUS_XI_NOW", None)
        else:
            os.environ["TERMINUS_XI_NOW"] = self._previous
