"""Scoped NHL capture using the reviewed atomic collector's receipt primitives.

Interrupted raw bytes never become evidence without a committed exact receipt.
The five nonexistent team seasons are scope exclusions, not successful requests.
"""
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass

from scripts.nhl_history_applicability import SCOPE_SHA256, history_urls, load_scope

RECEIPT_SCHEMA = "sports.exact_source_receipt.v1"
HOSTS = {"site.api.espn.com"}


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def instant(value):
    if not isinstance(value, str) or not value:
        raise ValueError("TIMESTAMP_STRING_REQUIRED")
    x = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if x.tzinfo is None:
        raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return x.astimezone(dt.timezone.utc)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def inside(root, relative):
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("UNSAFE_RELATIVE_PATH")
    target = root / p
    cursor = root
    for part in p.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("SYMLINK_PATH_FORBIDDEN")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("PATH_ESCAPES_ROOT")
    return target


def atomic(path, data, *, replace=False, hook=None, stage="write"):
    """fsync bytes, publish one file atomically, then fsync its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        raise FileExistsError("IMMUTABLE_PATH_EXISTS:" + str(path))
    temp = path.with_name("." + path.name + ".pending-" + uuid.uuid4().hex)
    with temp.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    if hook:
        hook("before_" + stage + "_commit", path)
    if replace:
        os.replace(temp, path)
    else:
        # link is atomic and fails if another writer has published this name.
        os.link(temp, path)
        temp.unlink()
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    if hook:
        hook("after_" + stage + "_commit", path)


def public_url(url):
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or u.hostname not in HOSTS or u.username or u.password:
        raise ValueError("UNAPPROVED_PUBLIC_SOURCE_URL")
    if u.port not in (None, 443) or u.fragment:
        raise ValueError("UNSAFE_PUBLIC_SOURCE_URL")
    if any(re.search(r"token|password|secret|api.?key", k, re.I)
           for k in urllib.parse.parse_qs(u.query)):
        raise ValueError("CREDENTIAL_QUERY_FORBIDDEN")
    return url


def source_id(spec):
    return digest(encoded({k: v for k, v in spec.items() if k != "id"}))


@dataclass
class Response:
    body: bytes
    status: int
    headers: dict
    final_url: str


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)  # Refuse before following an unapproved destination.
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_transport(spec, *, timeout=25, max_bytes=80_000_000):
    request = urllib.request.Request(public_url(spec["url"]), headers={
        "User-Agent": "sports-model-exact-source-capture/1.0", "Accept": "*/*"})
    try:
        response = urllib.request.build_opener(PublicRedirect()).open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError("RESPONSE_SIZE_LIMIT")
        return Response(body, response.status, dict(response.headers), response.url)


def validate_body(spec, body):
    if spec.get("expected_sha256") and digest(body) != spec["expected_sha256"]:
        raise ValueError("EXPECTED_SOURCE_HASH_MISMATCH")
    if spec["format"] == "parquet":
        if len(body) < 12 or body[:4] != b"PAR1" or body[-4:] != b"PAR1":
            raise ValueError("PARQUET_MAGIC_INVALID")
        return None
    p = json.loads(body)
    if not isinstance(p, dict):
        raise ValueError("JSON_OBJECT_REQUIRED")
    if spec["validator"] == "nhl_team_season":
        if str(p["team"]["id"]) != spec["team_id"]:
            raise ValueError("SOURCE_TEAM_MISMATCH")
        if p["requestedSeason"]["year"] != spec["provider_season"]:
            raise ValueError("REQUESTED_SEASON_MISMATCH")
        if not isinstance(p.get("events"), list):
            raise ValueError("EVENT_ARRAY_REQUIRED")
        if any(e["season"]["year"] != spec["provider_season"] for e in p["events"]):
            raise ValueError("EVENT_SEASON_MISMATCH")
    if spec["validator"] == "scoreboard":
        if not isinstance(p.get("events"), list) or len(p["events"]) >= 1000:
            raise ValueError("SCOREBOARD_CENSUS_INVALID")
        for e in p["events"]:
            instant(e["date"])
            c = e["competitions"]
            if len(c) != 1 or len(c[0]["competitors"]) != 2:
                raise ValueError("COMPETITION_IDENTITY")
            if {t["homeAway"] for t in c[0]["competitors"]} != {"home", "away"}:
                raise ValueError("TEAM_SIDE_IDENTITY")
    return p


def verified_receipt(root, spec, receipt, *, now, max_age_hours):
    if not isinstance(receipt, dict):
        raise ValueError("RECEIPT_OBJECT_REQUIRED")
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("spec_id") != spec["id"]:
        raise ValueError("RECEIPT_IDENTITY")
    if receipt.get("status") != "CAPTURED" or receipt.get("http_status") != 200:
        raise ValueError("RECEIPT_NOT_CAPTURED")
    if receipt.get("timestamp_evidence_type") != "EXACT_TRANSPORT_RECEIPT":
        raise ValueError("EXACT_TRANSPORT_TIMESTAMP_REQUIRED")
    requested, retrieved = map(instant, (receipt["requested_at_utc"], receipt["retrieved_at_utc"]))
    if not requested <= retrieved <= instant(now):
        raise ValueError("RECEIPT_TIME_ORDER")
    if (instant(now) - retrieved).total_seconds() > max_age_hours * 3600:
        raise ValueError("RECEIPT_EXPIRED")
    if receipt.get("url") != spec["url"]:
        raise ValueError("RECEIPT_URL_MISMATCH")
    public_url(receipt["final_url"])
    if any(receipt.get(k) != spec[k] for k in ("league", "kind")):
        raise ValueError("RECEIPT_SOURCE_KIND_MISMATCH")
    attempt = receipt.get("attempt_id")
    if not isinstance(attempt, str) or not re.fullmatch("[0-9a-f]{32}", attempt):
        raise ValueError("RECEIPT_ATTEMPT_IDENTITY")
    ext = ".json" if spec["format"] == "json" else ".parquet"
    if receipt["raw_path"] != f"raw/{spec['id']}/{attempt}/body{ext}":
        raise ValueError("RECEIPT_RAW_PATH_IDENTITY")
    raw = inside(root, receipt["raw_path"]).read_bytes()
    if digest(raw) != receipt["raw_sha256"] or digest(raw) != receipt.get("sha256") or len(raw) != receipt["bytes"]:
        raise ValueError("RAW_HASH_OR_SIZE_MISMATCH")
    validate_body(spec, raw)
    return raw


def reuse(root, spec, now, max_age_hours):
    found = []
    invalid = []
    journal = inside(root, "journal/" + spec["id"])
    for f in sorted(journal.glob("*.json")) if journal.exists() else []:
        try:
            receipt = json.loads(inside(root, str(f.relative_to(root))).read_text())
            verified_receipt(root, spec, receipt, now=now, max_age_hours=max_age_hours)
            if f.stem != receipt["attempt_id"]:
                raise ValueError("JOURNAL_ATTEMPT_IDENTITY")
            found.append(receipt)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            invalid.append({"receipt_path": str(f.relative_to(root)), "reason": str(exc)})
    # A preserved raw file without a committed receipt is deliberately ignored.
    found.sort(key=lambda r: instant(r["retrieved_at_utc"]))
    return (found[-1] if found else None), invalid


def capture_one(root, spec, transport, clock, hook=None):
    attempt = uuid.uuid4().hex
    ext = ".json" if spec["format"] == "json" else ".parquet"
    raw_path = f"raw/{spec['id']}/{attempt}/body{ext}"
    receipt_path = f"journal/{spec['id']}/{attempt}.json"
    r = {"schema": RECEIPT_SCHEMA, "spec_id": spec["id"], "attempt_id": attempt,
         "league": spec["league"], "kind": spec["kind"], "url": spec["url"],
         "evidence_tier": spec.get("evidence_tier", 2), "requested_at_utc": clock(),
         "provider_observed_at_utc": None, "historical_pregame_eligibility": False,
         "timestamp_evidence_type": "EXACT_TRANSPORT_RECEIPT"}
    try:
        response = transport(spec)
        r["retrieved_at_utc"] = clock()
    except Exception as exc:
        r.update(status="FAILED", error_type=type(exc).__name__, error=str(exc),
                 failed_at_utc=clock(), retrieved_at_utc=None, http_status=None)
    else:
        # An interruption here never promotes the orphan bytes into a receipt.
        atomic(inside(root, raw_path), response.body, hook=hook, stage="raw")
        r.update(http_status=response.status, final_url=response.final_url,
                 headers={k: v for k, v in response.headers.items()
                          if k.lower() not in {"set-cookie", "authorization"}},
                 raw_path=raw_path, raw_sha256=digest(response.body),
                 sha256=digest(response.body), bytes=len(response.body))
        try:
            if response.status != 200:
                raise ValueError("HTTP_STATUS:" + str(response.status))
            public_url(response.final_url)
            if instant(r["retrieved_at_utc"]) < instant(r["requested_at_utc"]):
                raise ValueError("TRANSPORT_CLOCK_REGRESSION")
            parsed = validate_body(spec, response.body)
            r.update(status="CAPTURED", parse_status="JSON_PARSED" if parsed is not None else "PARQUET_MAGIC_VERIFIED")
            # Quotes intentionally have no inferred provider observation time.
            if parsed is not None and spec["kind"] == "team_season_schedule":
                observed = parsed.get("timestamp")
                if observed is not None:
                    try:
                        instant(observed)
                        r["provider_observed_at_utc"] = observed
                    except ValueError:
                        r["provider_timestamp_warning"] = "UNPARSEABLE_PROVIDER_TIMESTAMP_RETAINED_IN_RAW"
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            r.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
    # Receipt is fully committed before the caller can request the next source.
    atomic(inside(root, receipt_path), encoded(r), hook=hook, stage="receipt")
    return r


def manifest(root):
    files = {str(p.relative_to(root)): digest(inside(root, str(p.relative_to(root))).read_bytes())
             for p in sorted(root.rglob("*")) if p.is_file() and p.name != "manifest.json"}
    atomic(inside(root, "manifest.json"), encoded(files), replace=True)


def history_plan(scope):
    specs = []
    for url in sorted(history_urls()):
        parsed = urllib.parse.urlparse(url)
        spec = {'group': 'history', 'league': 'nhl', 'kind': 'team_season_schedule',
                'url': url, 'format': 'json', 'validator': 'nhl_team_season',
                'team_id': parsed.path.split('/teams/')[1].split('/')[0],
                'provider_season': int(urllib.parse.parse_qs(parsed.query)['season'][0]),
                'evidence_tier': 2}
        spec['id'] = source_id(spec)
        specs.append(spec)
    return {'schema': 'nhl.atomic_history_plan.v1', 'season_scope_sha256': SCOPE_SHA256,
            'inapplicable_team_seasons': scope['nonexistent_team_seasons'],
            'sources': specs, 'action_authority': False}


def export_history(root, plan, selected, invalid, clock, *, complete=False):
    sources = [selected[s['id']] for s in plan['sources'] if s['id'] in selected]
    pending = len(plan['sources']) - sum(r['status'] == 'CAPTURED' for r in sources)
    report = {'schema': 'nhl.atomic_history_capture.v1', 'season_scope_sha256': SCOPE_SHA256,
              'inapplicable_team_seasons': plan['inapplicable_team_seasons'],
              'created_at_utc': clock(), 'sources': sources, 'expected_source_count': 219,
              'pending_requests': pending, 'status': 'COMPLETE' if complete and not pending else 'INCOMPLETE',
              'invalid_previous_receipts': invalid, 'action_authority': False}
    atomic(inside(root, 'report.json'), encoded(report), replace=True)
    manifest(root)
    return report


def access_denied(row):
    """Recognize explicit origin/proxy denials without treating generic URL errors as denials."""
    if not isinstance(row, dict) or row.get('status') != 'FAILED':
        return False
    return row.get('http_status') in (401, 403) or bool(re.search(
        r'Tunnel connection failed:\s*(?:401|403)\b', str(row.get('error', '')), re.IGNORECASE))


def collect_history(output, scope_path, *, resume=False, transport=None, clock=utc, hook=None):
    """Reuse only committed, hash-valid exact receipts that are still within six hours."""
    scope = load_scope(scope_path)
    plan = history_plan(scope)
    output = Path(output)
    if output.is_symlink():
        raise ValueError('SYMLINK_OUTPUT_ROOT_FORBIDDEN')
    output = output.resolve()
    identity = encoded(plan)
    if output.exists():
        if not resume:
            raise FileExistsError('FRESH_ROOT_REQUIRED')
        if inside(output, 'capture-plan.json').read_bytes() != identity:
            raise ValueError('RESUME_PLAN_MISMATCH')
    else:
        if resume:
            raise FileNotFoundError('RESUME_ROOT_MISSING')
        output.mkdir(parents=True, exist_ok=False)
        atomic(inside(output, 'capture-plan.json'), identity)
    transport = transport or http_transport
    with inside(output, '.collector.lock').open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        selected = {}; invalid = []
        for spec in plan['sources']:
            retained, problems = reuse(output, spec, clock(), 6)
            invalid.extend(problems)
            if retained is None:
                for path in inside(output, 'journal/' + spec['id']).glob('*.json'):
                    try:
                        prior = json.loads(path.read_text())
                    except (OSError, ValueError):
                        continue
                    if access_denied(prior) and prior.get('spec_id') == spec['id'] and prior.get('url') == spec['url']:
                        raise PermissionError('SOURCE_ACCESS_DENIED_REQUIRES_REVIEW:' + spec['url'])
            selected[spec['id']] = retained or capture_one(output, spec, transport, clock, hook)
            if selected[spec['id']]['status'] != 'CAPTURED':
                # Preserve the failure and stop; no automatic network retry or alternate route.
                return export_history(output, plan, selected, invalid, clock)
        # Recheck every selected receipt at completion; elapsed capture time cannot refresh it.
        for spec in plan['sources']:
            row = selected[spec['id']]
            if row['status'] == 'CAPTURED':
                verified_receipt(output, spec, row, now=clock(), max_age_hours=6)
        return export_history(output, plan, selected, invalid, clock, complete=True)
