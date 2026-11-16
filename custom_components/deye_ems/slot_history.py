"""Display-only historical SoC, with no interpolation over missing states."""
from bisect import bisect_right
from datetime import datetime


def add_actual_soc(rows, history):
    """State held by HA at each boundary, independently of saved forecasts."""
    def stamp(value):
        try:
            at = datetime.fromisoformat(value)
            return at.timestamp() if at.tzinfo is not None else None
        except (ValueError, TypeError):
            return None

    through = stamp(history.get("through"))
    samples = sorted((at, value) for raw, value in history.get("samples", [])
                     if (at := stamp(raw)) is not None)
    times = [at for at, _ in samples]

    def value_at(raw):
        at = stamp(raw)
        if at is None or through is None or at > through:
            return None
        index = bisect_right(times, at) - 1
        value = samples[index][1] if index >= 0 else None
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100 else None

    return [{**row, "actual_soc_start_percent": value_at(row["start"]),
             "actual_soc_end_percent": value_at(row["end"]),
             "actual_soc_source": "ha_recorder"} for row in rows]
