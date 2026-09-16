# 30. A hash of my own record is not a source, and an echoed timestamp is not an observation

2026-08-24. Two directives landed together and they turned out to be the same lesson twice.

**The evidence.** When the owner relayed the 8/23 scoreboard I wrote a JSON record, hashed it, and
bound fifteen canonical rows and fifteen grades to that hash. Every binding verifies. None of them
means what a tier-1 binding is supposed to mean. A hash over my own transcription proves exactly one
thing — that I have not altered the transcription since writing it. It is tamper-evidence on *my*
record. The artifact it commits to is my record, not the scoreboard. "MLB scoreboard" names a class
of source; a tier-1 binding needs the artifact.

Auditing for it found the same defect in **every owner-relay row in the table** — 123 rows across 11
dates, not the 15 I had just written. Downgrading the 15 and leaving 108 would have been a rule that
never runs.

**The timestamp.** Prospectivity rested on a git commit date: written by my machine, settable with
one environment variable. Fetching it back from the GitHub API returns the same author-written
field, echoed. That round trip *feels* like verification and is a service repeating my claim. The
repository has no workflow runs and no releases, so no clock but mine ever stamped anything
referencing that commit.

Both errors have one shape: **I checked that a record was internally consistent and read that as
externally corroborated.** A hash is integrity, not provenance. An API round trip is retrieval, not
observation. In both cases the artifact I was pointing at was one I had authored, and in both cases
the check I ran would have passed just as cleanly if I had made the contents up.

The test that separates them: *could this have been produced by me alone?* If yes, it is
self-assertion however well hashed, however remote the URL it came back from. Corroboration requires
something the other party generated — a source artifact someone else can go and read, a timestamp a
service created for its own reasons.

Neither downgrade says a number is wrong. The 8/23 scores reproduce the owner's own stated summary
exactly and the commit sits in a long consistent chain. PROVISIONAL and SELF_ASSERTED are resting
states, not accusations, and one addendum promotes them. What is not allowed is calling them proven
in the meantime.
