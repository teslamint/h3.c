---
module: release evidence
date: 2026-08-12
problem_type: workflow_issue
component: integration gate
severity: high
applies_when:
  - "A release criterion names an exact operator command"
  - "A workflow mutates packages, compiled artifacts, receipts, or authority state"
  - "Temporary work directories can survive across tool versions"
tags:
  - exact-command
  - mutation-evidence
  - legacy-state
  - release-gate
---

# Verify exact default commands against legacy state

## Context

An isolated ANE integration run proved the converter, compiler, production
reader, and 441-operation inventory. The same command with its published default
work directory failed after merge because an older directory lacked the current
ownership marker. The safety check was correct, but the declared one-command
acceptance criterion was not met.

Earlier evidence also described conversion, compilation, and summary failure
behavior without executing the claimed failure mechanism. Final review required
actual wrong-shape conversion, partial and native compile failures, synchronized
cancellation, preserved prior output, and successful reruns.

## Guidance

Treat the exact published command and its default state as part of the product:

1. Run the literal command on the merged tree; do not substitute a custom path,
   direct Python invocation, or helper call for its acceptance result.
2. Seed supported legacy and adversarial pre-state, including an older work
   directory, prior complete output, existing authority, and incomplete
   temporary artifacts.
3. Execute every mutation-matrix mechanism rather than inferring it from helper
   assertions: forced failure, cancellation, cleanup, compensation, and rerun.
4. Retain bounded evidence with the exact command, source commit, pre-state,
   injection, exit, post-state, and next invocation.
5. Stop the release gate when the exact default command fails, even if an
   isolated override proves the underlying implementation.

## Why this matters

An isolated pass answers whether the implementation can work. The published
default command answers whether the operator workflow works in the state users
actually inherit. Those are different claims. Safety checks should remain
fail-closed, but release status must expose—not conceal—the operational gap.

Mechanism evidence closes a second gap: a correct final state can result from a
fixture failing before the intended boundary. Synchronized fixtures and
sentinels prove that the converter, compiler, publisher, or authority transition
itself was exercised.

## When to apply

Apply this gate whenever a change touches:

- conversion or compilation outputs;
- atomic result or receipt publication;
- authority invalidation or quarantine;
- coordinator-owned work directories; or
- a documented one-command integration or release target.

The gate passes only when the merged tree succeeds with the literal default
command and every applicable transition has observed failure, cancellation,
cleanup, compensation, and rerun evidence.

## Examples

- A custom `ANE_INTEGRATION_WORK=/private/tmp/new-path` run may prove functional
  correctness, but it cannot pass a criterion that declares
  `make h3_ane_integration_test` with the default work directory.
- A helper raising on a wrong tensor shape does not prove the converter leaves
  no final package. Run the converter CLI and inspect the final and temporary
  paths.
- A cancellation test starting with no prior summary does not prove atomic
  preservation. Seed known bytes, interrupt after the intended boundary, and
  compare them exactly before rerunning.
