"""Read-only view of proven native report receipt, never an HA state update.

Original HA availability, units, numeric values and timestamp validity remain
mandatory. Only a later matching native packet, confirmed by another fresh
packet in the same connection, can supplement an old HA last_reported. Its
receipt dates the value, separately from the earlier confirmation receipt.
Neither is the time of the Modbus measurement acquisition.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ReportedState:
    original: Any
    receipt: datetime | None = None
    provider_unavailable: bool = False

    def __getattr__(self, name):
        return getattr(self.original, name)

    @property
    def state(self):
        return "unavailable" if self.provider_unavailable else self.original.state

    @property
    def last_reported(self):
        return self.receipt if self.receipt is not None else getattr(self.original, "last_reported", None)

    @property
    def timestamp_source(self):
        return "esphome_live" if self.receipt is not None else "home_assistant"

    @property
    def stream_samples(self):
        return 2 if self.receipt is not None else 0


def effective_state(entity_id, original, provider, now, validation, *, number, stamp):
    """Preserve every original guard and reject action/register state proxies."""
    if (original is None or provider is None or validation is None
            or not isinstance(entity_id, str) or not entity_id.startswith("sensor.")):
        return original
    attributes = getattr(original, "attributes", {})
    value = number(original.state)
    reported = stamp(getattr(original, "last_reported", None) or getattr(original, "last_updated", None))
    unit = validation.get("unit")
    if (attributes.get("restored", False) or value is None or reported is None or reported > now.timestamp()
            or unit is not None and attributes.get("unit_of_measurement") != unit
            or validation.get("low") is not None and value < validation["low"]
            or validation.get("high") is not None and value > validation["high"]):
        return original
    try:
        if provider.source_invalid(entity_id):
            return ReportedState(original, provider_unavailable=True)
        proof = provider.effective_report(entity_id, original, now, validation)
    except Exception:
        # A provider lifecycle failure cannot establish fresh communication.
        return ReportedState(original, provider_unavailable=True)
    receipt = proof.get("reported_at") if isinstance(proof, dict) else None
    confirmed = proof.get("confirmed_at") if isinstance(proof, dict) else None
    age = number(validation.get("age"))
    if (not isinstance(receipt, datetime) or receipt.tzinfo is None
            or not isinstance(confirmed, datetime) or confirmed.tzinfo is None
            or age is None or age <= 0
            or proof.get("source") != "esphome_live" or proof.get("samples") != 2
            or not confirmed <= receipt <= now
            or not 0 <= (now-confirmed).total_seconds() <= age
            or not reported < receipt.timestamp()):
        return original
    return ReportedState(original, receipt=receipt)
