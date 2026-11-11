"""The reserve is configurable, but never below the inverter low-SoC + 5pp."""
import math


def reserve_lower_bound(low_soc):
    if (not isinstance(low_soc, (float, int)) or isinstance(low_soc, bool)
            or not math.isfinite(low_soc) or not 0 <= low_soc <= 85):
        raise ValueError("Battery low SOC musi być poprawnym odczytem od 0 do 85%.")
    return math.ceil(low_soc + 5)


def reserve_bound_from_state(state):
    if (state is None or isinstance(state.state, bool) or state.attributes.get("restored", False)
            or state.attributes.get("unit_of_measurement") != "%"):
        return None
    try:
        return reserve_lower_bound(float(state.state))
    except (ValueError, TypeError):
        return None
