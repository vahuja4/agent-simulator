# Scenario synthesis Phase 4.3 notes

Date: 2026-08-18

## Decisions

Blueprint identity is now the first 16 hexadecimal characters of SHA-256 over
canonical JSON for the complete serialized blueprint except its self-referential
`id`. This includes `goal_facts`, fixture bindings, assertions, limits, and
provenance. Deduplication still uses the Phase 2 canonical key; identity no longer
reuses that deliberately coarser key.

`behavioral_class_key` is unchanged. `goal_facts` may remain outside that class key
because executable trigger facts are validated against their procedure paths and
perturbation placements. The path, placement, and fixture bindings therefore define
the exercised behavior, while the full-content blueprint ID distinguishes different
concrete fact payloads within that behavior.

Realization and dry-run history is append-only. Every new record has a
`batch_label`; reuse is recorded as a zero-attempt `reused` outcome, and a collision
or other failure adds a new failed-closed record without replacing any earlier
record. Catalog regeneration also preserves prior records verbatim. The live entry
points require an explicit batch label, and the dry-run entry point selects only
successful realizations from that label.

## Recovery and migration

The 27 realization records and 27 dry-run records from live batch 1 were labeled
`live-batch-1`. The three overwritten `unexecutable_blueprint` realization records
were restored from Git HEAD. Live batch 2 is represented by 14 separate records:
eight first-try successes, one retry success, two reused candidates, and three
zero-attempt failed-closed collisions. No live LLM call was made.

All 740 catalog blueprints, 25 archived blueprints, and 36 scenario YAML artifacts
were re-hashed and renamed by content. Blueprint references plus scenario/candidate
IDs in the manifest were remapped through the content source they actually
referenced. In particular, each of the three ambiguous old IDs now has a distinct
archive ID and corrected-catalog ID:

| Old ID | Archived predecessor | Corrected catalog blueprint |
| --- | --- | --- |
| `j1-6fd3cce8c9eff872` | `j1-893c89aca4ffd761` | `j1-0fb64fdd31e1862d` |
| `j1-82b14c01dcd19612` | `j1-cf2f090a2069215f` | `j1-d4005d61d5c1c541` |
| `j1-af21746358a09ca6` | `j1-d99609eb16c576cc` | `j1-d9c5a7d33bdea7c0` |

## Candidate ID map

| Content source | Old ID | New ID |
| --- | --- | --- |
| archive / live-batch-1 | `j1-6fd3cce8c9eff872` | `j1-893c89aca4ffd761` |
| archive / live-batch-1 | `j1-1a8cef237cb9a615` | `j1-fb6b690c15415aa2` |
| archive / live-batch-1 | `j1-82b14c01dcd19612` | `j1-cf2f090a2069215f` |
| archive / live-batch-1 | `j1-df7bba79881e74dc` | `j1-2d33e21a27e0da0d` |
| archive / live-batch-1 | `j1-f09de7c5aa3cdf9f` | `j1-79fee1e600a40f89` |
| archive / live-batch-1 | `j1-5cbd3ff623f7bab9` | `j1-e277e3d45f349722` |
| archive / live-batch-1 | `j1-e10080bbf91eba03` | `j1-85dbf007529f1b4d` |
| archive / live-batch-1 | `j1-38b93bf6b74fd63c` | `j1-bf5e7cf3e29e3006` |
| archive / live-batch-1 | `j1-51f7838c30dee465` | `j1-73b2cd259cf187df` |
| archive / live-batch-1 | `j1-af21746358a09ca6` | `j1-d99609eb16c576cc` |
| archive / live-batch-1 | `j1-4d198723b6000c08` | `j1-0d64354fd7908d7b` |
| archive / live-batch-1 | `j1-861102e99a258cec` | `j1-df887a8345b75639` |
| archive / live-batch-1 | `j1-15bb6d470dfe0fe4` | `j1-a37f5536f69c44a1` |
| archive / live-batch-1 | `j1-3e21466ac8ff6a3c` | `j1-53425021f42b818b` |
| archive / live-batch-1 | `j1-f82f27ce647d158d` | `j1-ffd32fa113061751` |
| archive / live-batch-1 | `j1-3a1337323e78683e` | `j1-cf740eaf50c4ff70` |
| archive / live-batch-1 | `j1-1e2fa23ae4f709e0` | `j1-77dbe30de9e37c22` |
| archive / live-batch-1 | `j1-7097e664b6c4c49c` | `j1-499d5cb95d7d7d7a` |
| archive / live-batch-1 | `j1-57ae9cbad1b8eaab` | `j1-a7069cfccb050154` |
| archive / live-batch-1 | `j1-fe5951f7be75d15a` | `j1-ade6fdfaff6f3c22` |
| archive / live-batch-1 | `j1-ed8fef83a7017aa7` | `j1-91c596bf43dc7a96` |
| archive / live-batch-1 | `j1-e013fd66e72c4df5` | `j1-6443e95e2279e240` |
| archive / live-batch-1 | `j1-788290ed34079618` | `j1-91088839e031046d` |
| archive / live-batch-1 | `j1-e41173c694844c43` | `j1-443f5760a346c43b` |
| archive / live-batch-1 | `j1-9032d7f657ac92bc` | `j1-37f7a44fdb9fd189` |
| catalog / live-batch-2 sample | `j1-0e52ad6a51d58f25` | `j1-2484e5f390c4919e` |
| catalog / live-batch-2 sample | `j1-19ba48bc5d5f1281` | `j1-33a8542037f90a65` |
| catalog / live-batch-2 sample | `j1-27cbbe5c09a99e33` | `j1-43d6711c9d6ab035` |
| catalog / live-batch-2 sample | `j1-53aebf7a6eff6fef` | `j1-3d88f3176efb27cd` |
| catalog / live-batch-2 sample | `j1-5a5aea0a2f4e1ce0` | `j1-e0eb0744f28a9653` |
| catalog / live-batch-2 sample | `j1-61c4ef0cacdc2b41` | `j1-e5b543fbe1a2edeb` |
| catalog / live-batch-2 sample | `j1-633947b18615197d` | `j1-225595457f4c793b` |
| catalog / live-batch-2 sample | `j1-6fd3cce8c9eff872` | `j1-0fb64fdd31e1862d` |
| catalog / live-batch-2 sample | `j1-82b14c01dcd19612` | `j1-d4005d61d5c1c541` |
| catalog / live-batch-2 sample | `j1-8ec36fc7f0a71cee` | `j1-a4731cb8613f3514` |
| catalog / live-batch-2 sample | `j1-af21746358a09ca6` | `j1-d9c5a7d33bdea7c0` |
| catalog / live-batch-2 sample | `j1-c1e39666c08a0ca2` | `j1-82b6ebb15f31ae4b` |
| catalog / live-batch-2 sample | `j1-f52316ce06b16852` | `j1-25ec15d058329ba8` |
| catalog / live-batch-2 sample | `j1-fde571a63c6a227e` | `j1-535fdfa16315d879` |

## Verification

Phase 4.2 tests cover goal-fact-sensitive identity, unchanged behavioral classes,
append-only collision history, explicit reuse history, batch labels, and immutable
catalog regeneration. Artifact-integrity checks passed for all migrated files and
manifest references. The complete offline suite passed with 298 tests and one live
test deselected.
