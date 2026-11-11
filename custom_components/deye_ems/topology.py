"""CT at the utility boundary, a passive branch, then the inverter GRID port.

Both meters use positive import towards the house/inverter. Thus branch demand
is CT minus GRID-port power, even while the inverter supplies that branch.
No physical limiter or service calls are implemented by this calculation.
"""
import math


def ct_load_balance(load, load_phases, port, port_phases, ct, ct_phases):
    if any(not isinstance(v, (list, tuple)) or len(v) != 3
           for v in (load_phases, port_phases, ct_phases)):
        raise ValueError("invalid_ct_measurements")
    values = [load, port, ct, *load_phases, *port_phases, *ct_phases]
    if any(not isinstance(v, (float, int)) or isinstance(v, bool)
           or not math.isfinite(v) or abs(v) > 60000 for v in values):
        raise ValueError("invalid_ct_measurements")
    if load < -200 or any(v < -200 for v in load_phases):
        raise ValueError("invalid_load_measurements")
    for total, phases in ((load, load_phases), (port, port_phases), (ct, ct_phases)):
        if abs(total - sum(phases)) > max(300, .1 * max(abs(total), abs(sum(phases)))):
            raise ValueError("inconsistent_phase_totals")
    branch = [a-b for a, b in zip(ct_phases, port_phases)]
    if ct-port < -200 or any(v < -200 for v in branch):
        raise ValueError("negative_outside_load_check_ct_direction")
    outside = max(ct-port, sum(max(v, 0) for v in branch), 0)
    return {"outside_load_w": outside,
            "total_load_w": max(load, sum(max(v, 0) for v in load_phases), 0) + outside,
            "total_load_phases_w": [max(a, 0)+max(b, 0) for a, b in zip(load_phases, branch)],
            "load_and_grid_output_w": max(load, sum(max(v, 0) for v in load_phases), 0)
                                       + max(-port, sum(max(-v, 0) for v in port_phases), 0),
            "grid_w": ct, "grid_phases_w": list(ct_phases)}
