from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


@dataclass(frozen=True)
class RuleClaim:
    event_type: str
    status: str
    certainty: str
    evidence_text: str
    restriction_value: Any = None
    rule_id: str = ""

    def as_dict(self):
        return asdict(self)


SUBJECTIVE_ONLY = re.compile(r"\b(checked out|quit|gave up|no heart|doesn't care|does not care|calling it in|mailed it in)\b", re.I)
NEGATED_OUT = re.compile(r"\b(not out|not scratched|isn't out|is not out|will play|available tonight)\b", re.I)
PATTERNS = [
    ("starter_scratched", re.compile(r"\b(?:starter|pitcher)?\s*(?:has been |was |is )?scratched\b", re.I), "STARTER_SCRATCHED", "SCRATCHED", "CONFIRMED"),
    ("player_out", re.compile(r"\b(?:out tonight|will not play|won't play|ruled out|not in the lineup)\b", re.I), "PLAYER_OUT", "UNAVAILABLE", "CONFIRMED"),
    ("starter_confirmed", re.compile(r"\b(?:will start|gets the start|gets the ball|starting tonight|confirmed starter)\b", re.I), "STARTER_CONFIRMED", "CONFIRMED", "CONFIRMED"),
    ("bullpen_unavailable", re.compile(r"\b(?:unavailable|not available)\b.{0,60}\b(?:bullpen|relief|closer|reliever)\b|\b(?:bullpen|closer|reliever)\b.{0,60}\b(?:unavailable|not available)\b", re.I), "BULLPEN_UNAVAILABLE", "UNAVAILABLE", "CONFIRMED"),
    ("bullpen_limited", re.compile(r"\b(?:bullpen|closer|reliever)\b.{0,60}\b(?:limited|likely unavailable|may be unavailable)\b", re.I), "BULLPEN_LIMITED", "LIMITED", "EXPECTED"),
    ("lineup_confirmed", re.compile(r"\b(?:in the lineup|lineup is set|batting [1-9](?:st|nd|rd|th)?|returns to the lineup)\b", re.I), "LINEUP_CONFIRMED", "ACTIVE", "CONFIRMED"),
    ("roster_callup", re.compile(r"\b(?:recalled|called up|selected .* contract)\b", re.I), "ROSTER_CALLUP", "ACTIVE", "CONFIRMED"),
    ("roster_option", re.compile(r"\b(?:optioned|sent down|designated for assignment)\b", re.I), "ROSTER_OPTION", "INACTIVE", "CONFIRMED"),
    ("weather_delay", re.compile(r"\b(?:weather delay|delay risk|storms? expected|rain delay)\b", re.I), "WEATHER_DELAY_RISK", "RISK", "EXPECTED"),
]
PITCH_LIMIT = re.compile(r"\b(?:pitch limit|pitch count|capped at|limited to|around)\s*(?:about\s*)?(\d{2,3})\s*(?:pitches)?\b", re.I)


def extract_rule_claims(text: str) -> list[dict[str, Any]]:
    """Conservative deterministic claim hints.

    These are extraction candidates, not availability facts. Entity resolution, source policy,
    NLI/corroboration and PIT checks are performed downstream. Subjective effort language emits no claim.
    """
    if SUBJECTIVE_ONLY.search(text):
        return []
    claims: list[RuleClaim] = []
    m = PITCH_LIMIT.search(text)
    if m:
        claims.append(RuleClaim("STARTER_PITCH_LIMIT", "LIMITED", "EXPECTED", m.group(0), int(m.group(1)), "pitch_limit"))
    for rule_id, regex, event_type, status, certainty in PATTERNS:
        m = regex.search(text)
        if not m:
            continue
        if event_type in {"PLAYER_OUT", "STARTER_SCRATCHED"} and NEGATED_OUT.search(text):
            continue
        claims.append(RuleClaim(event_type, status, certainty, m.group(0), None, rule_id))
    seen = set()
    out = []
    for claim in claims:
        key = (claim.event_type, claim.status, claim.restriction_value)
        if key in seen:
            continue
        seen.add(key)
        out.append(claim.as_dict())
    return out
