# 36 — True in one layer, a lie of omission in the other

I reported "12 games registered and unsettled — nothing gradable" while eleven finals sat on the
public scoreboard. The statement was exactly correct in the canonical layer: no retained artifact,
no game id, no content hash, nothing admissible. And the results card it produced was a lie by
omission, because the reader's question was "what happened?", not "what may settle a ledger?", and
I answered the second question as if it were the first.

The owner's rule, now binding and enforced by harness/result_display.py:

    RESULT_DISPLAY and CANONICAL_EVIDENCE_ADMISSION are separate layers. Missing canonical
    provenance may block settlement, promotion and estimator input; it may never hide an available
    score from the visible results card.

The gate refuses BOTH failure modes, because the wall between the layers can be breached from
either side. HIDDEN: an available score withheld from display on provenance grounds — evidentiary
rigor used as a blindfold. LAUNDERED: a relayed score claiming canonical effect — a display row
quietly settling a ledger. Each has its own refusal code, and a fixture names the five protected
canonical effects explicitly rather than looping over the list under test.

What made this one easy to miss is that the collapse was conservative. Hiding scores FEELS like
rigor: nothing unverified touches the reader. But the reader was never the thing the provenance
rules protect — the ledger, the prior pool, the promotion counts and the estimator are. Withholding
a score the whole world can see protects nothing and costs credibility, which is the one resource
an honest results card exists to build.

Rule: every evidentiary standard has a scope, and applying it outside that scope is not extra
safety, it is a different error. Ask what the gate protects before letting it decide what a reader
is allowed to see.
