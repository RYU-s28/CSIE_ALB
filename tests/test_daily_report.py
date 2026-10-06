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


if __name__ == "__main__":
    unittest.main()
