# Daily operations acceptance standard

This document defines the evidence required to call the sports workflow operational. A scheduled job, passing unit tests, or a generated Markdown card is not by itself acceptance.

## Required daily outputs

1. **Pregame card per league**: forecast cutoff, source availability cutoffs, exact event identity, model and artifact identity, full-slate coverage, original point forecast and distribution, contract probability, current line/price timestamp, selector decision, EV calculation, qualification verdict, and immutable output hash.
2. **Source acquisition receipt**: source URL/provider, retrieval time, provider availability time when known, response hash, parser result, event counts, failed sources, and explicit coverage state. An empty/blocked response is not proof of no games.
3. **End-of-day review**: immutable forecast-to-result joins, authoritative settlement evidence, prediction and probability scores, market/CLV measures only where timestamp and quote lineage are proven, missing/excluded records, and separate model/selector/operational metrics.
4. **Failure report**: run ID, commit, failed stage, error, artifact pointer, affected leagues/events, release state, and next diagnostic action.
5. **Delivery receipt**: durable artifact reference and confirmed publication/delivery result.

## Fail-closed gates

- Never backdate a forecast, retro-register a historical card, or describe a reconstruction as a true pregame forecast.
- Preserve original forecasts and all selector rejects. Never overwrite canonical results or silently replace a failed model.
- Validate event identity, home/away orientation, point-margin sign, timestamps, settlement rules, distribution mass, and qualification evidence.
- Keep data readiness, software health, predictive qualification, publication eligibility, and wagering authorization as separate decisions.
- If any required source, model package, input cutoff, selector receipt, or qualification gate is missing, publish a failure report and (only if supported) a clearly labelled research-only diagnostic artifact. Do not promote it to an official betting card.
- A run with zero authorized selections reports zero selections. ROI on no selections is undefined, not a hypothetical result.

## Acceptance sequence

1. Reproduce the saved-input run at its pinned commit and compare numerical outputs and hashes.
2. Run current acquisition and every model-specific runner; reconcile event counts and source receipts.
3. Verify all forecasts are pre-start and that original forecast bytes remain unchanged.
4. Run independent result-source, settlement, contract-probability, selector, and authorization checks.
5. Generate the card and archive a receipt; after events settle, generate the end-of-day review from those exact registered forecasts.
6. Confirm artifact readback and delivery; alert on any failed or missing stage.
7. Keep research qualification and wagering authorization OFF unless their own evidence gates independently pass.

## Current limitation

The daily preflight workflow captures sources and runs repository health checks. It is deliberately not described as the full card pipeline: model-specific current packages, valid pregame forecasts, selector registrations, durable archive configuration, and delivery receipts must be demonstrated separately before that claim is made.
