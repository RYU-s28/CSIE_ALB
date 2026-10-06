"""Attendance tracking abstractions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Iterable

from .classifier import ClassificationResult, classify_status


VALID_STATUSES = {
    "present",
    "late",
    "sick_leave",
    "personal_leave",
    "menstrual_leave",
    "abroad",
    "no_bus",
    "not_coming",
    "cancelled_work",
    "unknown",
}


@dataclass(slots=True)
class AttendanceRecord:
    """Represents one student's attendance state for a specific date."""

    student_id: str
    status: str
    message: str = ""
    attendance_date: date = field(default_factory=date.today)
    created_at: datetime = field(default_factory=datetime.now)
    confidence: float = 1.0
    matched_keyword: str | None = None
    is_manual_override: bool = False

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"Invalid attendance status: {self.status}")

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")


class AttendanceTracker:
    """Stores and manages attendance records.

    This is an in-memory implementation for development/testing.
    Replace the internal dictionary with a database repository later.
    """

    def __init__(
        self,
        record_writer: Callable[[AttendanceRecord], None] | None = None,
    ) -> None:
        self.records: dict[tuple[str, date], AttendanceRecord] = {}
        self.record_writer = record_writer

    def add_from_message(
        self,
        student_id: str,
        message: str,
        *,
        attendance_date: date | None = None,
    ) -> AttendanceRecord:
        """Classify a LINE message and save the resulting attendance status."""

        result: ClassificationResult = classify_status(message)

        record = AttendanceRecord(
            student_id=student_id,
            status=result.status,
            message=message,
            attendance_date=attendance_date or date.today(),
            confidence=result.confidence,
            matched_keyword=result.matched_keyword,
        )

        self._save(record)
        return record

    def set_status(
        self,
        student_id: str,
        status: str,
        *,
        attendance_date: date | None = None,
        message: str = "",
    ) -> AttendanceRecord:
        """Manually set or override a student's attendance status."""

        record = AttendanceRecord(
            student_id=student_id,
            status=status,
            message=message,
            attendance_date=attendance_date or date.today(),
            confidence=1.0,
            is_manual_override=True,
        )

        self._save(record)
        return record

    def _save(self, record: AttendanceRecord) -> None:
        key = (record.student_id, record.attendance_date)
        existing = self.records.get(key)

        # Do not overwrite a human correction with an automatic classification.
        if (
            existing
            and existing.is_manual_override
            and not record.is_manual_override
        ):
            return

        self.records[key] = record
        if self.record_writer is not None:
            self.record_writer(record)

    def get_record(
        self,
        student_id: str,
        *,
        attendance_date: date | None = None,
    ) -> AttendanceRecord | None:
        """Return one student's attendance record for a date."""

        key = (student_id, attendance_date or date.today())
        return self.records.get(key)

    def get_records_for_date(
        self,
        attendance_date: date | None = None,
    ) -> list[AttendanceRecord]:
        """Return all attendance records for one date."""

        target_date = attendance_date or date.today()
        return [
            record
            for record in self.records.values()
            if record.attendance_date == target_date
        ]

    def get_by_status(
        self,
        status: str,
        *,
        attendance_date: date | None = None,
    ) -> list[AttendanceRecord]:
        """Return all records matching a status for one date."""

        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid attendance status: {status}")

        return [
            record
            for record in self.get_records_for_date(attendance_date)
            if record.status == status
        ]

    def get_summary(
        self,
        *,
        attendance_date: date | None = None,
    ) -> dict[str, int]:
        """Return counts grouped by attendance status."""

        summary = {status: 0 for status in VALID_STATUSES}

        for record in self.get_records_for_date(attendance_date):
            summary[record.status] += 1

        return summary

    def clear_date(self, attendance_date: date) -> None:
        """Delete all in-memory records for a specific date."""

        keys_to_remove = [
            key for key in self.records if key[1] == attendance_date
        ]

        for key in keys_to_remove:
            del self.records[key]

    def load_records(self, records: Iterable[AttendanceRecord]) -> None:
        """Load records, useful later when reading from a database."""

        for record in records:
            self._save(record)