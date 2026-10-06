import unittest
from datetime import date

from attendance.attendance import AttendanceRecord
from attendance.report import StudentDisplay, build_report


class AttendanceReportTests(unittest.TestCase):
    def test_report_uses_roster_names_and_omits_empty_statuses(self) -> None:
        report = build_report(
            report_date=date(2026, 10, 6),
            total_students=41,
            expected_students=41,
            records=[
                AttendanceRecord(
                    student_id="1",
                    status="abroad",
                    attendance_date=date(2026, 10, 6),
                ),
                AttendanceRecord(
                    student_id="2",
                    status="late",
                    attendance_date=date(2026, 10, 6),
                ),
                AttendanceRecord(
                    student_id="3",
                    status="personal_leave",
                    attendance_date=date(2026, 10, 6),
                ),
            ],
            students={
                "1": StudentDisplay("1", "華凌智"),
                "2": StudentDisplay("2", "倪瑪芮 HEART"),
                "3": StudentDisplay("3", "言伊曼"),
            },
        )

        self.assertEqual(
            report,
            "「2026/10/06」（禮拜二）\n\n"
            "應到人數：41\n"
            "實到人數：39\n\n"
            "回菲律賓：1人\n"
            "@華凌智\n\n"
            "事假：1人\n"
            "@言伊曼\n\n"
            "遲到：1人\n"
            "@倪瑪芮 HEART",
        )
        self.assertNotIn("病假", report)
        self.assertNotIn("經痛", report)
        self.assertNotIn("待確認", report)

    def test_report_counts_only_leave_statuses_as_absent(self) -> None:
        report = build_report(
            report_date=date(2026, 10, 6),
            total_students=2,
            records=[
                AttendanceRecord(
                    student_id="1",
                    status="unknown",
                    attendance_date=date(2026, 10, 6),
                )
            ],
        )

        self.assertIn("實到人數：2", report)
        self.assertIn("待確認：1人", report)


if __name__ == "__main__":
    unittest.main()
