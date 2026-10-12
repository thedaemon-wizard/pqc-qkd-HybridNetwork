# Before/after measurement of the IPsec lane's PPK rotations

The result of [`VERIFICATION_CHECKLIST.md`](../../../VERIFICATION_CHECKLIST.md)
row 2.17: arnika `3a8cc13` (release 0.1.0) against arnika `f4cf9ba`
(release 0.2.0) on the strongSwan 6.1.0 lane of the public demo host, with
the windows, counting rules and comparison fixed before the runs. The numbers
were posted upstream first, on
[arnika PR #51](https://github.com/arnika-project/arnika/pull/51#issuecomment-6117990327)
on 2026-10-12. Every file here is the output of
[`scripts/ppk_race_report.py`](../../../scripts/ppk_race_report.py), which
prints counts, classes and times only; the container logs it read carry
credential ids and host identities and are kept off the repository, as row
2.17 requires.

## Arms and windows (UTC)

| File prefix | Arm | Window | Role in the comparison |
|---|---|---|---|
| `armA_primary` | A: release 0.1.0 (`94eb164`), arnika `3a8cc13` | 2026-09-25T10:55:00Z to 2026-10-02T10:55:00Z, 168 h from both IPsec nodes' recreation | Arm A |
| `armA_deviation` | A | 2026-09-25T16:01:55Z to 16:11:55Z | The named deviation: the KMEs and the WireGuard nodes were recreated at 16:01:55-16:02:01Z inside arm A; the 10 minutes after it, reported apart |
| `armA_sensitivity` | A | 2026-09-25T16:02:01Z to 2026-10-02T16:02:01Z | Sensitivity check: 168 h starting after that recreation |
| `armB_instep` | B: release 0.2.0 (`3baead1`), arnika `f4cf9ba` | 2026-10-03T07:04:06Z to 2026-10-08T08:42:21Z | Arm B as it enters the comparison |
| `armB_mismatch_span` | B | 2026-10-08T08:42:21Z to 2026-10-10T07:04:06Z (46.4 h) | Excluded and reported apart: row 2.17 excludes an interval-number mismatch from its first tick to the next recreation of both nodes, and there was none before the arm ended |
| `armB_primary` | B | 2026-10-03T07:04:06Z to 2026-10-10T07:04:06Z, 168 h from both IPsec nodes' recreation | The whole arm, kept for completeness; not used in the comparison |

Neither IPsec node restarted in either arm: `StartedAt` and `RestartCount`
were unchanged at the start, at the end and at each export, and arm B's
compose configuration and image ids at the export (2026-10-12T04:21Z) were
identical to the record taken when it started. The configuration diff
between the arms is the one fixed before the runs: the arnika pin, with the
IPsec image rebuilt from it, and the PQC input (the `PQC_PSK_FILE` mount, its
`pqc-psk-*` volume and the `depends_on` on the WireGuard node removed,
`PQC_ENABLED: "true"` instead). No KMS fetch failed in either arm.

## Result

Failures by alice's role in the interval of her last rotation (C1 is an
invalidation by a fail-closed path, C3 the race, C4 input divergence; C2, C5
and U were 0 in every window; intervals are 95 % Clopper-Pearson):

| | A, alice PRIMARY | A, alice BACKUP | B (in-step), alice PRIMARY | B (in-step), alice BACKUP |
|---|---|---|---|---|
| Rotations $`R`$ | 10,035 | 10,120 | 7,241 | 7,354 |
| Failures $`F`$ | 39 | 4 | 0 | 1,848 |
| C1 | 0 | 0 | 0 | 1,844 |
| C3 | 31 | 0 | 0 | 4 |
| C4 | 8 | 4 | 0 | 0 |
| C3 / $`R`$ | 2.10e-3 to 4.38e-3 | 0 to 3.64e-4 | 0 to 5.09e-4 | 1.48e-4 to 1.39e-3 |

**The comparison fixed before the runs** (exact conditional binomial test,
[`compare_A_primary_vs_B_instep_C3.txt`](compare_A_primary_vs_B_instep_C3.txt)):
C3 in 31 of 20,155 rotations in arm A against 4 of 14,595 in arm B, one-sided
$`p = 9.04 \times 10^{-5}`$. By cell, alice-PRIMARY went from 31 to 0
($`p = 4.86 \times 10^{-8}`$) and alice-BACKUP from 0 to 4 (two-sided
$`p = 0.031`$); the cell tests and the sensitivity window
([`compare_A_sensitivity_vs_B_C3.txt`](compare_A_sensitivity_vs_B_C3.txt),
32 against 31 in arm A) were not fixed beforehand.

**C1, which arm A could not produce.** Every C1 in arm B is a BACKUP interval
of alice that ended in `no key_id from the peer` and a random PPK, after
which alice's next IKE_AUTH failed once. The per-tick list in
`armB_instep.json.gz` pairs each tick's early key_id with how the BACKUP's
interval ended: with alice as BACKUP, 1,845 of the 3,801 intervals whose
key_id reached alice before her own boundary ended in that invalidation, and
none of the 3,553 where it did not. The offset between the two nodes'
interval boundaries (bob - alice) grew from -30 ms to -15.0 s over the in-step
part, against a median size of 82 ms and a maximum of 0.93 s in arm A, and the
interval-number mismatch began when it reached half an interval. Row 3.2b
predicted the early-key_id path from the code; why the offset kept growing
is an inference from the code, not a measurement, and is set out in the PR
#51 comment.

**Outside the measurement fixed beforehand.** In arm B's window the
WireGuard lane's alice logged 1,414 `no key_id from the peer` invalidations
and bob 1 (a count of that line in the two containers' exported logs over the
same window), although that lane starts aligned to an interval boundary.

## Comparisons

| File | Compares | Status |
|---|---|---|
| `compare_A_primary_vs_B_instep_C3.txt` | C3, arm A against arm B in-step | The comparison fixed before the runs |
| `compare_A_primary_vs_B_instep_C1.txt` | C1, arm A against arm B in-step | Descriptive |
| `compare_A_sensitivity_vs_B_C3.txt` | C3, arm A's sensitivity window against the whole of arm B | Descriptive |
| `compare_A_primary_vs_B_C3.txt`, `compare_A_primary_vs_B_C1.txt`, `compare_A_primary_vs_B_C4.txt` | C3, C1 and C4, arm A against the whole of arm B, mismatch span included | Descriptive, kept to show that the exclusion does not change the direction of any of them |

## How the files were made

On the host, from each arm's exported `docker logs -t` of `alice-ipsec` and
`bob-ipsec`:

```sh
python3 scripts/ppk_race_report.py report --alice A.log --bob B.log \
    --since <window start> --until <window end> [--json]
python3 scripts/ppk_race_report.py compare --class C3 armA_primary.json armB_instep.json
```

with the windows in the table above, and `--class C1` and `--class C4` for
the descriptive comparisons. The `.json.gz` files are the `--json` outputs,
compressed with `gzip -9 -n`; [`SHA256SUMS`](SHA256SUMS) lists every file.
