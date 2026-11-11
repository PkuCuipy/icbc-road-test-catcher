import unittest
from datetime import date, timedelta
from unittest.mock import patch

import main


class PreferencesTest(unittest.TestCase):
    def test_searches_use_selected_class_and_skip_weekdays(self):
        saturday = {"appointmentDt": {"date": "2026-12-19"}}
        monday = {"appointmentDt": {"date": "2026-12-14"}}
        for exam_type in ("5-R-1", "7-R-1"):
            with self.subTest(exam_type=exam_type), patch.dict(main.CONFIG, {
                "appointment_request_base": {"examType": exam_type},
                "location_ids": [93],
                "desired_date_range": {"start": "2026-12-14", "end": "2027-02-01"},
                "desired_weekdays": {"5"},
                "excluded_dates": set(),
            }), patch.object(main, "current_token", "test-token"), patch.object(main, "datetime") as clock, patch.object(main.httpx, "Client") as client_factory:
                from datetime import datetime
                clock.strptime = datetime.strptime
                clock.now.return_value = datetime(2026, 12, 1)
                client = client_factory.return_value.__enter__.return_value
                client.post.return_value.json.return_value = [monday, saturday]
                self.assertEqual(main.get_earliest_appointment(), saturday)
                main.canary_check()
                self.assertEqual(client.post.call_count, 2)
                for call in client.post.call_args_list:
                    self.assertEqual(call.kwargs["json"]["examType"], exam_type)
                    self.assertEqual(call.kwargs["json"]["aPosID"], 93)

    def test_weekday_range_and_exclusions(self):
        with patch.dict(main.CONFIG, {"desired_weekdays": {"5"}, "excluded_dates": set()}):
            start = date(2026, 12, 14)
            matches = [start + timedelta(days=i) for i in range(50)
                       if main.is_desired_day(start + timedelta(days=i))]
            self.assertEqual([d.isoformat() for d in matches], [
                "2026-12-19", "2026-12-26", "2027-01-02", "2027-01-09",
                "2027-01-16", "2027-01-23", "2027-01-30"])
            main.CONFIG["excluded_dates"] = {"2026-12-19"}
            self.assertFalse(main.is_desired_day(date(2026, 12, 19)))
            main.CONFIG["desired_weekdays"] = set()
            self.assertTrue(main.is_desired_day(start))

    def test_invalid_class_rejected_before_login(self):
        with patch.dict(main.CONFIG, {"appointment_request_base": {"examType": "6-R-1"}}), patch.object(main, "refresh_token") as login:
            main.main()
            login.assert_not_called()


if __name__ == "__main__":
    unittest.main()
