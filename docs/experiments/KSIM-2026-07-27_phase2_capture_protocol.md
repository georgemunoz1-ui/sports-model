# KSIM-2026-07-27 — PHASE 2 CAPTURE PROTOCOL

Final clarification, issued after the protocol addendum was accepted. **Phase 1 is not
modified.** Terminology here **supersedes** the EVENT_A / EVENT_B naming used in
`KSIM-2026-07-27_protocol_addendum.md` §5.

| | |
|---|---|
| Phase-1 artifact | `data/mlb/props/simulated/2026-07-27_KSIM_phase1.json` |
| **Phase-1 sha256** | `7f827fd0014e5835ec3bf3572bbe1ff36dce452d5e0a55b735d04fe665c12d2f` |
| Verified unchanged | `sha256sum -c` OK, and `harness/verify_lineage.py` OK |

---

## 1 — Naming. Nothing is an "opener" until it is proven to be one

| term | definition |
|---|---|
| `FIRST_CAPTURED_LINE` | the first K line we observed for a pitcher, **possibly one-sided** |
| `FIRST_CAPTURED_COMPLETE_QUOTE` | the first capture carrying book + line + over price + under price + timestamp |
| `VERIFIED_OPENER` | a quotation established as the **market's opening** quotation by a verified market-origin timestamp or an authenticated historical-odds feed |

**Neither of the first two may be called an opener.** "First we saw it" is a fact about our
retrieval; "first the book posted it" is a fact about the market, and we have never once had
evidence for the second. Absent a market-origin timestamp or odds-history feed, `VERIFIED_OPENER`
is simply **absent** — not inferred, not assumed to be the earliest capture.

## 2 — Two timestamps, never conflated

Every capture records both:

- **`observed_at_utc`** — when *we* retrieved it. Always present.
- **`source_quote_time_utc`** — the book's or feed's own quote timestamp, **only if the source
  supplies one**. If the source supplies none, this is **`null`**.

Setting `source_quote_time_utc = observed_at_utc` is prohibited. It would manufacture market
provenance out of our own retrieval clock, and it is the single mistake that would let a
mid-slate screenshot masquerade as an opener.

## 3 — Required fields on every capture

    book                       named sportsbook
    source_url_or_feed         where it came from
    observed_at_utc            our retrieval time
    source_quote_time_utc      book/feed time, or null
    line                       posted K line
    over_price                 or null if not shown/legible
    under_price                or null if not shown/legible
    raw_payload                screenshot path or raw JSON/text, retained
    source_labels_main_line    true / false / unknown -- does the SOURCE designate it the main line

A capture missing `raw_payload` is provenance-only and may not be scored. Prices that are
present at source but not transcribed are `null` **with a flag** — never guessed (R1).

## 4 — Main-line selection, by market designation only

When a book shows several strikeout lines for one pitcher:

1. **Use the line the book itself designates default/main.** Record
   `main_line_basis: "book_designated"`.
2. **Otherwise** mark the pitcher `MAIN_LINE_UNRESOLVED`, **retain every alternate rung**, and
   score nothing from that pitcher's line placement.

**Prohibited: choosing the rung nearest E\[K\].** That would select the comparison to minimise
the very error being measured, guaranteeing a flattering result no matter how the engine
performs. The rule must be independent of the projection, and it is.

This is the same defect class that quarantined 10 of 30 arms on 7/26 — an alt rung read as a
main line — approached from the other side.

## 5 — Phase-2A eligibility is decided by the clock

A Phase-2A capture is valid for **executable-decision scoring** only if
`observed_at_utc` **precedes that pitcher's scheduled first pitch**.

A quotation first captured after first pitch is **ineligible for executable-decision scoring**.
It is still recorded, still reported, and may still be used for line-placement description —
but it may not produce a frozen executable decision, and it may not be relabelled later.

Per-pitcher deadlines, taken from the frozen artifact:

| pitcher | game | first pitch (UTC) | frozen line |
|---|---|---|---|
| George Kirby | SEA@TEX | `2026-07-27T18:35Z` | 5.5 |
| Kumar Rocker | SEA@TEX | `2026-07-27T18:35Z` | 4.0 |
| Keider Montero | BAL@DET | `2026-07-27T22:40Z` | 4.0 |
| Kyle Bradish | BAL@DET | `2026-07-27T22:40Z` | 5.5 |
| Merrill Kelly | ARI@PIT | `2026-07-27T22:40Z` | 4.0 |
| Mitch Keller | ARI@PIT | `2026-07-27T22:40Z` | 4.0 |
| Tyler Phillips | PHI@MIA | `2026-07-27T22:40Z` | 3.5 |
| Zack Wheeler | PHI@MIA | `2026-07-27T22:40Z` | 7.0 |
| Andrew Alvarez | TOR@WSH | `2026-07-27T22:45Z` | 5.0 |
| Max Scherzer | TOR@WSH | `2026-07-27T22:45Z` | 3.5 |
| Chase Burns | CLE@CIN | `2026-07-27T23:10Z` | 6.5 |
| Martin Perez | ATL@NYM | `2026-07-27T23:10Z` | 4.0 |
| Slade Cecconi | CLE@CIN | `2026-07-27T23:10Z` | 4.0 |
| Max Fried | NYY@CHW | `2026-07-27T23:40Z` | 5.0 |
| Noah Schultz | NYY@CHW | `2026-07-27T23:40Z` | 4.5 |
| David Peterson | CHC@STL | `2026-07-27T23:45Z` | 4.5 |
| Matthew Liberatore | CHC@STL | `2026-07-27T23:45Z` | 4.5 |
| Tatsuya Imai | HOU@LAA | `2026-07-28T01:38Z` | 5.0 |
| Walbert Urena | HOU@LAA | `2026-07-28T01:38Z` | 5.0 |
| Jack Perkins | BOS@ATH | `2026-07-28T01:40Z` | 5.5 |
| Payton Tolle | BOS@ATH | `2026-07-28T01:40Z` | 5.5 |
| Brandon Sproat | MIL@SF | `2026-07-28T01:45Z` | 5.0 |
| Tyler Mahle | MIL@SF | `2026-07-28T01:45Z` | 5.0 |

## 6 — Two distinct comparisons, reported separately

| comparison | scope |
|---|---|
| **C1** frozen mechanical line vs `FIRST_CAPTURED_COMPLETE_QUOTE` | every eligible pitcher with a complete quote |
| **C2** frozen mechanical line vs `VERIFIED_OPENER` | **only** pitchers with authenticated opener history |

C1 measures how far the model's number sits from *a* market number we could actually see. C2
measures placement against the market's *origin*. They answer different questions, and C1 must
never be presented as C2. If no authenticated opener history exists for this slate — which is
the present expectation — **C2 is reported as empty**, not approximated from C1.

Per the addendum: both are **line-placement error in strikeouts only**. The `-115` prices are a
null assumption and are never scored.

## 7 — Reproducibility of the lineage hash

    python 3.11.15   CPython   Linux-6.18.5-x86_64-with-glibc2.39
    command:  python3 harness/verify_lineage.py
    manifest: docs/experiments/KSIM-2026-07-27_lineage_manifest.txt

`harness/verify_lineage.py` recomputes every published hash from the files on disk and prints
OK/FAIL per item. Current status: **all four reproduce**.

Two canonical forms are documented because the published one cannot be changed without
invalidating a hash already cited in the record:

- **v1 (published)** `''.join(f'{pid}:{sha256}')` over pids sorted as **strings**, utf-8, no
  separator → `806e5cd2f0a7964900b421069b1bfe596ccc71e885dfa6bb30fb0a55bcd53f20`.
  Note the pid sort is lexicographic on the CSV string, not numeric. Concatenating
  variable-length fields without a delimiter is not injective in general; it is well defined
  here only because pid and sha256 are fixed-width in this manifest. Kept verbatim.
- **v2 (use for future manifests)** newline-delimited `f'{pid}  {sha256}'` with a trailing
  newline → `fc6f01fa65f42fc39eaae65861ad49c341dc2935ca59c3251049cbb422c69a30`.

## Kyle Bradish — status restated

`FIRST_CAPTURED_LINE` **only**.

    line                    5.5
    under_price             PRESENT AT SOURCE, value not transcribed -> null + flag
    over_price              null (not shown)
    observed_at_utc         2026-07-27T02:33Z
    source_quote_time_utc   null (Covers board supplied no quote timestamp)
    source                  Covers player-props board, 12-source scan
    status                  NOT a complete executable quote; NOT a verified opener

He is **not** `FIRST_CAPTURED_COMPLETE_QUOTE` (no over price) and **not** `VERIFIED_OPENER` (no
market-origin timestamp). He may not be passed to `select_play()`. He remains **Tier 2**, and
his line-placement accuracy is never scored as blind.

One record correction: the addendum recorded "under side only, no price transcribed." The
source did display an under price; its value was not transmitted into our record. Both
statements are true of different things — the price existed at source, and we hold no value for
it. It is `null` with `price_present_but_not_transcribed: true`, never a reconstructed number.


---

# PHASE-2A OPERATIONAL RULES

Issued after the capture protocol was accepted. **Phase 1 is not modified.** These govern how a
Phase-2A capture is performed, evidenced and frozen.

## A1 — Fixed scan order

    DK -> FD -> BR -> MGM -> CZR -> HR

Declared in advance and never reordered mid-slate.

## A2 — A scan cycle is one timestamped sweep

A cycle **begins at one recorded UTC timestamp** (`cycle_started_at_utc`) and queries every
available source in A1 order. **Every response is retained**, including `market_unavailable`,
`no_line_posted`, `page_error` and `not_reachable`. A source that returned nothing is a recorded
observation, not an omission — the absence of a line at a known time is exactly the evidence
that established the 7/27 market had not opened.

## A3 — Primary selection: first qualifying cycle, then hierarchy

The primary `FIRST_CAPTURED_COMPLETE_QUOTE` is taken from the **first scan cycle containing at
least one qualifying complete main-line quote**. Within that cycle the **pre-registered
hierarchy decides**, not sub-second retrieval order.

> **This supersedes the rule pre-registered in the addendum §6** ("first complete quote by
> capture timestamp, ties broken DK > FD > BR > MGM > CZR > HR"). The change is legitimate
> *only* because **zero complete quotes exist for this slate at the time of writing** — the
> 12-source scan at `2026-07-27T02:33:00Z` found one one-sided line and no complete quotes.
> Changing a selection rule after a qualifying capture existed would be retrospective
> selection and is prohibited.

**Operational resolution.** Because DK is first in the hierarchy, a qualifying DK quote cannot
be outranked later in the same cycle, so it may be frozen the moment it qualifies. If DK does
not qualify, the cycle continues down the order; the first book that qualifies wins, and the
non-qualifying responses above it are retained as the evidence that it did.

## A4 — Required fields on every capture

    scan_cycle_id                 e.g. KSIM-0727-C03
    cycle_started_at_utc          full ISO, with date and seconds
    observed_at_utc               full ISO, per-source retrieval time
    source_quote_time_utc         book/feed time, or null -- never set equal to observed_at_utc
    scheduled_first_pitch_utc     full ISO
    minutes_before_first_pitch    signed; negative means AFTER first pitch -> ineligible (A7 / §5)
    book                          DK | FD | BR | MGM | CZR | HR
    line                          posted K line
    over_price                    or null
    under_price                   or null
    main_line_designation         book_designated | not_designated | MAIN_LINE_UNRESOLVED
    evidence_sha256               hash of the raw evidence artifact (A5)
    evidence_path                 path to the retained payload/screenshot
    status                        complete_quote | line_only | market_unavailable | error

## A5 — What counts as evidence

Acceptable, and only these:

- the **original HTML/JSON response** as returned; or
- a **timestamped screenshot visibly containing the complete quote**.

The evidence artifact is **hashed** and the hash stored on the record.

**A manually constructed JSON record is metadata, not raw evidence.** This has a consequence
worth stating plainly: the existing hand-built drop files under `data/mlb/props/drops/` are
metadata under this rule. They remain valid *inputs* to the ingester, but they are not evidence
and cannot by themselves substantiate a Phase-2A capture.

## A6 — Complete ISO timestamps, always

Write `2026-07-27T18:35:00Z`, never `18:35Z`. A bare time is ambiguous across the UTC date
boundary, and this slate straddles it: the three West Coast games fall on **2026-07-28** in UTC
while every other game falls on 2026-07-27.

- **Forward-only.** Historical `progress.md` entries contain bare `HH:MMZ` forms; they are an
  append-only log and are **not rewritten** (R6). The rule binds all new records.
- **The frozen artifact is not edited.** It stores `2026-07-27T18:35Z` — full date, no seconds
  field. Phase 2A writes the seconds-complete form. These denote the same instant; the mapping
  is recorded below, not applied to the frozen file.

| pitcher | game | frozen artifact form | Phase-2A form | frozen line |
|---|---|---|---|---|
| George Kirby | SEA@TEX | `2026-07-27T18:35Z` | `2026-07-27T18:35:00Z` | 5.5 |
| Kumar Rocker | SEA@TEX | `2026-07-27T18:35Z` | `2026-07-27T18:35:00Z` | 4.0 |
| Keider Montero | BAL@DET | `2026-07-27T22:40Z` | `2026-07-27T22:40:00Z` | 4.0 |
| Kyle Bradish | BAL@DET | `2026-07-27T22:40Z` | `2026-07-27T22:40:00Z` | 5.5 |
| Merrill Kelly | ARI@PIT | `2026-07-27T22:40Z` | `2026-07-27T22:40:00Z` | 4.0 |
| Mitch Keller | ARI@PIT | `2026-07-27T22:40Z` | `2026-07-27T22:40:00Z` | 4.0 |
| Tyler Phillips | PHI@MIA | `2026-07-27T22:40Z` | `2026-07-27T22:40:00Z` | 3.5 |
| Zack Wheeler | PHI@MIA | `2026-07-27T22:40Z` | `2026-07-27T22:40:00Z` | 7.0 |
| Andrew Alvarez | TOR@WSH | `2026-07-27T22:45Z` | `2026-07-27T22:45:00Z` | 5.0 |
| Max Scherzer | TOR@WSH | `2026-07-27T22:45Z` | `2026-07-27T22:45:00Z` | 3.5 |
| Chase Burns | CLE@CIN | `2026-07-27T23:10Z` | `2026-07-27T23:10:00Z` | 6.5 |
| Martin Perez | ATL@NYM | `2026-07-27T23:10Z` | `2026-07-27T23:10:00Z` | 4.0 |
| Slade Cecconi | CLE@CIN | `2026-07-27T23:10Z` | `2026-07-27T23:10:00Z` | 4.0 |
| Max Fried | NYY@CHW | `2026-07-27T23:40Z` | `2026-07-27T23:40:00Z` | 5.0 |
| Noah Schultz | NYY@CHW | `2026-07-27T23:40Z` | `2026-07-27T23:40:00Z` | 4.5 |
| David Peterson | CHC@STL | `2026-07-27T23:45Z` | `2026-07-27T23:45:00Z` | 4.5 |
| Matthew Liberatore | CHC@STL | `2026-07-27T23:45Z` | `2026-07-27T23:45:00Z` | 4.5 |
| Tatsuya Imai | HOU@LAA | `2026-07-28T01:38Z` | `2026-07-28T01:38:00Z` | 5.0 |
| Walbert Urena | HOU@LAA | `2026-07-28T01:38Z` | `2026-07-28T01:38:00Z` | 5.0 |
| Jack Perkins | BOS@ATH | `2026-07-28T01:40Z` | `2026-07-28T01:40:00Z` | 5.5 |
| Payton Tolle | BOS@ATH | `2026-07-28T01:40Z` | `2026-07-28T01:40:00Z` | 5.5 |
| Brandon Sproat | MIL@SF | `2026-07-28T01:45Z` | `2026-07-28T01:45:00Z` | 5.0 |
| Tyler Mahle | MIL@SF | `2026-07-28T01:45Z` | `2026-07-28T01:45:00Z` | 5.0 |

## A7 — Freeze per pitcher, immediately

The moment a pitcher has a qualifying capture, **that pitcher's executable decision is frozen**:
`select_play()` is run against that quote and the result is written and hashed.

Do **not** wait for the rest of the slate, for a later book, or for a better price. Waiting is
optionality, and optionality exercised with knowledge of how the market moved is indistinguishable
from choosing the entry that flatters the record.

## A8 — Later quotations are kept, never substituted

Every subsequent quotation is preserved for line-movement and closing-line analysis. None may
replace a frozen Phase-2A decision, and a later, better price never restates the decision that
was actually frozen.


---

# PHASE-2A OUTCOME AND DESIGN RULES (frozen at commit 5d18dde)

Issued after the operational rules were accepted, **before any qualifying capture existed**.
Phase 1 is not modified.

## B1 — Four distinct non-capture outcomes. Only one of them is a finding.

| status | meaning | establishes "no market"? |
|---|---|---|
| `NO_QUALIFYING_MARKET` | the source **responded successfully** and the response contained no qualifying complete main-line quote | **YES** |
| `SOURCE_FAILURE` | the source was reached but errored, timed out, returned malformed or truncated content | no |
| `ACCESS_BLOCKED` | geo-block, auth wall, bot challenge, robots restriction, rate limit | no |
| `CAPTURE_NOT_RUN` | the source was never queried in this cycle | no |

**Only a successful source response can establish that no qualifying market was present.** The
other three are statements about *us*, not about the market. Collapsing them into "no line
found" would convert our own failure into a market fact — which is how "the 7/27 board was
empty" could quietly become "the 7/27 market had not opened" without evidence for it.

## B2 — Predetermined scan order is preserved

Sources are queried in A1 order and **each source is queried once per cycle**. A source is
**not** re-run within the same cycle because its first result was unfavourable, incomplete, or
not the side we wanted. Re-rolling a source until it yields a usable quote is selection
disguised as retry.

A re-query is permitted only for a `SOURCE_FAILURE` or `ACCESS_BLOCKED` that returned **no
content at all**, and the retry is recorded as a separate attempt with its own timestamp and
status. It never replaces the original record.

## B3 — Opportunistic cadence must be labelled

If cycles are run when convenient rather than on a fixed schedule, the design is
**`OPPORTUNISTIC_CAPTURE`** and must be labelled so wherever results are reported.

Under that label the following claims are **prohibited**:

- that the first captured quote was the **first available** quote;
- any comparison of **market-release timing across pitchers** (who posted earlier);
- any inference about **how long** a line was available before capture.

Our capture times reflect operator availability, not market behaviour. Reading release timing
out of an opportunistic scan measures the observer.

## B4 — Game times verified at capture, never extended afterwards

`scheduled_first_pitch_utc` is verified against an authoritative schedule **at capture time**
and the verification source and time are recorded. A schedule change (rain delay, doubleheader
split, time move) is recorded when observed.

**A deadline is never extended retrospectively** — not after a qualifying quote is in hand, and
not after a result is known. If a game's start moved later and we learn of it afterwards, the
eligibility already determined by the deadline in force at capture stands. Retroactive deadline
extension is the purest form of outcome-dependent eligibility.

## B5 — The amendment window closes at the first qualifying capture

Once the first qualifying Phase-2A capture occurs for this slate, **no further 2026-07-27
protocol amendments are permitted**. Methodological problems discovered after that moment are
**logged and deferred to the next untouched slate** — never applied to 7/27 in flight.

This document and everything above it are frozen as of commit `5d18dde`. The ordering is
auditable: this section is committed before any capture is attempted.


---

# MANUAL-EVIDENCE PATH (section C) — issued before any qualifying capture

Phase 1 unaltered. The C01 artifact is **not rewritten**; the language correction below
supersedes it in reporting, and the original text stays hashed at
`147b2f3f44f4e00a58fb3400fefafe792137bf0e95585e3ef2abebdb2ad46fd0` (R6).

## C1 — `ENVIRONMENT_BLOCKED_DURING_C01`, not "permanent"

**Superseded wording (retained, R6).** The C01 record and its commit message called the two
blockers *"permanent for the agent-side path"* and stated *"retrying later will not change
this."*

**That was an overclaim and is withdrawn.** The evidence was seven HTTP 403s inside an 78-second
window. That establishes **perimeter blocking during C01** and nothing about the future. Network
policy, allowlists and environment configuration can change; a later cycle may succeed.

The finding is renamed **`ENVIRONMENT_BLOCKED_DURING_C01`** and is scoped to that cycle. Claims
that access *can never* work are prohibited. Retrying is permitted and may succeed.

The second blocker is likewise rescoped: WebFetch returning model-summarised markdown rather
than the original response is a property of **the fetch tooling currently available**, which is
also subject to change if a raw-response fetch path appears. It is not a law of nature either.

## C2 — A single screenshot is not a scan cycle

One user-supplied image is a **`USER_SUPPLIED_OPPORTUNISTIC_CAPTURE`**.

It is **not** a completed A1 scan cycle, and it **cannot supply statuses or timestamps for
sources the user did not inspect**. If the user screenshots FD, that tells us nothing whatsoever
about DK, BR, MGM, CZR or HR at that moment.

## C3 — Never manufacture the un-inspected

From a single screenshot it is prohibited to write:

- a per-source `observed_at_utc` for any source not inspected;
- a `NO_QUALIFYING_MARKET` finding for any source not inspected;
- an `ACCESS_BLOCKED` status for any source not inspected.

Un-inspected sources are `CAPTURE_NOT_RUN`. That is the only honest status for a source nobody
looked at.

## C4 — Two capture classes, reported separately

| class | requirement | may freeze a decision? | may be called the primary hierarchy-selected comparison? |
|---|---|---|---|
| **A. `PRIMARY_PROTOCOL_CAPTURE`** | the fixed DK→FD→BR→MGM→CZR→HR cycle, with evidence for **every** source through the qualifying winner | yes | **yes** |
| **B. `USER_SUPPLIED_OPPORTUNISTIC_CAPTURE`** | a complete same-book quote in one image | **yes** | **no** |

Class B can freeze an executable decision. It can never be presented as the hierarchy-selected
primary, because no hierarchy was exercised — one source was looked at.

## C5 — What a screenshot must visibly establish

All six, visible in the image itself, not supplied alongside it:

1. **sportsbook / source**
2. **player and market** (that it is pitcher strikeouts)
3. **the strikeout line**
4. **both over and under prices, from the same book**
5. **game or slate date**
6. **main / default-line status**, where the book shows it

The **original image is preserved and hashed**. A cropped re-render, a retyped transcription, or
a description of an image is not the evidence — the file is.

## C6 — Timestamps on manual evidence

- **`observed_at_utc`** = the time the evidence was **received or captured**. Always present.
- **`source_quote_time_utc`** = null **unless the book visibly supplies a quote time in the
  image**. Never inferred from the file's mtime, the message time, or when we processed it.

## C7 — What is not a complete quote

Neither of these is a `FIRST_CAPTURED_COMPLETE_QUOTE`, and neither may reach `select_play()`:

- a screenshot showing **only one side**;
- an image **combining the best over and the best under from different books**.

The second is the 7/26 aggregator contamination in screenshot form. A price pair that no single
book would honour together is not a quote; it is two quotes from two books, and the hold it
implies is fictional.

## C8 — Scoring an isolated user capture

A class-B capture may support a **prospective executable decision** — it is a real price a real
book showed, and a decision frozen against it before first pitch is a genuine forward test.

Its **line-placement result is descriptive and source-selected**. The book was chosen by
whatever made it convenient to screenshot, not by the pre-registered hierarchy, so the
comparison carries a selection effect of unknown sign and size.

**Class-A and class-B results are never pooled.** Reported separately, always, in any Phase-2
readout.


---

# MANUAL-EVIDENCE TIMESTAMPS AND MAIN-LINE STATUS (section D) — final pre-capture clarification

Phase 1 unaltered. Issued before any qualifying capture exists.

## D1 — Eligibility runs on a timestamp we can defend, not a recollection

**Withdrawn phrasing, mine.** I asked for a screenshot "plus roughly when you took it." An
approximation cannot carry an eligibility decision, and asking for one invites exactly the
conversion D1 prohibits.

Three timestamp fields, recorded separately and never merged:

| field | definition | required |
|---|---|---|
| `received_at_utc` | exact system timestamp when the **original image arrives** | **always** |
| `user_reported_capture_time` | operator's own account — **with timezone and stated precision** ("about 14:30 ET, ±15 min") | optional |
| `image_metadata_time` | EXIF / file metadata time, if present and readable | if available |

**The eligibility test uses `received_at_utc`** — compared against that pitcher's
`scheduled_first_pitch_utc` — **unless** the screenshot **visibly establishes an earlier
timestamp** (a clock or quote time inside the image) **or** trustworthy metadata supplies one.

**An approximate recollection is never converted into an exact timestamp.** It is recorded
verbatim in `user_reported_capture_time`, with its stated precision, and it does not move the
eligibility boundary.

**Consequence, stated plainly so it is not a surprise later.** An image that arrives after a
pitcher's first pitch is **ineligible for executable-decision scoring**, even if it was genuinely
taken hours earlier, unless the image or its metadata proves the earlier time. This is
deliberately conservative: `received_at_utc` is the one time we can evidence, and eligibility
that rests on memory is eligibility that can be revised after the result is known.

## D2 — Executability and main-line identification are separate questions

A **complete same-book quote can freeze a Class-B executable decision even when main-line status
is not visible.**

| label | when | freezes a decision? | outcome + CLV? | simulated-main-line placement comparison? |
|---|---|---|---|---|
| `book_designated` | the book visibly marks it default/main | yes | yes | **yes** |
| `MAIN_LINE_UNRESOLVED` | complete quote, main-line status not visible | **yes** | **yes**, against the **identical book and line** | **NO — excluded** |
| `ALT_LINE` | the image visibly shows an alternate rung | **yes** | **yes**, against the identical book and line | **NO — not the book's main market** |

CLV for either non-designated label is measured **against the identical book and line only** —
never against a different book's close, and never against a different rung.

**Refinement of §4 / A4, not a contradiction.** The earlier rule said an unresolved main line
meant "score nothing from that pitcher's line placement." D2 keeps that exclusion and separates
out what was conflated with it: the *executable decision* still freezes and is still scorable
for outcome and CLV. Only the *line-placement comparison against the simulated main line* is
excluded, because that comparison presumes we know which rung the book called its main market.

## D3 — Amendment window

Per B5, the 2026-07-27 amendment window **closes the moment the first qualifying capture is
received**. Sections A, B, C and D are the complete protocol for this slate. Anything discovered
after that moment is logged and deferred to the next untouched slate.
