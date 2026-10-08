import unittest

from attendance.classifier import (
    ClassificationResult,
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

    def test_tracker_saves_the_classification_supplied_by_ai_fallback(self) -> None:
        ai_result = ClassificationResult(
            status="special_leave",
            confidence=0.8,
            attendance_intent=True,
        )
        record = AttendanceTracker().add_from_message(
            "student-1",
            "I will be out for annual leave",
            classification_result=ai_result,
        )

        self.assertEqual(record.status, "special_leave")
        self.assertEqual(record.confidence, 0.8)
        self.assertTrue(record.attendance_intent)

    def test_explicit_chinese_leave_status_is_actionable(self) -> None:
        result = classify_status("明天病假")

        self.assertEqual(result.status, "sick_leave")
        self.assertGreaterEqual(result.confidence, 0.60)

    def test_partial_day_takes_priority_over_stated_leave_reason(self) -> None:
        result = classify_status(
            "I'm having period cramps. I won't work this afternoon."
        )

        self.assertEqual(result.status, "half_day")
        self.assertTrue(result.attendance_intent)

    def test_half_day_phrase_is_classified_by_python_rules(self) -> None:
        for message in (
            "I need the morning off",
            "I will take a half day off",
            "下午請假",
        ):
            with self.subTest(message=message):
                self.assertEqual(classify_status(message).status, "half_day")

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

    def test_bus_transport_notices_are_classified_as_non_absence(self) -> None:
        messages = (
            "您好，不好意思，我今天沒辦法搭車回學校",
            (
                "I did not catch up the bus. I will be taking uber now to work. "
                "Thank you for understanding."
            ),
            "I won't be taking the bus today because...",
        )
        for message in messages:
            with self.subTest(message=message):
                result = classify_status(message)
                self.assertEqual(result.status, "no_bus")
                self.assertGreaterEqual(result.confidence, 0.60)
                self.assertTrue(result.attendance_intent)

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
