import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from test_solcast import module
forecast_summary = module.forecast_summary

class ForecastDisplay(unittest.TestCase):
    def rows(self, start, count):
        return [{"period_start": (start+timedelta(minutes=30*i)).isoformat(), "pv_estimate": 2., "pv_estimate10": 1.} for i in range(count)]
    def test_energy_and_partial_current_period(self):
        start=datetime(2026,11,15,tzinfo=ZoneInfo("Europe/Warsaw")).astimezone(timezone.utc)
        result=forecast_summary(self.rows(start,96), start+timedelta(hours=12,minutes=15))
        self.assertEqual(result["today"]["p50_kwh"],23.5)
        self.assertEqual(result["remaining_today"]["p50_kwh"],23.5)
        self.assertEqual(result["tomorrow"]["p10_kwh"],24)
    def test_missing_period_is_unknown_not_zero(self):
        start=datetime(2026,11,15,tzinfo=timezone.utc)
        result=forecast_summary([],start)
        self.assertIsNone(result["today"]["p50_kwh"])
        self.assertFalse(result["remaining_today"]["complete"])
    def test_dst_local_days_have_23_or_25_hours(self):
        for month,day,hours in [(3,29,23),(10,25,25)]:
            start=datetime(2026,month,day,tzinfo=ZoneInfo("Europe/Warsaw")).astimezone(timezone.utc)
            result=forecast_summary(self.rows(start,100),start)
            self.assertEqual(result["today"]["p50_kwh"],hours*2)
