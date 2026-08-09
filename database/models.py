"""Database model definitions."""

from dataclasses import dataclass


@dataclass
class AttendanceEntry:
    student_id: str
    status: str
