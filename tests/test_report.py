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
                    status="no_bus",
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
            "不坐公交車：1人\n"
            "@倪瑪芮 HEART\n\n"
            "事假：1人\n"
            "@言伊曼",
        )
        self.assertNotIn("病假", report)
        self.assertNotIn("經痛", report)
        self.assertNotIn("待確認", report)

    def test_report_absent_count_excludes_no_bus_and_uses_expected_count(self) -> None:
        report = build_report(
            report_date=date(2026, 10, 6),
            total_students=99,
            expected_students=41,
            records=[
                AttendanceRecord(
                    student_id="1",
                    status="sick_leave",
                    attendance_date=date(2026, 10, 6),
                ),
                AttendanceRecord(
                    student_id="2",
                    status="not_coming",
                    attendance_date=date(2026, 10, 6),
                ),
                AttendanceRecord(
                    student_id="3",
                    status="cancelled_work",
                    attendance_date=date(2026, 10, 6),
                ),
                AttendanceRecord(
                    student_id="4",
                    status="no_bus",
                    attendance_date=date(2026, 10, 6),
                ),
            ],
        )

        self.assertIn("應到人數：41\n實到人數：38", report)
        self.assertIn("不出來：1人\n@2", report)
        self.assertIn("取消工讀：1人\n@3", report)

    def test_report_omits_students_with_no_exception_status(self) -> None:
        report = build_report(
            report_date=date(2026, 10, 6),
            total_students=2,
            expected_students=2,
            records=[
                AttendanceRecord(
                    student_id="1",
                    status="unknown",
                    attendance_date=date(2026, 10, 6),
                )
            ],
        )

        self.assertNotIn("出席", report)
        self.assertIn("待確認：1人\n@1", report)
        self.assertIn("實到人數：2", report)

    def test_pending_absence_intent_is_excluded_from_present_count(self) -> None:
        report = build_report(
            report_date=date(2026, 10, 6),
            total_students=3,
            expected_students=3,
            records=[
                AttendanceRecord(
                    student_id="1",
                    status="unknown",
                    attendance_date=date(2026, 10, 6),
                    attendance_intent=True,
                ),
                AttendanceRecord(
                    student_id="2",
                    status="unknown",
                    attendance_date=date(2026, 10, 6),
                ),
            ],
        )

        self.assertIn("實到人數：2", report)
        self.assertIn("待確認：2人", report)


if __name__ == "__main__":
    unittest.main()
