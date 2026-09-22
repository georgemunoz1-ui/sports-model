# Current research runtimes

The operational interface now covers NFL, MLB, WNBA, CFB, NBA, NHL and MLS.
Operational means a fitted executable consumes verified current inputs and retains
real simulation draws. It does not mean every optional feature is implemented or
that betting accuracy, settlement pricing, or real-money use has been established.
All outputs retain zero dose and no action authority.

| League | Current path | Scope and treatment |
|---|---|---|
| NFL | Selected QB arm, immutable weekly state | Complete prior week required; adjudicated starter source is seed-pinned; failed ensemble remains excluded |
| MLB | Frozen V13 | Official full-season D-1 runs, current pitcher logs, frozen park/HFA; unknown starters use declared frozen league prior |
| WNBA | Frozen selected fitter | Official regular-season census with independent ESPN box confirmation |
| CFB | Selected Elo/form logit + Ridge | FBS vs FBS, Week 2+; previous-week snapshot; exact original feature replay |
| NBA | Explicit initial research logit + Ridge | Regular season, Cup final excluded; currently no scheduled events in acquired window |
| NHL | Explicit initial research logit + Ridge | Regular-season final winner; preseason is outside this model's population |
| MLS | Explicit initial research Poisson | Regulation home/draw/away probabilities and actual paired goal draws |

NBA/NHL/MLS require `--initial-research-baselines`; the tested-default registry is
unchanged. NBA and MLS beat the simple empirical base rate in the retained later
period, while NHL's paired interval includes zero. None is a promoted champion.
All three retrospective datasets were acquired now, so they do not establish
historical availability or a prospective record. The initial NBA population audit
and its documented Cup-final correction are retained.

## Reproduce current packages and cards

Install `requirements-consolidated.txt`. Obtain and verify the source archives
listed in `.github/workflows/all-model-runtimes.yml`; that branch-specific workflow
performs the complete current acceptance, including NFL. The six other runtimes
can be rebuilt and exercised with:

```bash
python scripts/verify_all_current_runtimes.py \
  --recovery recovery --current current --history history --output unique-run
```

It builds immutable `packages/<league>/package.json`, runs the actual card CLI for
every acquired current date, verifies every retained draw count/probability,
and compares repeat-run draw bytes at the identical cutoff. Any missing forecast,
source revision, cutoff mismatch or corrupt input fails acceptance. NBA's verified
empty schedule is a successful no-event result, not a fabricated game or forecast.

To consume a built package directly:

```bash
SPORTS_RESEARCH_PACKAGE_DIR=/absolute/path/unique-run/packages \
python scripts/generate_card_force.py --league mls --date 2026-09-26 \
  --initial-research-baselines --simulations 100000 --output-dir unique-card
```

The CLI retains draws automatically. Packages expire six hours after source
retrieval; rebuilding from the same old source does not reset that clock. Acquire
new source receipts before the next operational run. These acceptance artifacts
are snapshots, not a scheduler or an always-running service. Capture scripts and
builders are reusable; a newly encountered source disagreement remains a safety
refusal until resolved, never silently relabeled healthy.

## Feature alignment

`sports.registry.CURRENT_RUNTIME_PROFILES` describes actual model-consumed features,
separately from ingestion plans. NFL's independent heads remain distinct from joint
score expectations. WNBA and NBA/NHL margin/total heads are independent diagnostics.
CFB has no fitted total head. MLB run-line/total settlement remains outside the
validated winner path. MLS alone here exposes its explicit independent-Poisson
joint score assumption. Injury, lineup and goalie effects are not invented when
absent from the selected transform.

Historical failed verdicts, the old repository-health incidents, canonical ledgers,
and prior blocked releases remain historical evidence. Current runtime acceptance
is evaluated directly rather than rewriting those records to manufacture a green
status. Forecast operation and wagering authorization remain separate.
