# E1 1,757-row EXPLORATORY dataset — AUDIT RECORD

Exploratory ≠ unaudited. This pins the provenance of the 1,757-row sensitivity run so it is fully
reproducible and tamper-evident, even though it is NOT confirmatory evidence.

## Frozen artifacts (sha256)
| file | rows | sha256 |
|---|---|---|
| `data/mlb/e1_score_pop.csv` (scored population) | 1757 (1757 unique row_id) | `56092b406ac991f882cb9d6a4d392bdebe5af8b1b6b78c5da72099b7d6927afb` |
| `data/mlb/e1_construction_table.csv` (all resolvable starts) | 2683 | `0dd2e6a9a7b7d07a70a73e08c44c30151857bf2e780e01c07611ec7bb05e61eb` |

`e1_score_pop.csv` md5 (secondary) = `52425948593defd0d946f76a42182c30`; 15 columns
(`row_id,pid,gamePk,date,opp,actual,n_prior,p_asof,etbf,o,L,ek_base,ek_e1,premium,highk`).

## Scoring-code commits (frozen)
| file | commit | role |
|---|---|---|
| `harness/e1_data.py` | `0a520c7` | canon table, team-id map, BLOCKING reconciliation gate |
| `harness/e1_replay.py` | `0a520c7` | build paired population (n_prior≥5, ≤7/19), resolvers, row_id=pid\|gamePk |
| `harness/e1_score.py` | `5f12da1` | paired scoring (MAE/NLL/slope, slices, frozen §6 rule) |
| dataset frozen at HEAD | `1a644b4` | after factual DH gamePk recovery |

## Input-data provenance
- 30 statsapi team hitting gamelogs (`data/mlb/team_gamelogs/*.json`), each parsed locally and
  reconciled EXACTLY (G/SO/AB/BB) to Taco's 7/23 snapshot (`data/mlb/team_batting_asof/2026-07-23.json`)
  via `e1_data.gate_ok()` — the gate must PASS before the replay builds.
- As-of team K-rate `o = (ΣSO + L·200)/(Σ(AB+BB) + 200)`, strict `date<D`; pitcher rate = engine
  shrunk K-rate; log5 combine. Baseline projection identical to the engine on all rows.

## Transcript (source of the closure finding)
`/root/.claude/projects/-home-claude/89dc228f-5581-5f9d-87f5-493d59afc3d1.jsonl` — contains the
original 2026-07-18 backtest code (anonymous parallel arrays, no row IDs, no date horizon) proving the
original 1,759 row set is unrecoverable.

## Doubleheader resolution evidence (factual, not manufactured)
Two 7/19 rows (LAD@NYY DH) were gamePk-ambiguous under K-total matching. Resolved by fetching each
pitcher's statsapi pitching gamelog:
- Yamamoto (808967, LAD) 2026-07-19 → gamePk **823523** (complete game, 7 SO == NYY game K; corroborated).
- Schlittler (693645, NYY) 2026-07-19 → gamePk **823523** (gamelog fetch; K-total match alone was ambiguous).
Both started game 1 of the DH against each other. row_ids remain unique (distinct pid).

## Reproduce
```
python3 harness/e1_replay.py     # rebuild construction + score population (gate must PASS)
python3 harness/e1_score.py      # paired scoring on e1_score_pop.csv
sha256sum data/mlb/e1_score_pop.csv   # must equal the hash above
```

## ERRATA — retracted language in immutable commit messages
Two earlier commit messages used verdict/causal language now retracted:
- `d093279` "E1 CONFIRMATORY: REJECT … Opponent-K rejected" — the run it describes was VOID (wrong 2659
  population); "confirmatory"/"REJECT" are withdrawn.
- `5f12da1` "E1 PAIRED confirmatory … REJECT holds" — relabeled EXPLORATORY; "confirmatory"/"REJECT" withdrawn.
Both are **superseded** by the recorded status: **NO-PROMOTE / CONFIRMATORY INDETERMINATE**, and the
Cole/Sale cause is **UNEXPLAINED**. Git history is deliberately left immutable — rewriting published
commit messages would itself alter the audit trail and change referenced hashes, which is inconsistent
with this project's standing rule against history rewrites. This erratum is the correction of record.
