"""``terminus-proof`` - build and verify proof packages.

Build and verify are separate operations by design. ``build`` produces a
directory; ``verify`` reads a directory it did not produce and decides whether
it is complete and honest. Nothing is shared between them except the files.

Exit codes
----------
``0``  admitted (build) / verified (verify)
``3``  not admitted, or verification failed
``5``  usage, specification, or adapter failure
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Sequence

from terminus_xi.canonical import canonical_json
from terminus_xi.contracts import ContractError
from terminus_xi.schemas import SchemaError

from . import ENGINE_VERSION
from .adapters import AdapterError, registered_kinds
from .engine import BuildError, build_proof
from .package import verify_package, write_package
from .redaction import RedactionError
from .spec import SpecError, load_spec

__all__ = ["main"]

EXIT_OK = 0
EXIT_NOT_ADMITTED = 3
EXIT_USAGE = 5


def _cmd_build(args: Any, out: Any) -> int:
    spec = load_spec(args.spec, root=args.root)
    build = build_proof(spec)
    out_root = Path(args.out) if args.out else spec.root / "proofs"
    result = write_package(build, out_root=out_root, render=not args.no_media)

    for arm_id in ("baseline", "augmented"):
        outcome = build.arms[arm_id]
        print(f"arm {arm_id:<10} {outcome.admission}", file=sys.stderr)
        for check in outcome.results:
            codes = ",".join(check.codes()) or "-"
            print(f"    {check.verdict:<5} {check.check_id}  [{codes}]", file=sys.stderr)
    print(f"package    {build.admission}", file=sys.stderr)
    for check in build.package.results:
        codes = ",".join(check.codes()) or "-"
        print(f"    {check.verdict:<5} {check.check_id}  [{codes}]", file=sys.stderr)

    if result.admitted:
        print(f"admitted proof {result.proof_id}", file=sys.stderr)
        print(str(result.directory), file=out)
        return EXIT_OK

    print(
        f"NOT ADMITTED ({build.admission}). Diagnostic package written; no video, thumbnail, "
        f"README, or listing copy was produced.",
        file=sys.stderr,
    )
    for reason in build.package.decision.reasons:
        print(f"    - {reason}", file=sys.stderr)
    print(str(result.directory), file=out)
    return EXIT_NOT_ADMITTED


def _cmd_verify(args: Any, out: Any) -> int:
    report = verify_package(args.proof_dir)
    if args.json:
        print(
            canonical_json(
                {
                    "directory": str(report.directory),
                    "proof_id": report.proof_id,
                    "ok": report.ok,
                    "admission": report.admission,
                    "checks": report.checks,
                    "errors": report.errors,
                }
            ),
            file=out,
        )
    else:
        for line in report.checks:
            print(f"  ok    {line}", file=sys.stderr)
        for line in report.errors:
            print(f"  FAIL  {line}", file=sys.stderr)
        verdict = "VERIFIED" if report.ok else "VERIFICATION FAILED"
        print(f"{verdict}: {report.directory}", file=out)
    return EXIT_OK if report.ok else EXIT_NOT_ADMITTED


def _cmd_version(args: Any, out: Any) -> int:
    from terminus_xi import PROTOCOL_VERSION, RUNTIME_VERSION

    print(
        canonical_json(
            {
                "engine_version": ENGINE_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "runtime_version": RUNTIME_VERSION,
                "adapters": registered_kinds(),
            }
        ),
        file=out,
    )
    return EXIT_OK


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="terminus-proof",
        description="Build and verify baseline-vs-capability proof packages admitted by Terminus XI v1.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    builder = subparsers.add_parser("build", help="build a proof package for one demo spec")
    builder.add_argument("spec", help="path to a terminus-proof.demo-spec.v1 document")
    builder.add_argument("--out", help="output root (default: <repo>/proofs)")
    builder.add_argument("--root", help="repository root used to resolve spec-relative paths")
    builder.add_argument(
        "--no-media",
        action="store_true",
        help="skip video and thumbnail rendering (documentation is still gated on admission)",
    )
    builder.set_defaults(handler=_cmd_build)

    verifier = subparsers.add_parser("verify", help="independently verify a proof directory")
    verifier.add_argument("proof_dir", help="path to a proof package directory")
    verifier.add_argument("--json", action="store_true", help="emit a machine-readable report")
    verifier.set_defaults(handler=_cmd_verify)

    version = subparsers.add_parser("version", help="print engine and protocol identity")
    version.set_defaults(handler=_cmd_version)

    return parser


def main(argv: Sequence[str] | None = None, out: Any = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    stream = out if out is not None else sys.stdout
    try:
        return int(args.handler(args, stream))
    except (SpecError, AdapterError, BuildError, RedactionError, ContractError, SchemaError) as exc:
        print(f"terminus-proof: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"terminus-proof: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
