# U1 Report — Preserve structured first-failure diagnostics

Status: DONE

## Changes

- Added the complete closed diagnostic taxonomy with stable stage/code names and exhaustive enum coverage.
- Mapped real metadata shape/dtype, input/provider, prediction, output, receipt, and eligibility boundaries to exact first diagnostics.
- Distinguished missing and malformed receipts and unknown usage/preferred-device failures.
- Preserved immutable first failure through fallback and later prediction accounting.
- Serialized stable diagnostic literals only; JSON contains no mutable NSError text, private paths, or absolute receipt paths.
- Added checked receipt-publication RESULT rewrite and stable dual-publication stderr on rewrite failure.

## Commits

- `04ddbf2 feat(ane): Preserve qualification failure diagnostics`
- `06b1d3d fix(ane): Complete diagnostic failure taxonomy`
- `fc77b20 fix(ane): Complete pre-handle diagnostics`
- `2add9fb test(ane): Verify qualification cancellation cleanup`
- `e9cf4d1 fix(ane): Preserve pre-handle publication diagnostics`

## Verification

- `make h3_ane_tool_tests h3_ane_tests`: passed without compiler warnings.
- `./h3_ane_tests`: passed with actual Metal access.
- `python3 -m unittest discover -s tests -p 'test_ane_tools.py'`: 24 tests passed.
- Strict `clang -fsyntax-only` for `h3_ane.m` and `tests/qualify_ane.c`: passed without warnings.
- `git diff --check`: passed.

## Review findings resolved

- Exact taxonomy now covers every declared stage/code name and maps real boundary failures rather than generic fallbacks.
- Qualification results use stable sanitized messages and a safe relative receipt role only on success.
- Receipt rewrite failure removes authority, emits both stable publication codes, and exits 2.
- Pre-handle GPU, weight-store, weight-load, tensor-digest, contract, and input failures now emit stable diagnostics before a handle exists.
- Compiled-model unreadability, digest failure, receipt digest mismatch, receipt invalidity, and source mismatch remain distinct.
- Missing Core ML usage/device context remains absent (`null`) rather than an invented empty array or device.
- Each applicable U1 mutation row has a separate source-commit-bound evidence record generated from actual disposable fixture runs.

## Evidence

- `.release-loop/evidence/U1/receipt-invalidation.json`
- `.release-loop/evidence/U1/result-publication.json`
- `.release-loop/evidence/U1/receipt-publication.json`
- `.release-loop/evidence/U1/result-rewrite.json`
- `.release-loop/evidence/U1/runtime-adoption.json`

## Concerns

- None for U1. The focused exception fixes preserve pre-handle diagnostics and prove receipt/rewrite cancellation at the actual temporary publication boundaries. Large-operation inventory traversal remains U2 scope and was not changed.

## Final branch review closure

- Exact source commit: `fcc872f3b2459aa277b267c92ee849410025ebd9`.
- Closed first-failure diagnostic context, strict receipt preflight, coordinator reuse authority preservation, and sealed taxonomy were revalidated by 69 Python tests, strict Clang analysis, actual-Metal ANE tests, and fresh isolated synthetic/real runs.
