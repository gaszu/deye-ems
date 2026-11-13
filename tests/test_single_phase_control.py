"""Single-phase Deye limits with one- or three-phase utility CTs, offline."""
import unittest

from test_grid_control import (calculate_grid_charge, calculate_grid_charge_cap,
                               calculate_grid_charge_increase_cap, snapshot)


def single_snapshot(*, phase=0, connection=1, **changes):
    native = [0., 0., 0.]
    native[phase] = 1200.
    data = snapshot(
        inverter_phases=1, connection_phases=connection,
        inverter_phase_index=phase, grid_charge_balanced=True,
        load_w=1200., load_phases_w=list(native),
        grid_w=1200., grid_phases_w=list(native),
        grid_port_w=1200., grid_port_phases_w=list(native),
        grid_port_load_w=1200., grid_port_load_phases_w=list(native),
        total_limit_w=12000., phase_limit_w=5000.,
        conversion_total_limit_w=6000., conversion_phase_limit_w=6000.,
        inverter_grid_import_limit_w=6000., inverter_grid_phase_limit_w=6000.)
    data.update(changes)
    return data


class SinglePhaseControl(unittest.TestCase):
    def test_single_phase_ignores_balancing_flag_and_uses_one_phase_budget(self):
        g = single_snapshot()
        result = calculate_grid_charge_cap(g)
        self.assertTrue(result["telemetry_ok"])
        self.assertEqual(result["phase_model"], "single_phase")
        # 5 kW phase minus 250 W margin minus 1200 W load, at60W/A.
        self.assertEqual(result["cap_a"], 59)
        self.assertEqual(result, calculate_grid_charge_cap({**g, "grid_charge_balanced": False}))

    def test_total_connection_limit_can_bind_before_phase_limit(self):
        result = calculate_grid_charge_cap(single_snapshot(total_limit_w=3000.))
        self.assertEqual(result["cap_a"], 21)

    def test_converter_one_phase_rating_cannot_be_tripled(self):
        result = calculate_grid_charge_cap(single_snapshot(
            conversion_total_limit_w=12000., conversion_phase_limit_w=1500.))
        self.assertEqual(result["converter_cap_a"], 25)
        self.assertEqual(result["cap_a"], 25)

    def test_single_phase_inverter_on_l2_with_three_phase_house(self):
        g = single_snapshot(phase=1, connection=3,
            load_w=6200., load_phases_w=[4000., 1200., 1000.],
            grid_w=6200., grid_phases_w=[4000., 1200., 1000.])
        result = calculate_grid_charge_cap(g)
        self.assertTrue(result["telemetry_ok"])
        # L1 is busier, but charging is connected toL2. L2 headroom is3550W.
        self.assertEqual(result["cap_a"], 59)
        increase = calculate_grid_charge_increase_cap(g)
        self.assertEqual(increase["increase_cap_a"], 59)

    def test_ct_total_load_still_counts_every_phase_once(self):
        result = calculate_grid_charge_cap(single_snapshot(phase=1, connection=3,
            load_w=10000., load_phases_w=[4400., 1200., 4400.],
            grid_w=10000., grid_phases_w=[4400., 1200., 4400.]))
        self.assertEqual(result["cap_a"], 25)

    def test_same_phase_overload_reduces_without_waiting_for_ordinary_gate(self):
        g = single_snapshot(phase=2, connection=3, current_a=50., last_attempt_a=50.,
            last_attempt_ts=999., ordinary_last_possible_ts=999.,
            load_w=3000., load_phases_w=[500., 500., 2000.],
            grid_w=6000., grid_phases_w=[500., 500., 5000.],
            grid_port_w=5000., grid_port_phases_w=[0., 0., 5000.],
            grid_port_load_w=2000., grid_port_load_phases_w=[0., 0., 2000.])
        result = calculate_grid_charge(g)
        self.assertTrue(result["safety"])
        self.assertTrue(result["write"])
        self.assertEqual(result["feedback_cap_a"], 45)
        self.assertEqual(result["next_a"], 45)

    def test_other_phase_overload_stops_charging_without_fictitious_partial_correction(self):
        g = single_snapshot(phase=1, connection=3, current_a=50., last_attempt_a=50.,
            last_attempt_ts=999., ordinary_last_possible_ts=999.,
            load_w=7000., load_phases_w=[4800., 1200., 1000.],
            grid_w=7000., grid_phases_w=[4800., 1200., 1000.])
        result = calculate_grid_charge(g)
        self.assertEqual(result["reason"], "connection_other_phase_headroom")
        self.assertEqual(result["feedback_cap_a"], 0)
        self.assertEqual(result["next_a"], 0)
        self.assertFalse(result["grid_within_limits"])
        self.assertTrue(result["safety"])
        self.assertTrue(result["write"])

    def test_other_phase_overload_cannot_start_zero_register(self):
        g = single_snapshot(connection=3,
            load_w=7000., load_phases_w=[1200., 4800., 1000.],
            grid_w=7000., grid_phases_w=[1200., 4800., 1000.])
        self.assertEqual(calculate_grid_charge_increase_cap(g)["increase_cap_a"], 0)
        result = calculate_grid_charge(g)
        self.assertEqual(result["next_a"], 0)
        self.assertFalse(result["write"])

    def test_native_port_phase_limit_is_independent_of_connection(self):
        result = calculate_grid_charge_cap(single_snapshot(phase=2, connection=3,
            inverter_grid_phase_limit_w=2500.))
        self.assertEqual(result["cap_a"], 17)

    def test_bms_and_deye_limits_remain_exact(self):
        for changes, expected in (({"bms_cap_a": 12.}, 12),
                                  ({"deye_cap_a": 17.}, 17),
                                  ({"actuator_cap_a": 8.}, 8)):
            self.assertEqual(calculate_grid_charge_cap(single_snapshot(**changes))["cap_a"], expected)

    def test_unconnected_native_measurement_is_not_silently_ignored(self):
        for field in ("grid_port_phases_w", "grid_port_load_phases_w"):
            for values in ([1200., 1., 0.], [1200., None, 0.], [1200., 0.]):
                with self.subTest(field=field, values=values):
                    result = calculate_grid_charge_cap(single_snapshot(**{field: values}))
                    self.assertFalse(result["telemetry_ok"])
                    self.assertEqual(result["cap_a"], 0)

    def test_single_phase_connection_rejects_phantom_other_phase_ct(self):
        for field in ("grid_phases_w", "load_phases_w"):
            result = calculate_grid_charge_cap(single_snapshot(**{field: [1200., 10., 0.]}))
            self.assertFalse(result["telemetry_ok"])

    def test_invalid_layout_fails_closed(self):
        for changes in ({"inverter_phases": 2}, {"inverter_phases": True},
                        {"connection_phases": None}, {"connection_phases": "3"},
                        {"inverter_phase_index": 3}, {"inverter_phase_index": True},
                        {"connection_phases": 1, "inverter_phase_index": 1},
                        {"inverter_phases": 3, "connection_phases": 1}):
            with self.subTest(changes=changes):
                result = calculate_grid_charge(single_snapshot(current_a=50., last_attempt_a=50., **changes))
                self.assertFalse(result["telemetry_ok"])
                self.assertEqual(result["next_a"], 0)

    def test_single_phase_does_not_bypass_current_ramp_or_ordinary_interval(self):
        start = calculate_grid_charge(single_snapshot())
        self.assertTrue(start["write"])
        self.assertEqual(start["next_a"], 20)
        held = calculate_grid_charge(single_snapshot(current_a=20., last_attempt_a=20.,
            last_attempt_ts=999., ordinary_last_possible_ts=999., target_soc=95.))
        self.assertFalse(held["write"])
        self.assertEqual(held["reason"], "ramp_wait")

    def test_single_phase_pv_contribution_still_reduces_grid_demand(self):
        grid = calculate_grid_charge(single_snapshot())
        solar = calculate_grid_charge(single_snapshot(battery_power_w=-5000.,
            grid_w=-1000., grid_phases_w=[-1000., 0., 0.],
            grid_port_w=-1000., grid_port_phases_w=[-1000., 0., 0.]))
        self.assertGreater(grid["need_a"], solar["need_a"])
        self.assertEqual(solar["next_a"], 0)

    def test_explicit_three_phase_layout_preserves_legacy_decisions(self):
        for balanced in (True, False):
            for load in (1000., 6000., 11000.):
                for current in (0., 20., 100.):
                    g = snapshot(load_w=load, load_phases_w=[load/3]*3,
                        grid_w=load, grid_phases_w=[load/3]*3,
                        grid_charge_balanced=balanced, current_a=current, last_attempt_a=current)
                    explicit = {**g, "inverter_phases": 3, "connection_phases": 3,
                                "inverter_phase_index": 0}
                    self.assertEqual(calculate_grid_charge(g), calculate_grid_charge(explicit))


if __name__ == "__main__":
    unittest.main()
