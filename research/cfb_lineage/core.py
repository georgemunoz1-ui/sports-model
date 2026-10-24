"""Content-addressed CFB graph and exactly-once research state transitions.

Local atomicity/integrity, not a substitute for source licensing, independent
schedule attestation, offsite retention, or approved production release.
"""
from __future__ import annotations
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any

class GateError(ValueError):
    def __init__(self, reason: str, **details: Any):
        self.reason, self.details = reason, details
        super().__init__(reason + (":" + json.dumps(details, sort_keys=True) if details else ""))

def require(ok: bool, reason: str, **details: Any) -> None:
    if not ok:
        raise GateError(reason, **details)

def canonical(x: Any) -> bytes:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def digest(x: Any) -> str:
    return hashlib.sha256(canonical(x)).hexdigest()

def utc(value: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(t.tzinfo is not None, "TIMEZONE_REQUIRED")
    return t.astimezone(dt.timezone.utc)

def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()

def hash_ok(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None

class Store:
    """Immutable blobs/nodes; SQLite indices and transitions serialize writers.

    A content object is committed before its reference. A crash can leave an
    unreachable object, never a published reference to a partially written one.
    A semantic identifier cannot be rebound to different bytes.
    """
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "index.sqlite"
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS refs(id TEXT PRIMARY KEY, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS transitions(id TEXT PRIMARY KEY, parent TEXT NOT NULL, child TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS heads(lineage TEXT PRIMARY KEY, hash TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS refs_no_update BEFORE UPDATE ON refs BEGIN SELECT RAISE(ABORT,'IMMUTABLE_REF'); END;
            CREATE TRIGGER IF NOT EXISTS refs_no_delete BEFORE DELETE ON refs BEGIN SELECT RAISE(ABORT,'IMMUTABLE_REF'); END;
            CREATE TRIGGER IF NOT EXISTS transitions_no_update BEFORE UPDATE ON transitions BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TRANSITION'); END;
            CREATE TRIGGER IF NOT EXISTS transitions_no_delete BEFORE DELETE ON transitions BEGIN SELECT RAISE(ABORT,'IMMUTABLE_TRANSITION'); END;
            """)

    def connect(self):
        db = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return contextlib.closing(db)

    def blob(self, body: bytes) -> str:
        h = hashlib.sha256(body).hexdigest()
        target = self.objects / h
        fd, tmp = tempfile.mkstemp(dir=self.objects, prefix=".pending-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(body); f.flush(); os.fsync(f.fileno())
            try:
                os.link(tmp, target)
                directory_fd = os.open(self.objects, os.O_RDONLY)
                try: os.fsync(directory_fd)
                finally: os.close(directory_fd)
            except FileExistsError:
                require(target.read_bytes() == body, "CONTENT_ADDRESS_COLLISION")
        finally:
            os.unlink(tmp)
        return h

    def bytes(self, h: str) -> bytes:
        require(hash_ok(h), "INVALID_ARTIFACT_HASH")
        p = self.objects / h
        require(p.is_file(), "MISSING_ARTIFACT", hash=h)
        body = p.read_bytes()
        require(hashlib.sha256(body).hexdigest() == h, "ARTIFACT_HASH_MISMATCH", hash=h)
        return body

    def node(self, h: str) -> dict:
        n = json.loads(self.bytes(h))
        require(n.get("sport") == "CFB", "CROSS_SPORT_ARTIFACT")
        return n

    def put(self, kind: str, payload: dict, parents: dict[str, str] | None = None) -> str:
        parents = parents or {}
        for h in parents.values():
            self.verify(h)
        return self.blob(canonical({"schema":"cfb.artifact.v1", "sport":"CFB", "kind":kind,
                                    "parents":parents, "payload":payload}))

    def bind(self, semantic_id: str, h: str) -> None:
        self.verify(h)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT hash FROM refs WHERE id=?", (semantic_id,)).fetchone()
            require(old is None or old[0] == h, "IMMUTABLE_IDENTIFIER_CONFLICT", id=semantic_id)
            db.execute("INSERT OR IGNORE INTO refs VALUES (?,?)", (semantic_id, h))
            db.execute("COMMIT")

    def resolve(self, semantic_id: str) -> str:
        with self.connect() as db:
            r = db.execute("SELECT hash FROM refs WHERE id=?", (semantic_id,)).fetchone()
        require(r is not None, "UNREGISTERED_ARTIFACT", id=semantic_id)
        self.verify(r[0]); return r[0]

    def verify(self, root: str) -> dict:
        seen, active = set(), set()
        def visit(h):
            require(h not in active, "LINEAGE_CYCLE")
            if h in seen: return
            active.add(h); n = self.node(h)
            if n["kind"] == "raw_source": self.bytes(n["payload"]["raw_hash"])
            for parent in n["parents"].values(): visit(parent)
            active.remove(h); seen.add(h)
        visit(root)
        return {"status":"PASS", "root_hash":root, "node_count":len(seen), "hashes":sorted(seen)}

    def source(self, body: bytes, family: str, url: str, *, scope="RESEARCH", query=None) -> str:
        require(family.startswith(("cfb", "espn_cfb", "official_cfb", "weather", "market")), "SOURCE_FAMILY_NOT_CFB")
        return self.put("raw_source", {"raw_hash":self.blob(body), "source_family":family,
            "source_url":url, "query":query or {}, "retrieved_at":now(), "available_at":now(),
            "evidence_scope":scope, "publication_time_verified":False, "license_approval":"UNVERIFIED",
            "historical_as_of_certified":False})

    def dataset(self, rows: list[dict], source: str, family: str, adapter_version: str) -> str:
        src = self.node(source)
        require(src["kind"] == "raw_source" and src["payload"]["source_family"] == family, "SOURCE_FAMILY_MISMATCH")
        return self.put("canonical_dataset", {"rows":rows, "source_family":family, "adapter_version":adapter_version,
                        "available_at":src["payload"]["available_at"], "evidence_scope":src["payload"]["evidence_scope"]}, {"source":source})

SCHEDULE_KEYS = ("event_id", "season", "week", "home_id", "away_id", "kickoff", "neutral_site", "home_division", "away_division", "status", "home_score", "away_score")

def publish_schedule(store: Store, dataset_hash: str, registry_id: str, *, expected_scope: str) -> str:
    """Separate publisher enrollment. Update calls resolve this registered snapshot.

    The publisher's complete census and provider adapter must be reviewed before
    live use. Never accept caller-supplied schedule rows at the update boundary.
    """
    d = store.node(dataset_hash)
    require(d["kind"] == "canonical_dataset", "SCHEDULE_DATASET_REQUIRED")
    rows = d["payload"]["rows"]
    # A separate publisher cannot enroll an arbitrary subset of a raw snapshot.
    # This first adapter supports explicit, source-bound canonical JSON schedules.
    source = store.node(d["parents"]["source"])
    require(source["payload"]["source_family"] in ("cfb_schedule_canonical_json", "cfb_fixture_schedule"), "SCHEDULE_PUBLISHER_ADAPTER_NOT_VERIFIED")
    native = json.loads(store.bytes(source["payload"]["raw_hash"]))
    require(native == rows, "SCHEDULE_RAW_CENSUS_MISMATCH")
    require(bool(rows) and expected_scope in ("FBS_VS_FBS", "FULL_PROVIDER_WEEK"), "SCHEDULE_SCOPE_REQUIRED")
    require(len({r["event_id"] for r in rows}) == len(rows), "DUPLICATE_SCHEDULE_GAME")
    require(len({(r["season"],r["week"]) for r in rows}) == 1, "SCHEDULE_SINGLE_WEEK_REQUIRED")
    for r in rows:
        require(set(SCHEDULE_KEYS).issubset(r), "SCHEDULE_SCHEMA")
        require(r["home_id"] != r["away_id"], "TEAM_IDENTITY_COLLISION")
        require(type(r["neutral_site"]) is bool, "NEUTRAL_SITE_UNKNOWN")
        utc(r["kickoff"])
        require(r["status"] in ("FINAL", "PENDING", "POSTPONED", "CANCELLED"), "UNKNOWN_GAME_STATUS")
        if r["status"] == "FINAL":
            require(all(type(r[k]) is int and r[k] >= 0 for k in ("home_score", "away_score")), "FINAL_SCORES_REQUIRED")
        if expected_scope == "FBS_VS_FBS":
            require(r["home_division"] == r["away_division"] == "FBS", "DIVISION_BRIDGE_BLOCKED")
    payload = {"registry_id":registry_id, "scope":expected_scope, "rows":sorted(rows,key=lambda r:r["event_id"]),
        "game_ids":sorted(r["event_id"] for r in rows), "count":len(rows), "season":rows[0]["season"], "week":rows[0]["week"],
        "census_authority":"REGISTERED_PUBLISHER_NOT_INDEPENDENT_PROVIDER_VERIFICATION", "created_at":now(),
        "available_at":d["payload"]["available_at"], "evidence_scope":d["payload"]["evidence_scope"]}
    h = store.put("schedule", payload, {"dataset":dataset_hash}); store.bind(registry_id,h); return h

def validate_pbp(store: Store, pbp_hash: str, schedule: dict, cutoff: str) -> tuple[list[dict],dict]:
    n = store.node(pbp_hash); require(n["kind"] == "canonical_dataset", "PBP_DATASET_REQUIRED")
    require(utc(n["payload"]["available_at"]) <= utc(cutoff), "SOURCE_AFTER_CUTOFF")
    rows = n["payload"]["rows"]; games = {r["event_id"]:r for r in schedule["rows"]}
    ids = {r["event_id"] for r in rows}; extra = sorted(ids-set(games))
    require(not extra, "OUT_OF_SCOPE_PBP_GAME_IDS", game_ids=extra)
    require(set(games) == ids, "MISSING_COMPLETED_GAME", missing=sorted(set(games)-ids))
    require(len({(r["event_id"],r["play_id"]) for r in rows}) == len(rows), "DUPLICATE_PLAY_ID")
    require(len({(r["event_id"],r["sequence"]) for r in rows}) == len(rows), "DUPLICATE_PLAY_SEQUENCE")
    for r in rows:
        g = games[r["event_id"]]
        require((r["season"],r["week"]) == (g["season"],g["week"]), "PLAY_WEEK_BINDING")
        require((r["home_id"],r["away_id"]) == (g["home_id"],g["away_id"]), "PLAY_TEAM_BINDING")
        require(r["posteam"] in (g["home_id"],g["away_id"]), "PLAY_OFFENSE_BINDING")
        require(r["defteam"] in (g["home_id"],g["away_id"]) and r["defteam"] != r["posteam"], "PLAY_DEFENSE_BINDING")
        require(type(r["eligible"]) is bool and type(r["dropback"]) is bool, "PLAY_FLAG_UNITS")
        require(r["epa"] is None or (type(r["epa"]) in (float,int) and math.isfinite(r["epa"])), "INVALID_EPA")
        require(utc(r["available_at"]) <= utc(cutoff), "PLAY_AFTER_CUTOFF")
    for gid,g in games.items():
        final=max((r for r in rows if r["event_id"] == gid), key=lambda r:r["sequence"])
        require((final["home_score"],final["away_score"]) == (g["home_score"],g["away_score"]), "FINAL_SCORE_MISMATCH")
    return rows,{"accepted_game_ids":sorted(ids), "accepted_rows":len(rows), "out_of_scope_game_ids":extra,
                  "schedule_game_set_hash":digest(sorted(games)), "status":"PASS"}

def seed_state(store: Store, lineage: str, season: int, completed_week: int = 0) -> str:
    state={"lineage":lineage,"season":season,"completed_week":completed_week,"teams":{},"qbs":{},"processed_games":{},
           "processed_player_games":[],"source_family":None,"action_authority":False,"status":"RESEARCH_ONLY","created_at":now()}
    h=store.put("weekly_state",state)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        r=db.execute("SELECT hash FROM heads WHERE lineage=?",(lineage,)).fetchone()
        require(r is None or r[0]==h,"LINEAGE_ALREADY_INITIALIZED")
        db.execute("INSERT OR IGNORE INTO heads VALUES (?,?)",(lineage,h));db.execute("COMMIT")
    return h

def update_week(store: Store, parent_hash: str, registry_id: str, requested_ids: list[str], pbp_hash: str, cutoff: str, *, updater_version="cfb.observation_accumulator.v1") -> dict:
    """Atomic team+QB observation state, not a newly fitted predictive rating model."""
    require(utc(cutoff)<=utc(now()),"FUTURE_UPDATE_CUTOFF")
    sh=store.resolve(registry_id);sn=store.node(sh);require(sn["kind"]=="schedule","REGISTERED_SCHEDULE_REQUIRED");s=sn["payload"]
    require(s["scope"]=="FBS_VS_FBS","DIVISION_BRIDGE_BLOCKED")
    require(len(requested_ids)==len(set(requested_ids)) and sorted(requested_ids)==s["game_ids"],
            "AUTHORITATIVE_SCHEDULE_COVERAGE_MISMATCH",expected_games=s["count"],provided_games=len(requested_ids),missing_games=len(set(s["game_ids"])-set(requested_ids)))
    require(utc(s["available_at"])<=utc(cutoff),"SCHEDULE_AFTER_CUTOFF")
    if any(r["status"] != "FINAL" for r in s["rows"]):
        return {"status":"WITHHELD","reason":"WEEK_INCOMPLETE_OR_DISPOSITION_REVIEW","state_published":False}
    rows,scope=validate_pbp(store,pbp_hash,s,cutoff)
    p=store.node(parent_hash);require(p["kind"]=="weekly_state","PARENT_STATE_REQUIRED");parent=p["payload"]
    require(utc(parent["created_at"])<=utc(cutoff),"PARENT_STATE_AFTER_CUTOFF")
    require(all(utc(g["kickoff"])<utc(cutoff) for g in s["rows"]),"COMPLETED_GAME_START_AFTER_CUTOFF")
    family=store.node(pbp_hash)["payload"]["source_family"]
    require(parent["source_family"] in (None,family),"SOURCE_FAMILY_CHANGED_REQUIRES_NEW_LINEAGE")
    hashes={gid:digest(sorted(({k:v for k,v in r.items() if k!="available_at"} for r in rows if r["event_id"]==gid),key=lambda r:r["sequence"])) for gid in s["game_ids"]}
    for gid,h in hashes.items():
        if gid in parent["processed_games"]:
            old=parent["processed_games"][gid]["content_hash"]
            raise GateError("DUPLICATE_GAME_STATE_TRANSITION" if old==h else "SOURCE_REVISION_REQUIRES_NEW_RECONCILIATION",game_id=gid)
    require(parent["season"]==s["season"] and parent["completed_week"]+1==s["week"],"WEEKLY_PARENT_MISMATCH")
    tid=digest({"parent":parent_hash,"schedule":sh,"games":hashes,"updater":updater_version,"feature_schema":"cfb.observed_team_qb.v1"})
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        prior=db.execute("SELECT child FROM transitions WHERE id=?",(tid,)).fetchone()
        if prior:
            store.verify(prior[0]);db.execute("COMMIT")
            return {"status":"REPLAY_NOOP","transition_id":tid,"child_state_hash":prior[0],"state_published":False}
        head=db.execute("SELECT hash FROM heads WHERE lineage=?",(parent["lineage"],)).fetchone()
        require(head is not None and head[0]==parent_hash,"STALE_PARENT_OR_SOURCE_REVISION")
        child=json.loads(canonical(parent));child["completed_week"]=s["week"];child["source_family"]=family
        processed=set(child["processed_player_games"])
        for r in sorted(rows,key=lambda r:(r["event_id"],r["sequence"])):
            if not r["eligible"]:continue
            for team,side in ((r["posteam"],"off"),(r["defteam"],"def")):
                st=child["teams"].setdefault(team,{"off_epa_sum":0.,"def_epa_allowed_sum":0.,"off_n":0,"def_n":0})
                if r["epa"] is not None:
                    key="off_epa_sum" if side=="off" else "def_epa_allowed_sum";st[key]+=r["epa"];st[side+"_n"]+=1
            if r["dropback"]:
                require(bool(r.get("player_id")),"STABLE_QB_ID_REQUIRED")
                qb=child["qbs"].setdefault(r["player_id"],{"epa_sum":0.,"observed_dropbacks":0})
                if r["epa"] is not None:qb["epa_sum"]+=r["epa"];qb["observed_dropbacks"]+=1
                processed.add(r["event_id"]+":"+r["player_id"])
        child["processed_player_games"]=sorted(processed)
        child["processed_games"].update({gid:{"content_hash":h,"transition_id":tid} for gid,h in hashes.items()})
        child["parent_state_hash"]=parent_hash;child["transition_id"]=tid;child["created_at"]=now()
        ch=store.put("weekly_state",child,{"parent_state":parent_hash,"schedule":sh,"pbp":pbp_hash})
        db.execute("INSERT INTO transitions VALUES (?,?,?)",(tid,parent_hash,ch))
        db.execute("UPDATE heads SET hash=? WHERE lineage=? AND hash=?",(ch,parent["lineage"],parent_hash))
        require(db.execute("SELECT changes()").fetchone()[0]==1,"PARENT_COMPARE_AND_SWAP_FAILED")
        db.execute("COMMIT")
    return {"status":"PUBLISHED_RESEARCH_STATE","transition_id":tid,"child_state_hash":ch,"state_published":True,"scope_receipt":scope,"action_authority":False}
