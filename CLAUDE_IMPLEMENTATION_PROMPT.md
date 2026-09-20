You are implementing the local repository `/home/orz/Desktop/terminus-xi-protocol` under the governing contract `UKSL.md`.

Your mission is to complete the UKSL, not merely propose an architecture.

Read first:
- `UKSL.md`
- `CHARTER.md`
- `README.md`
- `docs/LINEAGE.md`
- `docs/RECOVERED_VS_NEW.md`
- `docs/KNOWN_HISTORICAL_DEFECTS.md`
- active schemas under `spec/`
- relevant historical evidence under `archive/`, especially the recovered charter and XI agents

You may inspect `/home/orz/Desktop/gtd-dataset-factory-core` as READ-ONLY reference for evidence/receipt/runner patterns. Do not modify that repository unless the UKSL is otherwise impossible to satisfy; if you believe modification is unavoidable, stop and report the blocker instead of changing it.

Implementation rules:
1. KSL-01 first: build and freeze one coherent Terminus XI v1 base. Historical files stay historical. Do not import archived runtime modules into active runtime.
2. Resolve the old divergent xiAudit semantics into one stable issue-code and PASS/WARN/FAIL system. Record the decision.
3. Keep XI deterministic. No LLM calls inside XI verification/admission.
4. Provide a small active Python package, CLI/module entry point, tests, and machine-readable freeze receipt.
5. Then KSL-02: build the automated proof/documentation engine using XI v1 as the admission substrate.
6. Provide a declarative demo spec and an end-to-end fixture-backed Claim Boundary Audit example. It must automatically emit the required proof package, including a real PNG and a real MP4 generated locally using Pillow/ffmpeg where appropriate.
7. Build and verify must be separate operations. Verification must detect tampering/incompleteness.
8. Fail closed: parity failure, XI FAIL, unsupported claim, invalid redaction, or incomplete evidence cannot produce an admitted success package.
9. Add negative tests for the critical gates.
10. Keep the implementation bounded and boring. Do not build a SaaS, web app, marketplace integration, or generalized agent framework.
11. Do not delete or rewrite historical evidence to make tests pass.
12. Do not commit or push. Leave the working tree ready for operator review.

Before finishing:
- run the full active test suite;
- run the canonical KSL-01 verify/receipt path;
- run the canonical KSL-02 proof build;
- independently verify the resulting proof directory;
- validate all JSON/schema artifacts you create;
- use ffprobe to verify the generated MP4;
- verify the thumbnail is a valid image;
- report exact commands, test counts, generated proof path, and any unresolved UKSL clauses.

Do not claim KSL closure unless the evidence supports it. If a clause cannot be satisfied, leave a clear blocker receipt instead of hand-waving.
