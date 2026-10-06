import unittest
from datetime import date
from unittest import mock

from scheduler import daily_report


class DailyReportTests(unittest.TestCase):
    def test_daily_report_uses_persisted_records_and_active_roster(self) -> None:
        with (
            mock.patch.object(
                daily_report,
                "get_report_students",
                return_value=(
                    {"S1": mock.Mock(line_label="杜榮瑪")},
                    1,
                ),
            ),
            mock.patch.object(
                daily_report,
                "get_attendance_rows",
                return_value=[
                    {
                        "student_id": "S1",
                        "type": "病假",
                        "raw_message": "sick",
                    }
                ],
            ),
        ):
            report = daily_report.generate_daily_report(date(2026, 10, 10))

        self.assertEqual(
            report,
            "「2026/10/10」（禮拜六）\n\n"
            "應到人數：1\n"
            "實到人數：0\n\n"
            "病假：1人\n"
            "@杜榮瑪",
        )

    def test_daily_job_skips_push_without_destination_configuration(self) -> None:
        with (
            mock.patch.object(daily_report, "is_workday", return_value=True),
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(daily_report, "generate_daily_report") as generate,
        ):
            daily_report.daily_attendance_job()

        generate.assert_not_called()

    def test_pending_absence_intent_is_not_reported_as_present(self) -> None:
        with (
            mock.patch.object(
                daily_report,
                "get_report_students",
                return_value=({"S1": mock.Mock(line_label="杜榮瑪")}, 1),
            ),
            mock.patch.object(
                daily_report,
                "get_attendance_rows",
                return_value=[
                    {
                        "student_id": "S1",
                        "type": "待確認",
                        "status": "Pending",
                        "attendance_intent": "TRUE",
                        "raw_message": "I will not be working today because of a migraine",
                    }
                ],
            ),
        ):
            report = daily_report.generate_daily_report(date(2026, 10, 10))

        self.assertIn("實到人數：0", report)
        self.assertIn("待確認：1人", report)


if __name__ == "__main__":
    unittest.main()
