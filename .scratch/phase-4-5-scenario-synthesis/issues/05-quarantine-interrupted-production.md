# Quarantine or resume interrupted production

Type: task
Status: resolved

Slice 3 originally left interrupted candidate production neither quarantined
nor resumable, allowing ambiguous partial artifacts.

## Acceptance criteria

- Verified complete production artifacts are reused idempotently.
- Partial artifacts are quarantined as corrupt or resumed only under the exact snapshot identity.
- Tests cover interruption at each durable-write boundary.

## Answer

Resolved by `ab4e3ce`: candidate bundles are assembled and validated in hidden
staging directories, then atomically renamed. Partial final or staging bundles
are quarantined, while verified complete candidates are reused idempotently.
Tests cover each staged file boundary and the pre-rename boundary.

## Comments

- Carried over from the Slice 3 merge-readiness review during main cleanup on 2026-08-27.
