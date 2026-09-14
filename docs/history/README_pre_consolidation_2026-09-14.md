# Sports Model Research System

Sports forecasting and simulation research across MLB, CFB, WNBA, NFL, MLS, NBA and NHL.
Implementation, data coverage and validation vary by league and branch.

**Status checked September 9, 2026 (UTC).** This page is an evidence index, not a release
attestation. A successful diagnostic run or draft PR does not establish production readiness
or predictive improvement. The verified September 8 runs have **market overlay OFF and action authority OFF**.

**Current development: [PR #18 — sports information-state stack and official-source pilot](https://github.com/georgemunoz1-ui/sports-model/pull/18), stacked on PR #17.** See the pilot evidence and remaining work below.

## Start here: repository and branch authority

| Location | Purpose | Verified source before this documentation update |
|---|---|---|
| [sportsmodel/main](https://github.com/georgemunoz1-ui/sports-model/tree/sportsmodel/main) | Operational code lineage | `98035a19a7ba80bff622e35f4a61661f09082d5c` |
| [main](https://github.com/georgemunoz1-ui/sports-model/tree/main) | GitHub landing branch; contains README and .gitignore | `c3df041c513bf737b14afb613f0a73789c7d6e9c` |
| [Open PRs](https://github.com/georgemunoz1-ui/sports-model/pulls) | Pending code, research and evidence | Inspect exact head and base before use |

Recent work is distributed across branches. Do not interpret the operational branch's older
registry as proof that no diagnostic forecast exists elsewhere. Conversely, do not treat
a feature-branch run as code merged into the operational branch.

The commits above identify the inspected code state; this README-only update advances the branch
heads without merging any model PR. Branch protection and operational release acceptance are
not certified by this documentation change.

## Latest verified model and simulation output

### September 8 MLB diagnostic refresh

[GitHub Actions run 34273154914](https://github.com/georgemunoz1-ui/sports-model/actions/runs/34273154914)
completed successfully on
[code commit 4d39ff5](https://github.com/georgemunoz1-ui/sports-model/commit/4d39ff5f039fe28709e9f58f48f43c7ab28a5ef0),
branch `codex/nfl-wnba-nba-models-v1`.

| Field | Retained artifact value |
|---|---|
| Slate date | 2026-09-08 |
| Mode | DIAGNOSTIC_SHADOW |
| Scheduled / forecasted MLB games | 15 / 15 |
| Simulation count | 100,000 per game |
| Requested as-of time | 2026-09-08T20:08:57Z |
| Latest source fetch time | 2026-09-08T20:09:52.711976Z |
| Generation time | 2026-09-08T20:09:52.758760Z |
| Workflow conclusion | success |
| Reported probability-gap categories | 7 NONE, 5 MODERATE, 3 CRITICAL |
| Market overlay / action authority | false / false |

Artifact ID: `10074624931`. The downloaded ZIP's SHA-256 was independently checked against
GitHub's artifact digest:

```text
5cb007a85cada78e4a041986c0b92e2783892baa4b81ccfaff3e13761e5ae8cf
```

The ZIP contains the JSON/CSV/Markdown card, divergence reports, manifest, PIT report and run log.
Its listed expiry is October 8, 2026. Download from the linked run while retained.

The card compares fixed-Poisson probabilities at simulation-realized mean runs with a
Gamma–Poisson simulation including starter-workload uncertainty. These are different distribution
assumptions; their gap is not automatically a Monte Carlo convergence failure.

**Interpretation limits:** source times are live-fetch proxies. The run reports a tolerance-based
PIT pass; preserve requested time, actual data vintage and generation time separately.
Arizona's away starter and Seattle's home starter use fallback states. Contract interpretation
of grading eligibility, run-line/total support and replay requirements must be checked against
this exact source commit before declaring either acceptance or a defect. No predictive superiority
or protected canonical prospective admission is established here.

## Official-information pilot: a separate output

[PR #18](https://github.com/georgemunoz1-ui/sports-model/pull/18) now contains actual source retrieval,
immutable receipts, official MLB identity population, cutoff-specific claim reduction,
deterministic NFL report parsing and offline replay.

| Verified September 8 pilot measure | Result |
|---|---:|
| MLB provider-date games retained | 15/15 |
| Active team rosters retrieved | 30/30 |
| Official roster player IDs | 840 |
| Additional probable-only player identity | 1; roster membership unresolved |
| Raw source receipts/hash checks | 32/32 |
| NFL report rows parsed | 11; player/event/practice-date binding unresolved |
| News-information tests at executed commit | 41 passed |

Executed code: `4edf9eb99b8f059c656c213bb8ec21c195cc1e34`.
[Run 34272196290](https://github.com/georgemunoz1-ui/sports-model/actions/runs/34272196290)
passed capture and tests; research CI also passed. Both actual capture ZIPs and offline replay
evidence are committed in the
[pilot evidence directory](https://github.com/georgemunoz1-ui/sports-model/tree/1b7a83c6067f9080bdc6762e12651e04f22c8e79/research/news_information/pilot_evidence/2026-09-08).

**This pilot did not generate forecasts.** Its rows say `NO_FORECAST_INFORMATION_PILOT`.
It must not be confused with the separate MLB diagnostic run above.

## Pending implementation and evidence

The following PRs were open drafts when checked. Their titles identify scope; this table does
not certify that their full scope has passed acceptance.

| PR | Scope | Base |
|---|---|---|
| [#9](https://github.com/georgemunoz1-ui/sports-model/pull/9) | Absent-acquisition freshness bypass follow-up | sportsmodel/main |
| [#10](https://github.com/georgemunoz1-ui/sports-model/pull/10) | SIM-1 simulation corpus and tiered specification; documentation | sportsmodel/main |
| [#11](https://github.com/georgemunoz1-ui/sports-model/pull/11) | September 3 evidence and release gate | sportsmodel/main |
| [#12](https://github.com/georgemunoz1-ui/sports-model/pull/12) | Seven-sport source recovery and diagnostic admission | codex/nfl-wnba-nba-models-v1 |
| [#13](https://github.com/georgemunoz1-ui/sports-model/pull/13) | Phase 1.1 code lineage and remote-durability gates | sportsmodel/main |
| [#14](https://github.com/georgemunoz1-ui/sports-model/pull/14) | Late import of September 5 local evidence | sportsmodel/main |
| [#15](https://github.com/georgemunoz1-ui/sports-model/pull/15) | September 6 pregame shadow evidence mirror | sportsmodel/main |
| [#16](https://github.com/georgemunoz1-ui/sports-model/pull/16) | MLB market-feature validation beyond the first 50 rows | sportsmodel/main |
| [#17](https://github.com/georgemunoz1-ui/sports-model/pull/17) | Offline PIT evaluation infrastructure and challenger intake | sportsmodel/main |
| [#18](https://github.com/georgemunoz1-ui/sports-model/pull/18) | Sports information-state stack and official-source pilot | PR #17 branch |

[PR #1](https://github.com/georgemunoz1-ui/sports-model/pull/1), the separate sportsim implementation,
is also open against landing branch `main`. Model code existing in that PR does not establish
an admitted operational path.

PR #17 is evaluation infrastructure. Naming Toto, TabICL, Granite or other candidates does not
establish that their checkpoints ran or improved forecasts. PR #18's parser and engineering tests
do not establish extraction accuracy.

## Next development priorities

1. Bind NFL report dates, canonical player identities and scheduled events.
2. Complete MLB starter/lineup, bullpen and weather/roof source binding; retain unresolved games.
3. Execute the compact NLP research stack: BGE, checkpoint-specific GLiNER, DeBERTa NLI and one
   independent NER challenger, with verified checkpoint/dependency provenance.
4. Build an independently reviewed point-in-time corpus and measure destructive false positives,
   identity errors, abstentions and latency.
5. Evaluate versioned A/B/C information-state forecasts on identical prospective populations.
6. Review pending PRs and verify release readiness separately from research performance.

## Operating and reporting rules

- Start from the actual branch and commit required for the task. Read
  [AGENTS.md](https://github.com/georgemunoz1-ui/sports-model/blob/sportsmodel/main/AGENTS.md),
  [state.json](https://github.com/georgemunoz1-ui/sports-model/blob/sportsmodel/main/state.json)
  and the [progress journal](https://github.com/georgemunoz1-ui/sports-model/blob/sportsmodel/main/docs/progress.md).
- Inspect open PRs and relevant workflow artifacts before declaring work absent or completed.
- Use the existing runbook and healthcheck for a complete operational checkout:
  `python3 harness/healthcheck.py`. A README update does not mean that healthcheck passed.
- Keep input observations, model outputs, simulation outputs and market observations distinct.
- Preserve frozen forecasts. Append results and corrections with explicit parent-artifact identity.
- Distinguish saved, tested, reviewed, merged, operational and predictively validated.
- Before alleging a contract violation, check the run's exact code, configuration, chronology and
  applicable policy. Report artifact fields separately from audit conclusions.
- Keep timestamps in UTC and state the requested slate timezone explicitly.

## Historical documentation

The previous README is retained verbatim in
[docs/history/README_pre_2026-09-09.md](docs/history/README_pre_2026-09-09.md).
Its August-era performance summaries, model descriptions and readiness statements are historical,
not a current cross-branch status report.

Update this page when a model/evidence milestone changes. Link the actual PR, source commit or
workflow; keep detailed run results and append-only corrections in their original records.
