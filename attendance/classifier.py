"""Rule-based attendance/leave classifier."""

from __future__ import annotations

from dataclasses import dataclass
import re


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
        "body ache",
        "body pain",
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
        "period cramps",
        "period discomfort",
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
    "no_bus": (
        "不坐公交車",
        "不坐公車",
        "not taking the bus",
        "no bus",
    ),
    "not_coming": (
        "不出來",
        "不來上班",
        "不来上班",
        "not coming to work",
    ),
    "cancelled_work": (
        "取消工讀",
        "取消打工",
        "cancel work",
        "cancelled work",
    ),
    "late": (
        "遲到",
        "迟到",
        "late",
        "arrived late",
    ),
}

MIN_ATTENDANCE_CONFIDENCE = 0.60

LEAVE_INTENT_PATTERNS = (
    r"\b(?:take|taking|request|requesting|apply for|applied for)\s+"
    r"(?:a\s+)?(?:sick|personal|menstrual|medical)?\s*leave\b",
    r"\b(?:will|going to)\s+(?:be\s+)?(?:taking|take|request|requesting)\s+"
    r"(?:a\s+)?(?:sick|personal|menstrual|medical)?\s*leave\b",
    r"\b(?:will not work|won't work|can't work|cannot work|unable to work)\b",
    r"\b(?:will not be working|won't be working|can't come|cannot come|"
    r"will not come|won't come|not coming)\b",
    r"\b(?:take|taking|requesting)\s+(?:a\s+)?leave\b",
    r"\b(?:i am|i'm|was|will be|arrived)\s+late\b",
)
CHINESE_LEAVE_INTENT_PHRASES = (
    "請病假",
    "请病假",
    "請事假",
    "请事假",
    "請假",
    "请假",
    "休假",
    "不上班",
    "不來上班",
    "不来上班",
    "不會上班",
    "不会上班",
    "無法上班",
    "无法上班",
    "今天不來",
    "今天不来",
    "明天不來",
    "明天不来",
)
NEGATED_LEAVE_PATTERNS = (
    r"\b(?:not|don't|do not|doesn't|does not|won't|will not|never)\s+"
    r"(?:be\s+)?(?:taking|take|requesting|request|need|apply for)\s+"
    r"(?:a\s+)?(?:sick|personal|menstrual|medical)?\s*leave\b",
    r"\bno\s+(?:sick|personal|menstrual|medical)?\s*leave\b",
)


def classify_status(message: str) -> ClassificationResult:
    """Classify clear leave/attendance intent; ignore casual keyword mentions."""

    text = normalize_text(message)

    if not text:
        return _unknown_result()

    if any(re.search(pattern, text) for pattern in NEGATED_LEAVE_PATTERNS):
        return _unknown_result()

    priority = (
        "menstrual_leave",
        "sick_leave",
        "personal_leave",
        "abroad",
        "no_bus",
        "not_coming",
        "cancelled_work",
        "late",
    )

    matched_status = None
    matched_keyword = None
    for status in priority:
        for keyword in KEYWORDS[status]:
            if normalize_text(keyword) in text:
                matched_status = status
                matched_keyword = keyword
                break
        if matched_status is not None:
            break

    explicit_status_phrase = matched_keyword in {
        "病假",
        "事假",
        "經痛",
        "生理假",
        "回國",
        "回菲律賓",
        "不坐公交車",
        "不坐公車",
        "不出來",
        "取消工讀",
        "取消打工",
        "遲到",
        "迟到",
    }
    has_leave_intent = (
        any(re.search(pattern, text) for pattern in LEAVE_INTENT_PATTERNS)
        or any(phrase in text for phrase in CHINESE_LEAVE_INTENT_PHRASES)
        or explicit_status_phrase
    )
    checklist_score = 0.0
    if has_leave_intent:
        checklist_score += 0.65
    if matched_keyword is not None:
        checklist_score += 0.25
    if explicit_status_phrase:
        checklist_score = max(checklist_score, 0.70)
    confidence = min(checklist_score, 0.95)
    if confidence < MIN_ATTENDANCE_CONFIDENCE:
        return _unknown_result()

    if matched_status is None:
        matched_status = "personal_leave"
        matched_keyword = next(
            (
                phrase
                for phrase in CHINESE_LEAVE_INTENT_PHRASES
                if phrase in text
            ),
            "work absence",
        )

    return ClassificationResult(
        status=matched_status,
        confidence=confidence,
        matched_keyword=matched_keyword,
    )


def _unknown_result() -> ClassificationResult:
    return ClassificationResult(status="unknown", confidence=0.0)


def normalize_text(text: str) -> str:
    """Normalize input for keyword matching."""

    return " ".join(text.lower().strip().split())