"""Gemini fallback for messages the rule-based classifier cannot resolve."""

from __future__ import annotations

import json
import os

from .classifier import ClassificationResult, classify_status


CATEGORY_TO_STATUS = {
    "出席": "present",
    "病假": "sick_leave",
    "事假": "personal_leave",
    "經痛": "menstrual_leave",
    "特休": "special_leave",
    "半天": "half_day",
    "待確認": "unknown",
    "無關": "unrelated",
}
AI_CLASSIFICATION_CONFIDENCE = 0.8
GEMINI_MODEL = "gemini-2.5-flash"

CLASSIFICATION_PROMPT = """Classify employee attendance messages into exactly one category.

Categories:
出席 = Present
病假 = Sick leave
事假 = Personal or family matters
經痛 = Menstrual pain or period-related absence
特休 = Explicit annual/special leave
半天 = Any half-day or partial-day absence, regardless of reason
待確認 = Absence stated but category unclear
無關 = Not an attendance message

Priority rules:
1. If the employee will miss only part of the workday, return 半天 regardless of the reason.
2. Otherwise classify by the explicitly stated leave reason.
3. Do not invent reasons.
4. If absent but the reason is unclear, return 待確認.
5. If unrelated to attendance, return 無關.

Return JSON only:
{"category": "CATEGORY"}

Message: {message}"""


def classify_attendance_message(message: str) -> ClassificationResult:
    """Prefer a confident Python result and use Gemini for unknown messages."""

    result = classify_status(message)
    if result.status != "unknown":
        return result
    return classify_with_ai(message)


def classify_with_ai(message: str) -> ClassificationResult:
    """Classify a rule-based unknown using the configured Gemini API key."""

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is required when the rule-based classifier "
            "cannot classify a message."
        )

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=CLASSIFICATION_PROMPT.replace("{message}", message),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    response_text = response.text
    if not response_text:
        raise ValueError("Gemini returned an empty attendance classification.")
    return parse_ai_category(response_text)


def parse_ai_category(response_text: str) -> ClassificationResult:
    """Parse and validate Gemini's required JSON category response."""

    try:
        response_data = json.loads(response_text)
    except json.JSONDecodeError as error:
        raise ValueError(
            "Gemini returned invalid JSON for attendance classification."
        ) from error

    if (
        not isinstance(response_data, dict)
        or set(response_data) != {"category"}
        or not isinstance(response_data["category"], str)
        or response_data["category"] not in CATEGORY_TO_STATUS
    ):
        raise ValueError(
            "Gemini returned an invalid attendance category; expected exactly "
            "one of: " + ", ".join(CATEGORY_TO_STATUS)
        )

    category = response_data["category"]
    status = CATEGORY_TO_STATUS[category]
    return ClassificationResult(
        status=status,
        confidence=AI_CLASSIFICATION_CONFIDENCE,
        attendance_intent=status != "unrelated",
    )
