"""Missing-data receipt for local simulations of hypothetical games and seasons."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipelines.cards.missingness import content_digest, seal_audit, verify_audit


def finish(args, output, details, *, blocked=False):
    mode=args.command if hasattr(args,"command") else args.func.__name__.removeprefix("cmd_")
    scope=f"scenario/{args.sport}/{mode}"
    event_id=scope+(f"/{args.away}@{args.home}" if mode=="game" else "")
    products=(["coverage"] if blocked else ["winner","score_margin","total"] if mode=="game"
              else ["season_standings"]+([] if args.no_playoffs else ["postseason_probabilities"]))
    invocation={k:v for k,v in vars(args).items() if k not in
                {"func","games","ratings","json","audit_output","top","standings","source_evidence"}}
    bound={"scenario":invocation,"result":output,"source_evidence":args.source_evidence}
    binding=dict(league=args.sport,event_id=event_id,model_id=scope,products=products,forecast=bound)
    receipt=seal_audit(**binding,details={"scope":"USER_SUPPLIED_SCENARIO; NO_SOURCE_FRESHNESS_OR_REGISTRATION",
        "status":"BLOCKED" if blocked else "RESEARCH_ONLY","historical_support":"UNMEASURED",
        "thresholds":"UNREVIEWED",**details})
    packet={"binding":bound,"missingness_audit":receipt}
    if args.audit_output:
        path=Path(args.audit_output)
        with path.open("x") as handle:
            json.dump(packet,handle,sort_keys=True,allow_nan=False);handle.write("\n")
        packet=json.loads(path.read_bytes())
    if packet["binding"]!=bound or not verify_audit(packet["missingness_audit"],**binding):
        raise ValueError("SCENARIO_MISSINGNESS_READBACK")
    return packet


def rating_details(ratings, teams):
    teams=sorted(set(teams))
    return {"teams_using_average_rating":[t for t in teams if t not in ratings],
            "effective_rating_state_sha256":content_digest({t:vars(v) for t,v in ratings.items()}),
            "fallback_values":{"attack":1.,"defense":1.,"pace":1.,"elo":1500.},
            "interpretation":"Default team and field ratings express a league-average scenario; they do not establish observed team quality."}


def array_sha(data):
    return {"shape":list(data.shape),"dtype":str(data.dtype),
            "sha256":hashlib.sha256(data.tobytes()).hexdigest()}
