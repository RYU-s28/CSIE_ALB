"""Report keywords and delivery tests with no live LINE/Sheets requests."""
import ast
from datetime import date
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from bot.report_keywords import handle_report_keyword


def route_function(name, namespace):
    tree = ast.parse(Path('app.py').read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    function.decorator_list = []
    namespace.setdefault('FlexMessage', object)
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'app.py', 'exec'), namespace)
    return namespace[name]


class KeywordTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 10, 15)
        self.reply = MagicMock(return_value=True)
        self.generate = MagicMock(return_value='應到人數：41\n實到人數：39')
        self.confirm = MagicMock(return_value='應到人數：41\n實到人數：39\n\n回到學校：38')
        self.state = {'expected_return': 38, 'fingerprint': 'state'}
        modules = {}
        for name, attrs in {
            'app': {'send_report_reply': self.reply},
            'bot.commands': {'is_admin_user': MagicMock(return_value=True)},
            'scheduler.work_calendar': {'is_workday': MagicMock(return_value=True)},
            'scheduler.daily_report': {'generate_daily_report': self.generate},
            'attendance.time_out': {'get_state': MagicMock(return_value=self.state), 'confirm_return': self.confirm},
        }.items():
            module = ModuleType(name)
            module.__dict__.update(attrs)
            modules[name] = module
        self.modules = modules
        mocked = patch.dict(sys.modules, modules)
        mocked.start()
        self.addCleanup(mocked.stop)
        env = patch.dict('os.environ', {'LINE_REPORT_GROUP_ID': 'Cgroup'})
        env.start()
        self.addCleanup(env.stop)

    def event(self, text, group='Cgroup', private=False):
        return SimpleNamespace(message=SimpleNamespace(text=text), reply_token='reply-token',
                               source=SimpleNamespace(type='user' if private else 'group', group_id=None if private else group, user_id='Uadmin'))

    def test_exact_morning_keyword_replies_with_current_report(self):
        self.assertTrue(handle_report_keyword(self.event(' 上班點名\n'), self.day))
        self.generate.assert_called_once_with(self.day)
        self.reply.assert_called_once_with('reply-token', self.generate.return_value)

    def test_afternoon_keyword_uses_expected_bus_return(self):
        self.assertTrue(handle_report_keyword(self.event('下班點名'), self.day))
        self.confirm.assert_called_once_with(self.day, 38, 'Uadmin', 'state')
        self.assertIn('回到學校：38', self.reply.call_args.args[1])

    def test_containing_keywords_never_triggers_reports(self):
        for text in ('請上班點名', '上班點名！', '下班點名了嗎', '今天上班點名誰處理', '上班點名 下班點名'):
            self.assertFalse(handle_report_keyword(self.event(text), self.day))
        self.generate.assert_not_called()
        self.confirm.assert_not_called()
        self.reply.assert_not_called()

    def test_nonadmin_does_not_issue_or_confirm_reports(self):
        self.modules['bot.commands'].is_admin_user.return_value = False
        self.assertTrue(handle_report_keyword(self.event('下班點名'), self.day))
        self.confirm.assert_not_called()
        self.reply.assert_not_called()

    def test_private_or_wrong_group_does_not_publish_attendance(self):
        for event in (self.event('上班點名', private=True), self.event('上班點名', group='Cother')):
            self.assertTrue(handle_report_keyword(event, self.day))
        self.generate.assert_not_called()
        self.confirm.assert_not_called()
        self.assertEqual(self.reply.call_count, 2)

    def test_missing_morning_does_not_invent_return_count(self):
        self.modules['attendance.time_out'].get_state.return_value = None
        self.assertTrue(handle_report_keyword(self.event('下班點名'), self.day))
        self.confirm.assert_not_called()
        self.assertIn('Monthly Report is unavailable', self.reply.call_args.args[1])

    def test_rest_day_does_not_generate(self):
        self.modules['scheduler.work_calendar'].is_workday.return_value = False
        handle_report_keyword(self.event('上班點名'), self.day)
        self.generate.assert_not_called()
        self.assertIn('rest day', self.reply.call_args.args[1])

    def test_keyword_is_not_sent_for_translation(self):
        from bot.group_translation import translation_job
        for keyword in ('上班點名', '下班點名'):
            self.assertIsNone(translation_job(self.event(keyword)))


class ReplyDeliveryTests(unittest.TestCase):
    def test_report_uses_reply_once_without_push(self):
        from linebot.v3.messaging import ReplyMessageRequest, TextMessage
        api, client = MagicMock(), MagicMock()
        namespace = {'ApiClient': client, 'configuration': None, 'MessagingApi': MagicMock(return_value=api),
                     'ReplyMessageRequest': ReplyMessageRequest, 'TextMessage': TextMessage}
        send = route_function('send_report_reply', namespace)
        self.assertTrue(send('reply-token', '應到人數：41\n實到人數：39'))
        request = api.reply_message.call_args.kwargs['reply_message_request']
        self.assertEqual(request.reply_token, 'reply-token')
        self.assertEqual(request.messages[0].text, '應到人數：41\n實到人數：39')
        api.reply_message.assert_called_once()
        api.push_message.assert_not_called()

    def test_private_report_is_preview_and_group_report_uses_current_token(self):
        import os
        from attendance.report import GroupReportText, DailyReportText
        for private in (True, False):
            with self.subTest(private=private):
                reply, push = MagicMock(return_value=True), MagicMock()
                namespace = {'destination': SimpleNamespace(get=lambda: SimpleNamespace(private=private, group_id='Cgroup')),
                             'os': os, 'GroupReportText': GroupReportText, 'DailyReportText': DailyReportText,
                             'send_report_reply': reply, 'push_to_line': push}
                send = route_function('reply_to_line', namespace)
                with patch.dict(os.environ, {'LINE_REPORT_GROUP_ID': 'Cgroup'}):
                    self.assertTrue(send('token', GroupReportText('應到人數：41')))
                reply.assert_called_once_with('token', '應到人數：41')
                push.assert_not_called()

    def test_scheduler_no_longer_registers_daily_push(self):
        tree = ast.parse(Path('scheduler/daily_report.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'start_scheduler')
        scheduler = MagicMock()
        scheduler.running = False
        namespace = {'scheduler': scheduler, 'mark_present_job': MagicMock()}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'scheduler/daily_report.py', 'exec'), namespace)
        namespace['start_scheduler']()
        self.assertEqual([c.kwargs['id'] for c in scheduler.add_job.call_args_list], ['mark_present_monthly_report'])


if __name__ == '__main__':
    unittest.main()
