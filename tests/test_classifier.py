import unittest

from attendance.classifier import (
    MIN_ATTENDANCE_CONFIDENCE,
    classify_status,
)
from attendance.attendance import AttendanceTracker


class AttendanceClassifierTests(unittest.TestCase):
    def test_explicit_english_leave_intents_are_actionable(self) -> None:
        cases = {
            "I will be taking a sick leave today": "sick_leave",
            "I will not be working today because of back pain": "sick_leave",
            "I will not be working today because of backache": "sick_leave",
            "I will not be working today because of lower back pain": "sick_leave",
            "今天因為背痛不上班": "sick_leave",
            "明天腰痛請假": "sick_leave",
            "I will not be working today because I'm not feeling well": "sick_leave",
        }
        for message, expected_status in cases.items():
            with self.subTest(message=message):
                result = classify_status(message)
                self.assertEqual(result.status, expected_status)
                self.assertGreaterEqual(
                    result.confidence,
                    MIN_ATTENDANCE_CONFIDENCE,
                )

    def test_unclear_absence_is_unknown_with_attendance_intent(self) -> None:
        for message in (
            "I will take a leave tomorrow",
            "I will not work today",
            "I will not be working today because of a migraine",
        ):
            with self.subTest(message=message):
                result = classify_status(message)
                self.assertEqual(result.status, "unknown")
                self.assertTrue(result.attendance_intent)

    def test_tracker_preserves_unclear_absence_intent(self) -> None:
        record = AttendanceTracker().add_from_message(
            "student-1",
            "I will not be working today because of a migraine",
        )

        self.assertEqual(record.status, "unknown")
        self.assertTrue(record.attendance_intent)

    def test_explicit_chinese_leave_status_is_actionable(self) -> None:
        result = classify_status("明天病假")

        self.assertEqual(result.status, "sick_leave")
        self.assertGreaterEqual(result.confidence, 0.60)

    def test_explicit_roster_attendance_categories_are_actionable(self) -> None:
        cases = {
            "不坐公交車": "no_bus",
            "今天不出來": "not_coming",
            "取消工讀": "cancelled_work",
        }
        for message, expected_status in cases.items():
            with self.subTest(message=message):
                result = classify_status(message)
                self.assertEqual(result.status, expected_status)
                self.assertGreaterEqual(result.confidence, 0.60)

    def test_casual_keyword_mentions_do_not_create_attendance(self) -> None:
        for message in (
            "Good morning everyone",
            "I am sick of this homework",
            "I am not feeling well",
            "We discussed personal leave policy",
        ):
            with self.subTest(message=message):
                result = classify_status(message)
                self.assertEqual(result.status, "unknown")
                self.assertLess(result.confidence, 0.60)
                self.assertFalse(result.attendance_intent)

    def test_explicitly_cancelled_leave_is_not_actionable(self) -> None:
        for message in (
            "I will not take sick leave today",
            "I don't need personal leave tomorrow",
            "No sick leave for me",
        ):
            with self.subTest(message=message):
                result = classify_status(message)
                self.assertEqual(result.status, "unknown")
                self.assertLess(result.confidence, 0.60)


if __name__ == "__main__":
    unittest.main()
