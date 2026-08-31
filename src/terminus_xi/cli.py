"""The deterministic Terminus XI v1 command line.

``python -m terminus_xi verify`` is the canonical entry point: it identifies an
artifact, evaluates a frozen contract set, applies an admission policy, and
emits a canonical receipt. The process exit status carries the decision, so a
rejection cannot be mistaken for a success by a shell caller.

Exit codes
----------
``0``  ADMIT
``2``  REVIEW  (WARN under a policy that requires review)
``3``  REJECT
``4``  ERROR   (a check could not establish its invariant)
``5``  usage/loading failure
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import PROTOCOL_VERSION, RUNTIME_VERSION
from .admission import DEFAULT_POLICY, AdmissionPolicy, load_policy
from .canonical import canonical_json, read_json, write_json
from .checks import registered_names
from .codes import ISSUE_CODES
from .contracts import ContractError, load_contract_set
from .engine import verify_artifact
from .receipt import verify_receipt_file
from .schemas import SchemaError

__all__ = ["main", "EXIT_CODES"]

EXIT_CODES = {"ADMIT": 0, "REVIEW": 2, "REJECT": 3, "ERROR": 4}
EXIT_USAGE = 5


def _load_policy(path: str | None) -> AdmissionPolicy:
    return DEFAULT_POLICY if path is None else load_policy(path)


def _resolve_pointer_arg(document: Any, pointer: str | None) -> Any:
    if not pointer:
        return document
    from .canonical import resolve_pointer

    return resolve_pointer(document, pointer)


def _cmd_verify(args: argparse.Namespace, out: Any) -> int:
    artifact = _resolve_pointer_arg(read_json(args.artifact), args.pointer)
    contract_set = load_contract_set(args.contracts)
    policy = _load_policy(args.policy)

    outcome = verify_artifact(
        artifact,
        boundary_id=args.boundary,
        contract_set=contract_set,
        policy=policy,
        artifact_id=args.artifact_id or Path(args.artifact).name,
    )

    if args.receipt:
        Path(args.receipt).parent.mkdir(parents=True, exist_ok=True)
        write_json(args.receipt, outcome.receipt)
    else:
        print(canonical_json(outcome.receipt), file=out)

    if not args.quiet:
        print(f"boundary  {args.boundary}", file=sys.stderr)
        for result in outcome.results:
            codes = ",".join(result.codes()) or "-"
            print(f"  {result.verdict:<5} {result.check_id}  [{codes}]", file=sys.stderr)
        print(f"admission {outcome.admission}", file=sys.stderr)
        for reason in outcome.decision.reasons:
            print(f"  - {reason}", file=sys.stderr)

    return EXIT_CODES[outcome.admission]


def _cmd_verify_receipt(args: argparse.Namespace, out: Any) -> int:
    verification = verify_receipt_file(args.receipt, artifact_sha256=args.artifact_sha256)
    if not verification.ok:
        for error in verification.errors:
            print(f"receipt invalid: {error}", file=sys.stderr)
        return EXIT_CODES["ERROR"]
    print(f"receipt valid: admission {verification.admission}", file=out)
    return EXIT_CODES.get(verification.admission or "ERROR", EXIT_CODES["ERROR"])


def _cmd_codes(args: argparse.Namespace, out: Any) -> int:
    vocabulary = [
        {
            "code": item.code,
            "severity": item.severity,
            "category": item.category,
            "description": item.description,
        }
        for item in sorted(ISSUE_CODES.values(), key=lambda entry: entry.code)
    ]
    if args.json:
        print(canonical_json(vocabulary), file=out)
        return 0
    for item in vocabulary:
        print(f"{item['severity']:<5} {item['code']:<28} {item['description']}", file=out)
    return 0


def _cmd_contracts(args: argparse.Namespace, out: Any) -> int:
    contract_set = load_contract_set(args.contracts)
    print(f"{contract_set.set_id} v{contract_set.version}  sha256={contract_set.sha256()}", file=out)
    for contract in contract_set.contracts:
        print(
            f"  {contract.check_id:<32} impl={contract.implementation:<28} "
            f"sha256={contract.sha256()[:16]}",
            file=out,
        )
    return 0


def _cmd_version(args: argparse.Namespace, out: Any) -> int:
    print(
        canonical_json(
            {
                "protocol_version": PROTOCOL_VERSION,
                "runtime_version": RUNTIME_VERSION,
                "issue_codes": len(ISSUE_CODES),
                "registered_checks": registered_names(),
            }
        ),
        file=out,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="terminus-xi",
        description="Terminus XI Protocol v1 - deterministic boundary watchdog.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser(
        "verify", help="evaluate a frozen contract set against an artifact and emit a receipt"
    )
    verify.add_argument("artifact", help="path to the JSON artifact entering the boundary")
    verify.add_argument("--contracts", required=True, help="path to a check-contract-set document")
    verify.add_argument("--boundary", required=True, help="the named boundary being crossed")
    verify.add_argument("--policy", help="path to an admission policy (default: terminus-xi.default)")
    verify.add_argument("--receipt", help="write the receipt here instead of stdout")
    verify.add_argument("--pointer", help="JSON Pointer selecting the artifact inside the file")
    verify.add_argument("--artifact-id", help="identity recorded in provenance")
    verify.add_argument("--quiet", action="store_true", help="suppress the human-readable summary")
    verify.set_defaults(handler=_cmd_verify)

    check_receipt = subparsers.add_parser(
        "verify-receipt", help="independently verify an existing XI receipt"
    )
    check_receipt.add_argument("receipt", help="path to a terminus-xi.receipt.v2 document")
    check_receipt.add_argument("--artifact-sha256", help="digest the receipt must cover")
    check_receipt.set_defaults(handler=_cmd_verify_receipt)

    codes = subparsers.add_parser("codes", help="print the frozen issue-code vocabulary")
    codes.add_argument("--json", action="store_true")
    codes.set_defaults(handler=_cmd_codes)

    contracts = subparsers.add_parser("contracts", help="summarize a contract set and its digests")
    contracts.add_argument("contracts", help="path to a check-contract-set document")
    contracts.set_defaults(handler=_cmd_contracts)

    version = subparsers.add_parser("version", help="print protocol and runtime identity")
    version.set_defaults(handler=_cmd_version)

    return parser


def main(argv: Sequence[str] | None = None, out: Any = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    stream = out if out is not None else sys.stdout
    try:
        return int(args.handler(args, stream))
    except (ContractError, SchemaError, ValueError, KeyError) as exc:
        print(f"terminus-xi: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (OSError, json.JSONDecodeError) as exc:
        print(f"terminus-xi: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
