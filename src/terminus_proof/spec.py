"""Demo specification loading.

A spec declares identity and intent. It never declares a result: nothing in the
emitted package is taken from the spec's opinion of how the run should turn out,
only from what the arms recorded and what XI decided about it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from terminus_xi.canonical import read_json, sha256_canonical
from terminus_xi.schemas import SchemaError, validate_against

__all__ = ["DemoSpec", "SpecError", "load_spec"]


class SpecError(ValueError):
    """The demo specification is malformed or points at something missing."""


@dataclass(frozen=True)
class DemoSpec:
    document: Mapping[str, Any]
    path: Path
    root: Path

    @property
    def demo_id(self) -> str:
        return str(self.document["demo_id"])

    @property
    def sha256(self) -> str:
        return sha256_canonical(self.document)

    def resolve(self, relative: str) -> Path:
        """Resolve a spec-relative path against the repository root."""
        candidate = Path(relative)
        path = candidate if candidate.is_absolute() else self.root / candidate
        if not path.exists():
            raise SpecError(
                f"demo spec {self.path.name!r} references {relative!r}, which does not exist"
            )
        return path

    def arm(self, arm_id: str) -> Mapping[str, Any]:
        return self.document["arms"][arm_id]


def load_spec(path: str | Path, *, root: str | Path | None = None) -> DemoSpec:
    spec_path = Path(path).resolve()
    document = read_json(spec_path)
    if not isinstance(document, Mapping):
        raise SpecError("demo spec must be a JSON object")
    if document.get("schema") != "terminus-proof.demo-spec.v1":
        raise SpecError(f"unsupported demo spec schema: {document.get('schema')!r}")
    try:
        validate_against(document, "terminus-proof.demo-spec.v1", label="demo spec")
    except SchemaError as exc:
        raise SpecError(str(exc)) from exc

    for arm_id in ("baseline", "augmented"):
        declared = document["arms"][arm_id]["arm_id"]
        if declared != arm_id:
            raise SpecError(
                f"arm {arm_id!r} declares arm_id {declared!r}; the two must agree"
            )

    changed = document["changed_variable"]
    if changed["baseline_value"] == changed["augmented_value"]:
        raise SpecError(
            f"changed variable {changed['name']!r} declares the same value for both arms; "
            "a proof spec must make the intended changed variable explicit"
        )

    resolved_root = Path(root).resolve() if root is not None else _default_root(spec_path)
    return DemoSpec(document=document, path=spec_path, root=resolved_root)


def _default_root(spec_path: Path) -> Path:
    """Walk up from the spec until a directory holding ``spec/`` is found."""
    for candidate in [spec_path.parent, *spec_path.parents]:
        if (candidate / "spec").is_dir() and (candidate / "contracts").is_dir():
            return candidate
    return spec_path.parent
