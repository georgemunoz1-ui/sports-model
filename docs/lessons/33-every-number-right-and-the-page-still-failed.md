# 33 — Every number was right and the page still failed its reader

The 2026-08-24 report passed every gate it had. Forecasts frozen and hashed, EV reproduced to the
cent, hold validated, Monte Carlo decomposed, provenance graded. And it opened with what I had got
wrong, then forecasts, then prices, then a twenty-row two-sided EV table, and a reader who wanted to
know what to do today had to work it out somewhere past all of that.

The answer was "bet nothing." That is a one-line answer and it was buried under my working.

## What the structure was actually doing

Correctness gates catch wrong numbers. Nothing in the harness asked whether the page *communicated*
its own conclusion, so the failure was invisible to every check I had. The page was organised around
how the analysis was built rather than around what the reader needed, which is the natural order for
the author and the wrong one for everyone else.

Worse, the two-sided EV table implicitly invited a bad reading. Twenty rows, ten of them positive,
no summary above them saying zero — a reader skimming that table could easily come away thinking
there were ten opportunities here. There were zero. A model should never manufacture twelve wagers
because twelve games exist, and a page should not be laid out so that a hurried reader does it on
the model's behalf.

## Four questions that must stay apart

    PROJECTED_WINNER   who is most likely to win. Says nothing about price.
    BEST_VALUE_SIDE    the best price-relative opportunity. Often the OTHER team.
    ACTUAL_ACTION      BET, PASS or BLOCKED. The only column that authorizes anything.
    SHADOW_TOTAL       analytical direction. Never a wager, whatever it says.

COL@WSH is the case that proves they are different questions: WSH is the projected winner at 56.66%
and COL +169 is the better side. Merge those two columns and the board becomes either a tip sheet or
nonsense, depending on which one you dropped.

## PASS and BLOCKED are not the same output

A row with no positive-value side is a PASS: the market and the model agree, there is nothing here.
A row with positive value that cannot be acted on is BLOCKED: there is something here and we cannot
reach it. Collapsing them into "no bet" makes the portfolio look clean while hiding every blocker in
it. Today: 1 pass, 11 blocked. Those two numbers say completely different things about the state of
the system.

## WATCHLIST, not HOLD

"Hold" already names the bookmaker's overround throughout this repository. An action status that
collides with a market quantity will eventually be quoted at someone in the wrong sense. Pick the
word that cannot be confused, even when the confusing one reads more naturally.

## The rule

Report structure is part of the deliverable, not packaging around it. The order is: what to do, then
what the model thinks, then why, then the evidence, then the corrections. Audit history is real
evidence and it goes in an appendix — it must never stand between a reader and today's decision.

And BET is a gated word. Five gates, all required, none excusing another, and a blocked opportunity
may never be rendered in the selections section. `decision_view.render_gate` refuses a page that
does it, because a rule nothing enforces is a preference.
