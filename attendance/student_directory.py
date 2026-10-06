"""Student roster lookup helpers."""

from __future__ import annotations


INACTIVE_VALUES = {"false", "0", "no", "inactive"}


def find_student_by_line_user_id(
    students: list[dict[str, object]],
    line_user_id: str,
) -> dict[str, str] | None:
    """Return the active roster entry matching a LINE user ID."""

    for student in students:
        if str(student.get("line_user_id", "")).strip() != line_user_id:
            continue

        active = str(student.get("active", "true")).strip().lower()
        if active in INACTIVE_VALUES:
            return None

        return {
            "student_id": str(student.get("student_id", "")).strip(),
            "name": str(student.get("name", "")).strip(),
        }

    return None


def find_student_by_name(
    students: list[dict[str, object]],
    display_name: str,
) -> dict[str, str] | None:
    """Return a unique active roster entry matching a display name."""

    normalized_name = display_name.strip().casefold()
    if not normalized_name:
        return None

    matches = [
        student
        for student in students
        if str(student.get("name", "")).strip().casefold() == normalized_name
        and str(student.get("active", "true")).strip().lower()
        not in INACTIVE_VALUES
    ]
    if len(matches) != 1:
        return None

    student = matches[0]
    return {
        "student_id": str(student.get("student_id", "")).strip(),
        "name": str(student.get("name", "")).strip(),
    }