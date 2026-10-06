"""Student roster lookup helpers."""

from __future__ import annotations


ACTIVE_VALUES = {"true", "1", "yes"}


def normalize_display_name(name: object) -> str:
    """Normalize spacing and Latin casing without removing meaningful text."""

    return " ".join(str(name).split()).casefold()


def _is_active(student: dict[str, object]) -> bool:
    value = student.get("active")
    if value is None:
        return True
    return str(value).strip().lower() in ACTIVE_VALUES


def find_student_by_line_user_id(
    students: list[dict[str, object]],
    line_user_id: str,
) -> dict[str, str] | None:
    """Return the active roster entry matching a LINE user ID."""

    normalized_user_id = str(line_user_id).strip()
    for student in students:
        if str(student.get("line_user_id", "")).strip() != normalized_user_id:
            continue

        if not _is_active(student):
            return None

        return {
            "student_id": str(student.get("student_id", "")).strip(),
            "name": str(student.get("name", "")).strip(),
        }

    return None


def find_students_by_display_name(
    students: list[dict[str, object]],
    display_name: object,
) -> list[dict[str, object]]:
    """Return all active exact matches for an initial LINE display name."""

    normalized_name = normalize_display_name(display_name)
    if not normalized_name:
        return []

    return [
        student
        for student in students
        if normalize_display_name(student.get("display_name", "")) == normalized_name
        and _is_active(student)
    ]


def find_student_by_name(
    students: list[dict[str, object]],
    display_name: str,
) -> dict[str, str] | None:
    """Return a unique active roster entry matching a display name."""

    matches = find_students_by_display_name(
        [
            {
                **student,
                "display_name": student.get("display_name", student.get("name", "")),
            }
            for student in students
        ],
        display_name,
    )
    if len(matches) != 1:
        return None

    student = matches[0]
    return {
        "student_id": str(student.get("student_id", "")).strip(),
        "name": str(student.get("name", "")).strip(),
    }