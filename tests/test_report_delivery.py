import unittest
from unittest.mock import MagicMock, patch

from linebot.v3.messaging.exceptions import ApiException
from bot.report_delivery import delivery_error, report_chunks, report_failure, send_report


class ReportDeliveryTests(unittest.TestCase):
    def test_unicode_chunks_preserve_report_and_limit(self):
        text = '出席😀' * 6000
        chunks = list(report_chunks(text))
        self.assertEqual(''.join(chunks), text)
        self.assertTrue(all(len(c.encode('utf-16-le')) // 2 <= 4900 for c in chunks))

    def test_invalid_group_does_not_call_line(self):
        with patch('bot.report_delivery.ApiClient') as client:
            self.assertFalse(send_report(None, 'Cwrong', 'report'))
            client.assert_not_called()
        self.assertIn('LINE_REPORT_GROUP_ID', report_failure.get())

    def test_failure_reasons(self):
        for status, body, expected in [
            (401, '{}', 'access token'),
            (429, '{"message":"You have reached your monthly limit."}', 'monthly message quota'),
            (429, '{}', 'message limit'),
            (400, '{}', 'destination'),
            (403, 'invalid JSON', 'denied access'),
        ]:
            error = ApiException(status=status)
            error.body = body
            self.assertIn(expected, delivery_error(error))

    @patch('bot.report_delivery.MessagingApi')
    @patch('bot.report_delivery.ApiClient')
    def test_batching_and_reset(self, client, api):
        report_failure.set('old failure')
        self.assertTrue(send_report(None, 'C' + 'a' * 32, 'a' * (4900 * 6)))
        calls = api.return_value.push_message.call_args_list
        self.assertEqual([len(c.kwargs['push_message_request'].messages) for c in calls], [5, 1])
        self.assertEqual(report_failure.get(), '')

    @patch('bot.report_delivery.MessagingApi')
    @patch('bot.report_delivery.ApiClient')
    def test_partial_failure_reports_duplicate_risk(self, client, api):
        error = ApiException(status=429)
        error.body = '{"message":"monthly limit"}'
        api.return_value.push_message.side_effect = [None, error]
        self.assertFalse(send_report(None, 'C' + 'a' * 32, 'a' * (4900 * 6)))
        self.assertIn('Part of the report was sent', report_failure.get())
        self.assertIn('duplicate', report_failure.get())


if __name__ == '__main__':
    unittest.main()
