# 37 — An acquisition log is not analysis, and a snippet can lie in shape and winner

Two defects in one card, caught by the owner on 2026-08-26.

First: the results card led with a table of what scores were found — statuses, grades, routes.
That is an acquisition log. It answers "what did the pipeline retrieve?" and says nothing about
whether the model worked, what separated useful sides from losing ones, or what should change.
The reader's questions are the candidate record and counterfactual, the losses the passes
avoided, the Brier against the do-nothing prior, how the replacement workflow actually graded,
the failure pattern, and the one-sentence thesis. The retrieval table is the appendix.
`result_display.card_order_gate` now refuses a card whose acquisition section precedes any
analysis section.

Second: the card displayed "MIL 9, NYM 2" as a FINAL_IDENTIFIED score. The official final was
NYM 3–2 — the opposite winner, a completely different game shape. The snippet was not stale or
imprecise; it was false. The never-bind rule already kept it out of every canonical path, but
the display layer still put a wrong winner in front of the reader under a "FINAL" label, and the
UNCONFIRMED tag did not carry the weight of that error. The correction is recorded append-only
(v2, 84f93525). The two places v1 refused to display — conflicting HOU@NYY states, and a PDX
"win" recap that contradicted another headline and never happened — were the discipline working:
when snippets disagree, showing nothing was right, and the one time snippets agreed on a false
score is why they identify and never bind.
