# Consolidation artifact storage repair

PR #46 merged as 43ad83382af067b019a086d45d23569497ca6e08.
Its PR run 35956282637 passed 394 tests and the committed MLB acceptance comparison.
The main run 35956502274 passed 394 tests. The PR46-only acceptance comparison
was correctly skipped on that push. Both failed only at artifact upload with
the storage-quota error. Durability passed. These facts do not clear repository
health, release restrictions, or predictive validation.

## Minimal prevention change

Keep the complete `--all` Git bundle and every existing evidence path.
Repack Git objects losslessly with a larger delta search window and compression
level 9, then upload with ZIP compression level 9. Compare reference targets
before and after packing, verify the bundle, and retain its SHA-256.
Missing upload inputs now fail when no files are found; upload failure remains
fatal. No retention period, permissions, existing checks, or trigger changes.
No model, registry, ledger, grading, forecast, market, action, or release-policy
file is changed.

On retained artifact 10784614200, the bundle shrank from 28,091,500 bytes to
27,323,990 bytes (2.732%). All 75 advertised reference targets and all 10,833
reachable Git objects matched. A fresh bare-repository restore and full fsck
passed. YAML, shell syntax, and unchanged-check/path comparisons passed.
This is a measured modest reduction, not deduplication across separate runs
and not proof that the account has available quota.

## Cleanup prepared, not executed

The latest 100 repository workflow runs contained 13 Consolidation runs,
10 with retained artifacts totaling 278,519,997 bytes. This is a scoped
inventory, not repository-wide or account-wide billing usage.

Three older archives have exact-byte durable backups:
- 10785275906: 28,028,792 bytes, run 35940881541.
- 10774764754: 27,868,997 bytes, run 35916497131.
- 10762847990: 27,860,724 bytes, run 35886363619.

Total potential reclaim: 83,758,513 bytes. The newer archive 10784614200 remains
on GitHub. No source-capture, forecast, registration, grading, durability, or
timestamp-anchor artifact is selected for deletion.

Backup: `consolidation-evidence-backup.zip`, Library ID
`libfile_b8ecd8d74d748191b50e1dbf32247705`.
SHA-256: `cee76c276eec93f094b445ac9ac40c786e8ccd7120fda589df62b07d55de70de`.
The backup includes the exact three ZIPs, GitHub metadata/digests, and hashes
for every ZIP member. Each original ZIP matches its GitHub SHA-256. An
independent materialization of the saved backup matched the outer SHA-256 and
all original ZIP digests; ZIP CRC checks passed.

The connector cannot delete artifacts or read account billing usage. The
browser is signed out. No cleanup has occurred. Before deletion, recheck the
three exact IDs and digests; preserve run logs and workflow runs. After storage
is released and GitHub has recalculated usage, rerun the failed job on both
the historical PR46 run and the current main run. The error message says usage
is recalculated every 6–12 hours. A green check requires actual successful
upload; do not suppress it, shorten retention, or assert capacity from this
partial inventory.
