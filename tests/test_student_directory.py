import unittest

from attendance.student_directory import (
    find_student_by_line_user_id,
    find_students_by_display_name,
    normalize_display_name,
)


class StudentDirectoryTests(unittest.TestCase):
    def test_display_name_normalization_keeps_meaningful_characters(self) -> None:
        self.assertEqual(
            normalize_display_name(" MICHAEL(潘伯森) "),
            normalize_display_name("michael(潘伯森)"),
        )
        self.assertEqual(
            normalize_display_name("  Romel   Jr. "),
            "romel jr.",
        )

    def test_display_name_lookup_is_exact_and_active_only(self) -> None:
        students = [
            {
                "student_id": "1",
                "name": "Michael Arbor",
                "display_name": "MICHAEL(潘伯森)",
                "active": "TRUE",
            },
            {
                "student_id": "2",
                "name": "Inactive Student",
                "display_name": "michael(潘伯森)",
                "active": "FALSE",
            },
            {
                "student_id": "3",
                "name": "Similar Name",
                "display_name": "Michael(潘伯森) Jr.",
                "active": "TRUE",
            },
        ]

        matches = find_students_by_display_name(students, " michael(潘伯森) ")

        self.assertEqual([student["student_id"] for student in matches], ["1"])

    def test_duplicate_active_display_names_remain_ambiguous(self) -> None:
        students = [
            {"student_id": "1", "display_name": "Same", "active": True},
            {"student_id": "2", "display_name": " same ", "active": True},
        ]

        self.assertEqual(len(find_students_by_display_name(students, "SAME")), 2)

    def test_line_user_id_lookup_trims_incoming_id(self) -> None:
        students = [
            {
                "student_id": "24113328",
                "name": "杜榮瑪",
                "line_user_id": "U123",
                "active": True,
            }
        ]

        self.assertEqual(
            find_student_by_line_user_id(students, " U123 "),
            {"student_id": "24113328", "name": "杜榮瑪"},
        )


if __name__ == "__main__":
    unittest.main()
