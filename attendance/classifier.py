"""Rule-based attendance/leave classifier."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    status: str
    confidence: float
    matched_keyword: str | None = None


KEYWORDS: dict[str, tuple[str, ...]] = {
    "sick_leave": (
        "病假",
        "不舒服",
        "不太舒服",
        "身體不舒服",
        "生病",
        "發燒",
        "發熱",
        "感冒",
        "頭痛",
        "肚子痛",
        "喉嚨痛",
        "看醫生",
        "去醫院",
        "doctor",
        "hospital",
        "sick",
        "fever",
        "not feeling well",
        "feeling unwell",
    ),
    "personal_leave": (
        "事假",
        "已請假",
        "已經請假",
        "提前請假",
        "先請假",
        "有事",
        "家裡有事",
        "personal leave",
        "advance leave",
        "already took leave",
        "already requested leave",
    ),
    "menstrual_leave": (
        "經痛",
        "生理假",
        "生理期",
        "月經",
        "menstrual leave",
        "period pain",
    ),
    "abroad": (
        "回國",
        "回菲律賓",
        "在國外",
        "出國",
        "abroad",
        "back home",
        "returning home",
    ),
    "late": (
        "遲到",
        "迟到",
        "late",
        "arrived late",
    ),
}


def classify_status(message: str) -> ClassificationResult:
    """Classify a student's LINE message using simple keyword rules.

    This intentionally returns ``unknown`` when no clear rule matches.
    More advanced date/context analysis can be layered on top later.
    """

    text = normalize_text(message)

    if not text:
        return ClassificationResult(
            status="unknown",
            confidence=0.0,
        )

    # Check the more specific leave categories before general ones.
    priority = (
        "menstrual_leave",
        "sick_leave",
        "personal_leave",
        "abroad",
        "late",
    )

    for status in priority:
        for keyword in KEYWORDS[status]:
            if normalize_text(keyword) in text:
                return ClassificationResult(
                    status=status,
                    confidence=0.95,
                    matched_keyword=keyword,
                )

    return ClassificationResult(
        status="unknown",
        confidence=0.0,
    )


def normalize_text(text: str) -> str:
    """Normalize input for keyword matching."""

    return " ".join(text.lower().strip().split())