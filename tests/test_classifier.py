import unittest

from attendance.classifier import (
    MIN_ATTENDANCE_CONFIDENCE,
    classify_status,
)


class AttendanceClassifierTests(unittest.TestCase):
    def test_explicit_english_leave_intents_are_actionable(self) -> None:
        cases = {
            "I will be taking a sick leave today": "sick_leave",
            "I will take a leave tomorrow": "personal_leave",
            "I will not work today": "personal_leave",
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

    def test_explicit_chinese_leave_status_is_actionable(self) -> None:
        result = classify_status("明天病假")

        self.assertEqual(result.status, "sick_leave")
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
