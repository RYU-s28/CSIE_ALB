import os
import sys
from types import ModuleType
import unittest
from unittest import mock

from attendance.ai_classifier import (
    CATEGORY_TO_STATUS,
    GEMINI_MODEL,
    SYSTEM_PROMPT,
    classify_attendance_message,
    parse_ai_response,
)


def make_ai_modules(response_text: str):
    client = mock.Mock()
    client.models.generate_content.return_value.text = response_text
    genai_module = ModuleType("google.genai")
    genai_module.Client = mock.Mock(return_value=client)
    types_module = ModuleType("google.genai.types")
    types_module.GenerateContentConfig = mock.Mock(return_value="json-config")
    google_module = ModuleType("google")
    google_module.genai = genai_module
    genai_module.types = types_module
    return google_module, genai_module, types_module, client


class AiAttendanceClassifierTests(unittest.TestCase):
    def test_parses_each_intent_and_leave_category(self) -> None:
        for category, expected_status in CATEGORY_TO_STATUS.items():
            with self.subTest(category=category):
                result = parse_ai_response(
                    f'{{"intent":"LEAVE","category":"{category}",'
                    '"reasoning":"Explicit leave notice."}'
                )
                self.assertEqual(result.intent, "LEAVE")
                self.assertEqual(result.category, category)
                self.assertEqual(
                    result.to_classification_result().status,
                    expected_status,
                )

        review = parse_ai_response(
            '{"intent":"REVIEW","category":"病假",'
            '"reasoning":"Illness mentioned, absence unclear."}'
        )
        self.assertEqual(review.intent, "REVIEW")
        with self.assertRaises(ValueError):
            review.to_classification_result()

        ignored = parse_ai_response(
            '{"intent":"IGNORE","category":null,'
            '"reasoning":"Greeting only."}'
        )
        self.assertEqual(ignored.intent, "IGNORE")
        self.assertIsNone(ignored.category)

    def test_rejects_invalid_json_or_response_shapes(self) -> None:
        responses = (
            "not json",
            '{"intent":"LEAVE","category":"待確認"}',
            '{"intent":"MAYBE","category":null,"reasoning":"?"}',
            '{"intent":"IGNORE","category":"病假","reasoning":"?"}',
            '{"intent":"LEAVE","category":"無關","reasoning":"?"}',
            '{"intent":"REVIEW","category":null,"reasoning":"?"}',
            '{"intent":[],"category":null,"reasoning":"?"}',
            '{"intent":"IGNORE","category":null,"reasoning":" "}',
            '{"intent":"IGNORE","category":null,"reasoning":"?","extra":1}',
        )
        for response in responses:
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    parse_ai_response(response)

    def test_sends_raw_message_to_gemini_with_system_instructions(self) -> None:
        user_message = "Good morning everyone!"
        google_module, genai_module, types_module, client = make_ai_modules(
            '{"intent":"IGNORE","category":null,"reasoning":"Greeting only."}'
        )

        with (
            mock.patch.dict(
                sys.modules,
                {
                    "google": google_module,
                    "google.genai": genai_module,
                    "google.genai.types": types_module,
                },
            ),
            mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-api-key"}),
        ):
            result = classify_attendance_message(user_message)

        self.assertEqual(result.intent, "IGNORE")
        genai_module.Client.assert_called_once_with(api_key="test-api-key")
        request = client.models.generate_content.call_args.kwargs
        self.assertEqual(request["model"], GEMINI_MODEL)
        self.assertEqual(request["contents"], user_message)
        self.assertEqual(
            request["config"],
            "json-config",
        )
        types_module.GenerateContentConfig.assert_called_once_with(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        )

    def test_missing_api_key_reports_configuration_error(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                classify_attendance_message("Good morning")


if __name__ == "__main__":
    unittest.main()
