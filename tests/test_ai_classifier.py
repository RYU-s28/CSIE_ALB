import os
import sys
from types import ModuleType
import unittest
from unittest import mock

from attendance.ai_classifier import (
    CATEGORY_RESPONSE_SCHEMA,
    GEMINI_MODEL,
    IGNORE_MESSAGES,
    INTENT_RESPONSE_SCHEMA,
    classify_attendance_message,
    should_skip_ai,
)


def make_ai_modules(*responses: str):
    client = mock.Mock()
    client.interactions.create.side_effect = [
        mock.Mock(output_text=response) for response in responses
    ]
    genai_module = ModuleType("google.genai")
    genai_module.Client = mock.Mock(return_value=client)
    google_module = ModuleType("google")
    google_module.genai = genai_module
    return google_module, genai_module, client


def call_classifier(message: str, *responses: str):
    google_module, genai_module, client = make_ai_modules(*responses)
    with (
        mock.patch.dict(
            sys.modules,
            {
                "google": google_module,
                "google.genai": genai_module,
            },
        ),
        mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-api-key"}),
    ):
        analysis = classify_attendance_message(message)
    return analysis, genai_module, client


class AiAttendanceClassifierTests(unittest.TestCase):
    def test_known_greetings_are_ignored_without_an_ai_request(self) -> None:
        self.assertIn("hi", IGNORE_MESSAGES)
        for message in ("Hi!", "  GOOD morning everyone. ", "早安", "哈哈"):
            with self.subTest(message=message):
                self.assertTrue(should_skip_ai(message))
                result = classify_attendance_message(message)
                self.assertEqual(result.intent, "IGNORE")

    def test_messages_without_attendance_signals_are_ignored_locally(self) -> None:
        for message in ("Dili pwede?", "It's a lovely day", "Thanks everyone"):
            with self.subTest(message=message):
                with mock.patch.dict(os.environ, {}, clear=True):
                    result = classify_attendance_message(message)
                self.assertEqual(result.intent, "IGNORE")

    def test_confident_python_leave_category_skips_gemini(self) -> None:
        messages = (
            ("明天病假", "sick_leave"),
            ("我今天不能去上班，因為我不舒服", "sick_leave"),
            (
                "I can't work tomorrow because im not feeling well",
                "sick_leave",
            ),
        )
        for message, expected_status in messages:
            with self.subTest(message=message):
                with mock.patch.dict(os.environ, {}, clear=True):
                    result = classify_attendance_message(message)
                self.assertEqual(result.intent, "LEAVE")
                self.assertEqual(
                    result.to_classification_result().status,
                    expected_status,
                )

    def test_bus_notices_are_saved_as_attendance_without_gemini(self) -> None:
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
                with mock.patch.dict(os.environ, {}, clear=True):
                    analysis = classify_attendance_message(message)
                self.assertEqual(analysis.intent, "ATTENDANCE")
                self.assertEqual(analysis.category, "不坐公交車")
                self.assertEqual(
                    analysis.to_classification_result().status,
                    "no_bus",
                )

    def test_question_about_bus_notice_uses_intent_ai(self) -> None:
        analysis, _, client = call_classifier(
            "Are you not taking the bus today?",
            '{"intent":"IGNORE","reasoning":"The sender asks another person."}',
        )

        self.assertEqual(analysis.intent, "IGNORE")
        client.interactions.create.assert_called_once()
        request = client.interactions.create.call_args.kwargs
        self.assertEqual(
            request["response_format"]["schema"],
            INTENT_RESPONSE_SCHEMA,
        )

    def test_uncertain_bus_notice_uses_both_ai_stages(self) -> None:
        analysis, _, client = call_classifier(
            "The bus service is disrupted; I need another way to commute today.",
            (
                '{"intent":"ATTENDANCE",'
                '"reasoning":"The sender is reporting a transport issue, not absence."}'
            ),
            (
                '{"category":"不坐公交車",'
                '"reasoning":"The sender reports a bus transportation issue."}'
            ),
        )

        self.assertEqual(analysis.intent, "ATTENDANCE")
        self.assertEqual(analysis.category, "不坐公交車")
        self.assertEqual(analysis.to_classification_result().status, "no_bus")
        self.assertEqual(client.interactions.create.call_count, 2)
        intent_request, category_request = [
            call.kwargs for call in client.interactions.create.call_args_list
        ]
        self.assertEqual(
            intent_request["response_format"]["schema"],
            INTENT_RESPONSE_SCHEMA,
        )
        self.assertEqual(
            category_request["response_format"]["schema"],
            CATEGORY_RESPONSE_SCHEMA,
        )

    def test_chinese_leave_discussion_requires_ai_intent_confirmation(self) -> None:
        analysis, _, client = call_classifier(
            "請問你叫什麼名字，請假完成後再上傳截圖，謝謝",
            '{"intent":"IGNORE","reasoning":"This is an instruction to someone else."}',
        )

        self.assertEqual(analysis.intent, "IGNORE")
        client.interactions.create.assert_called_once()
        request = client.interactions.create.call_args.kwargs
        self.assertEqual(
            request["response_format"]["schema"],
            INTENT_RESPONSE_SCHEMA,
        )

    def test_category_keyword_in_question_does_not_skip_intent_ai(self) -> None:
        analysis, _, client = call_classifier(
            "你明天請病假嗎？",
            '{"intent":"IGNORE","reasoning":"The sender asks another person."}',
        )

        self.assertEqual(analysis.intent, "IGNORE")
        client.interactions.create.assert_called_once()

    def test_uncertain_intent_that_ai_ignores_uses_one_ai_call(self) -> None:
        analysis, _, client = call_classifier(
            "Who is taking leave tomorrow?",
            '{"intent":"IGNORE","reasoning":"This asks about another person."}',
        )

        self.assertEqual(analysis.intent, "IGNORE")
        client.interactions.create.assert_called_once()
        request = client.interactions.create.call_args.kwargs
        self.assertEqual(request["input"], "Who is taking leave tomorrow?")
        self.assertEqual(request["model"], GEMINI_MODEL)
        self.assertEqual(request["response_format"]["schema"], INTENT_RESPONSE_SCHEMA)

    def test_python_detects_leave_intent_and_ai_classifies_unknown_reason(self) -> None:
        analysis, _, client = call_classifier(
            "I won't work tomorrow due to a situation I haven't explained",
            '{"category":"待確認","reasoning":"Absence stated without a reason."}',
        )

        self.assertEqual(analysis.intent, "LEAVE")
        self.assertEqual(
            analysis.to_classification_result().status,
            "unknown",
        )
        client.interactions.create.assert_called_once()
        request = client.interactions.create.call_args.kwargs
        self.assertEqual(
            request["response_format"]["schema"],
            CATEGORY_RESPONSE_SCHEMA,
        )

    def test_uncertain_intent_then_leave_category_uses_two_staged_ai_calls(self) -> None:
        analysis, _, client = call_classifier(
            "I will be absent tomorrow for an unusual personal reason",
            '{"intent":"LEAVE","reasoning":"The sender says they will be away."}',
            '{"category":"事假","reasoning":"The message states a personal reason."}',
        )

        self.assertEqual(analysis.intent, "LEAVE")
        self.assertEqual(
            analysis.to_classification_result().status,
            "personal_leave",
        )
        self.assertEqual(client.interactions.create.call_count, 2)
        intent_request, category_request = [
            call.kwargs
            for call in client.interactions.create.call_args_list
        ]
        self.assertEqual(
            intent_request["response_format"]["schema"],
            INTENT_RESPONSE_SCHEMA,
        )
        self.assertEqual(
            category_request["response_format"]["schema"],
            CATEGORY_RESPONSE_SCHEMA,
        )

    def test_ai_review_does_not_request_a_category_or_save(self) -> None:
        analysis, _, client = call_classifier(
            "I have a fever",
            '{"intent":"REVIEW","reasoning":"Illness is mentioned without absence."}',
        )

        self.assertEqual(analysis.intent, "REVIEW")
        self.assertEqual(client.interactions.create.call_count, 1)
        with self.assertRaises(ValueError):
            analysis.to_classification_result()

    def test_rejects_malformed_intent_and_category_responses(self) -> None:
        cases = (
            (
                "I am not feeling well",
                ('{"intent":"UNKNOWN","reasoning":"?"}',),
            ),
            (
                "I won't work tomorrow for some reason",
                ('{"category":"unknown","reasoning":"?"}',),
            ),
            (
                "I won't work tomorrow because of the bus situation",
                ('{"category":"不坐公交車","reasoning":"?"}',),
            ),
        )
        for message, responses in cases:
            with self.subTest(message=message):
                google_module, genai_module, client = make_ai_modules(*responses)
                with (
                    mock.patch.dict(
                        sys.modules,
                        {
                            "google": google_module,
                            "google.genai": genai_module,
                        },
                    ),
                    mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-api-key"}),
                ):
                    with self.assertRaises(ValueError):
                        classify_attendance_message(message)
                self.assertGreaterEqual(
                    client.interactions.create.call_count,
                    1,
                )

    def test_missing_api_key_reports_configuration_error_for_uncertain_message(
        self,
    ) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                classify_attendance_message("Who is taking leave tomorrow?")


if __name__ == "__main__":
    unittest.main()
