"""Bind a post-price review to the externally pinned replay manifest."""
import hashlib
import json
import re
from datetime import datetime, timezone

from .cbb_quote_chronology import PregameContext, parse_utc


class BundleError(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _unambiguous_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise BundleError("AMBIGUOUS_BOUND_DOCUMENT")
    return result


def _invalid_constant(_):
    raise BundleError("INVALID_BOUND_DOCUMENT")


class IncidentBundle:
    def __init__(self, root, manifest_sha256, card_sha256, card):
        if root is None or manifest_sha256 is None:
            raise BundleError("EVIDENCE_BUNDLE_REQUIRED")
        self.root = root
        manifest = self._bytes("SHA256SUMS.txt", manifest_sha256)
        self.pins = {}
        try:
            for line in manifest.decode("utf-8").splitlines():
                digest, path = line.split("  ", 1)
                if not re.fullmatch(r"[0-9a-f]{64}", digest) or path in self.pins:
                    raise ValueError
                self.pins[path] = digest
        except ValueError as exc:
            raise BundleError("INVALID_EVIDENCE_MANIFEST") from exc
        if not any(p.startswith("delivered/") and h == card_sha256 for p, h in self.pins.items()):
            raise BundleError("PRICED_CARD_NOT_BOUND")
        freeze = self._document("forecast-freeze.json", card.get("forecast_freeze_sha256"))
        protocol_hash = freeze.get("protocol_sha256")
        if not protocol_hash or protocol_hash != card.get("evaluation_protocol_sha256"):
            raise BundleError("PROTOCOL_NOT_BOUND")
        self.policy = self._document("evaluation-protocol.json", protocol_hash)
        self.seal = parse_utc(freeze.get("sealed_at_utc"), "INVALID_FORECAST_SEAL")
        if parse_utc(self.policy.get("registered_at_client_utc"), "INVALID_POLICY_TIME") > self.seal:
            raise BundleError("POLICY_AFTER_FORECAST_SEAL")
        census_hash = freeze.get("census_sha256")
        if not census_hash or self.policy.get("initial_schedule_sha256") != census_hash:
            raise BundleError("SCHEDULE_NOT_BOUND")
        census = self._document("census/events.json", census_hash, list)
        self.census = {}
        for row in census:
            if not isinstance(row, dict) or not isinstance(row.get("event_id"), str):
                raise BundleError("INVALID_SCHEDULE")
            eid = row["event_id"]
            self.census[eid] = None if eid in self.census else row
        files = freeze.get("files")
        if not isinstance(files, dict):
            raise BundleError("SCHEDULE_NOT_BOUND")
        path = "cbb/schedule-identity.json"
        self.schedule = self._document(path, files.get(path)).get("events")
        if not isinstance(self.schedule, dict):
            raise BundleError("INVALID_SCHEDULE")
        verification = self._document("verification.json", self.pins.get("verification.json"))
        if verification.get("card_sha256") != card_sha256:
            raise BundleError("VERIFICATION_CARD_MISMATCH")
        self.verified_at = parse_utc(verification.get("checked_utc"), "INVALID_VERIFICATION_TIME")
        if not self.seal <= self.verified_at <= datetime.now(timezone.utc):
            raise BundleError("VERIFICATION_TIME_OUT_OF_SEQUENCE")

    def _bytes(self, path, expected):
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise BundleError("MISSING_OR_INVALID_EVIDENCE_PIN")
        try:
            data = (self.root / path).read_bytes()
        except OSError as exc:
            raise BundleError("BOUND_FILE_UNAVAILABLE") from exc
        if hashlib.sha256(data).hexdigest() != expected:
            raise BundleError("BOUND_FILE_DIGEST_MISMATCH")
        return data

    def _document(self, path, expected, kind=dict):
        if not expected or self.pins.get(path) != expected:
            raise BundleError("DOCUMENT_NOT_BOUND")
        try:
            obj = json.loads(self._bytes(path, expected), object_pairs_hook=_unambiguous_fields,
                             parse_constant=_invalid_constant)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise BundleError("INVALID_BOUND_DOCUMENT") from exc
        if not isinstance(obj, kind):
            raise BundleError("INVALID_BOUND_DOCUMENT")
        return obj

    def context(self, event):
        eid = event["event_id"]
        census = self.census.get(eid)
        schedule = self.schedule.get(eid.removeprefix("CBB:"))
        if not isinstance(schedule, dict) or not isinstance(census, dict):
            raise BundleError("VERIFIED_SCHEDULE_UNAVAILABLE")
        if (schedule.get("state") != "PRE" or census.get("status") != "STATUS_SCHEDULED"
                or not schedule.get("ncaa_id") or type(event.get("neutral")) is not bool):
            raise BundleError("VERIFIED_SCHEDULE_UNAVAILABLE")
        for key in ("home_id", "away_id", "home", "away", "neutral"):
            if key not in event or event[key] != census.get(key) or event[key] != schedule.get(key):
                raise BundleError("EVENT_SCHEDULE_MISMATCH")
        tip = parse_utc(schedule.get("ncaa_start_time_utc"), "INVALID_VERIFIED_TIPOFF")
        for row in (census, schedule, event):
            if parse_utc(row.get("start_time_utc"), "INVALID_EVENT_START") != tip:
                raise BundleError("EVENT_START_MISMATCH")
        if self.policy.get("quote_cutoff_utc") is None:
            raise BundleError("POLICY_QUOTE_CUTOFF_MISSING")
        cutoff = parse_utc(self.policy["quote_cutoff_utc"], "INVALID_QUOTE_CUTOFF")
        return PregameContext(cutoff, tip, self.verified_at, self.seal)
