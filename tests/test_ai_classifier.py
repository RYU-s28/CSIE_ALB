import os
import sys
from types import ModuleType
import unittest
from unittest import mock

from attendance.ai_classifier import (
    CATEGORY_TO_STATUS,
    CLASSIFICATION_PROMPT,
    classify_attendance_message,
    classify_with_ai,
    parse_ai_category,
)


class AiAttendanceClassifierTests(unittest.TestCase):
    def test_maps_each_prompt_category_to_an_internal_status(self) -> None:
        expected = {
            "出席": "present",
            "病假": "sick_leave",
            "事假": "personal_leave",
            "經痛": "menstrual_leave",
            "特休": "special_leave",
            "半天": "half_day",
            "待確認": "unknown",
            "無關": "unrelated",
        }

        self.assertEqual(CATEGORY_TO_STATUS, expected)
        for category, status in expected.items():
            with self.subTest(category=category):
                result = parse_ai_category(f'{{"category": "{category}"}}')
                self.assertEqual(result.status, status)
                self.assertEqual(result.attendance_intent, status != "unrelated")

    def test_rejects_invalid_or_non_json_ai_responses(self) -> None:
        for response in (
            "not json",
            '{"category": "無關", "reason": "not requested"}',
            '{"category": "unknown"}',
            '{"category": []}',
        ):
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    parse_ai_category(response)

    def test_calls_ai_only_when_rule_classifier_returns_unknown(self) -> None:
        known_result = mock.Mock(status="sick_leave")
        fallback_result = mock.Mock(status="personal_leave")

        with (
            mock.patch(
                "attendance.ai_classifier.classify_status",
                return_value=known_result,
            ),
            mock.patch(
                "attendance.ai_classifier.classify_with_ai",
                return_value=fallback_result,
            ) as classify_with_ai,
        ):
            self.assertIs(
                classify_attendance_message("病假"),
                known_result,
            )
        classify_with_ai.assert_not_called()

        with (
            mock.patch(
                "attendance.ai_classifier.classify_status",
                return_value=mock.Mock(status="unknown"),
            ),
            mock.patch(
                "attendance.ai_classifier.classify_with_ai",
                return_value=fallback_result,
            ) as classify_with_ai,
        ):
            self.assertIs(
                classify_attendance_message("I'm not coming in"),
                fallback_result,
            )
        classify_with_ai.assert_called_once_with("I'm not coming in")

    def test_sends_prompt_to_gemini_and_parses_its_response(self) -> None:
        client = mock.Mock()
        client.models.generate_content.return_value.text = '{"category": "特休"}'
        genai_module = ModuleType("google.genai")
        genai_module.Client = mock.Mock(return_value=client)
        types_module = ModuleType("google.genai.types")
        types_module.GenerateContentConfig = mock.Mock(return_value="json-config")
        google_module = ModuleType("google")
        google_module.genai = genai_module
        genai_module.types = types_module

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
            result = classify_with_ai("Need to take a special leave tomorrow")

        self.assertEqual(result.status, "special_leave")
        genai_module.Client.assert_called_once_with(api_key="test-api-key")
        request = client.models.generate_content.call_args.kwargs
        self.assertEqual(request["model"], "gemini-2.5-flash")
        self.assertIn(
            "Message: Need to take a special leave tomorrow",
            request["contents"],
        )
        self.assertEqual(request["config"], "json-config")
        types_module.GenerateContentConfig.assert_called_once_with(
            response_mime_type="application/json"
        )
        self.assertIn('{"category": "CATEGORY"}', CLASSIFICATION_PROMPT)


if __name__ == "__main__":
    unittest.main()
