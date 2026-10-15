import importlib.util
from datetime import date
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import MagicMock, patch

from attendance.report import StudentDisplay


class TimeOutMonthlySourceTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 10, 15)
        self.students = {sid: StudentDisplay(sid, sid) for sid in ('A', 'B', 'C', 'D', 'E')}
        self.rows = [{'student_id': sid, 'type': value} for sid, value in
                     [('A', ''), ('B', '病假'), ('C', '不坐公交車'), ('D', '特休'), ('E', '待確認')]]
        self.db = ModuleType('database.google_sheets')
        self.db.get_report_students = MagicMock(return_value=(self.students, 5))
        self.db.get_daily_monthly_report = MagicMock(side_effect=lambda *a, **kw: [row.copy() for row in self.rows])
        self.db.get_attendance_rows = MagicMock(side_effect=AssertionError('Must not read Attendance logs'))
        modules = patch.dict(sys.modules, {'database.google_sheets': self.db})
        modules.start()
        self.addCleanup(modules.stop)
        spec = importlib.util.spec_from_file_location('_timeout_monthly_test', Path('attendance/time_out.py'))
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.sheet = MagicMock()
        self.draft = None
        def read(tab, headers, day):
            return self.sheet, None, self.draft if tab == 'Time Out Drafts' else None
        mocked = patch.object(self.module, '_read_row', side_effect=read)
        mocked.start()
        self.addCleanup(mocked.stop)

    def test_state_uses_fresh_grid_and_does_not_need_morning_snapshot(self):
        with patch.object(self.module, 'get_morning', side_effect=AssertionError('No frozen morning source')):
            state = self.module.get_state(self.day)
        self.assertEqual(state['morning']['snapshot']['attended'], 3)
        self.assertEqual(state['eligible'], ['A', 'C'])
        self.assertEqual(state['no_bus'], [])
        self.assertEqual(state['expected_return'], 2)
        report = self.module.compose_report(state, 2)
        self.assertIn('實到人數：3', report)
        self.assertIn('病假：1人\n@B', report)
        self.assertIn('回到學校：2', report)
        self.assertNotIn('不坐公交車', report)
        self.db.get_attendance_rows.assert_not_called()
        self.db.get_daily_monthly_report.assert_called_once_with(self.day, fresh=True, students=self.students)

    def test_sheet_edits_change_return_count_and_clear_old_absences(self):
        before = self.module.get_state(self.day)
        self.rows[1]['type'] = ''  # Clear B's sick leave.
        self.rows[2]['type'] = ''  # Clear C's no-bus status.
        after = self.module.get_state(self.day)
        self.assertEqual(after['expected_return'], 3)
        self.assertEqual(after['no_bus'], [])
        self.assertNotIn('病假', after['morning']['report'])
        self.assertNotEqual(before['fingerprint'], after['fingerprint'])
        self.assertEqual(after['fingerprint'], self.module.get_state(self.day)['fingerprint'])

    def test_explicit_bus_overrides_still_apply(self):
        self.draft = [self.day.isoformat(), '{"A": true}']
        state = self.module.get_state(self.day)
        self.assertEqual(state['no_bus'], ['A'])
        self.assertEqual(state['expected_return'], 1)

    def test_false_and_ineligible_overrides_do_not_exclude_passengers(self):
        self.draft = [self.day.isoformat(), '{"A": false, "B": true, "D": true}']
        state = self.module.get_state(self.day)
        self.assertEqual(state['no_bus'], [])
        self.assertEqual(state['expected_return'], 2)
        self.assertNotIn('不坐公交車', self.module.compose_report(state, 2))

    def test_changed_grid_blocks_stale_return_confirmation(self):
        state = self.module.get_state(self.day)
        self.rows[0]['type'] = '病假'
        commands = ModuleType('bot.commands')
        commands.is_admin_user = lambda actor: True
        with patch.dict(sys.modules, {'bot.commands': commands}):
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.module.confirm_return(self.day, 1, 'Uadmin', state['fingerprint'])
        self.sheet.append_row.assert_not_called()


    def test_morning_uber_does_not_exclude_return_bus(self):
        self.draft = [self.day.isoformat(), '{"morning": {"A": true}, "afternoon": {}}']
        state = self.module.get_state(self.day)
        self.assertEqual(state['morning_no_bus'], ['A'])
        self.assertEqual(state['no_bus'], [])
        self.assertEqual(state['expected_return'], 2)
        self.assertEqual(state['morning']['snapshot']['attended'], 3)
        self.assertIn('不坐公交車（上班）：1人\n@A', state['morning']['report'])
        report = self.module.compose_report(state, 2)
        self.assertIn('回到學校：2', report)
        self.assertNotIn('不坐公交車（下班）', report)

    def test_separate_trip_sections_and_return_counts(self):
        self.draft = [self.day.isoformat(), '{"morning": {"A": true}, "afternoon": {"C": true}}']
        state = self.module.get_state(self.day)
        report = self.module.compose_report(state, 1)
        self.assertIn('不坐公交車（上班）：1人\n@A', report)
        self.assertIn('不坐公交車（下班）：1人\n@C', report)
        self.assertIn('回到學校：1', report)
        self.assertEqual(state['expected_return'], 1)

    def test_changing_morning_selection_preserves_legacy_return_choices(self):
        import json
        self.draft = [self.day.isoformat(), '{"C": true}']
        self.module.set_bus_exception(self.day, 'A', True, trip='morning')
        saved = json.loads(self.sheet.append_row.call_args.args[0][1])
        self.assertEqual(saved, {'morning': {'A': True}, 'afternoon': {'C': True}})
        self.db.get_attendance_rows.assert_not_called()

    def test_changing_return_selection_keeps_morning_choices(self):
        import json
        self.draft = [self.day.isoformat(), '{"morning": {"A": true}, "afternoon": {"C": true}}']
        self.module.set_bus_exception(self.day, 'C', False)
        saved = json.loads(self.sheet.append_row.call_args.args[0][1])
        self.assertEqual(saved, {'morning': {'A': True}, 'afternoon': {'C': False}})

    def test_morning_report_transport_does_not_change_attendance(self):
        from attendance.report import build_report, records_from_monthly_report
        self.draft = [self.day.isoformat(), '{"morning": {"A": true}, "afternoon": {"C": true}}']
        records = records_from_monthly_report(self.day, self.students)
        original = build_report(report_date=self.day, total_students=5, students=self.students, records=records)
        report = self.module.apply_morning_bus(self.day, original, records, self.students)
        self.assertIn('實到人數：3', report)
        self.assertIn('不坐公交車（上班）：1人\n@A', report)
        self.assertNotIn('不坐公交車（下班）', report)
        self.assertNotIn('不坐公交車：', report)
        self.assertNotIn('回到學校', report)

    def test_invalid_trip_does_not_write(self):
        with self.assertRaisesRegex(ValueError, 'morning or afternoon'):
            self.module.set_bus_exception(self.day, 'A', True, trip='invalid')
        self.sheet.append_row.assert_not_called()


if __name__ == '__main__':
    unittest.main()
