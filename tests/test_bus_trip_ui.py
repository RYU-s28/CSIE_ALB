import ast
from datetime import date
from pathlib import Path
import sys
from types import ModuleType
from urllib.parse import urlencode, parse_qs
import unittest
from unittest.mock import MagicMock, patch

from bot.search_context import begin_search, consume_search, clear_search


class BusTripUITests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 10, 15)
        self.state = {'morning': {'snapshot': {'students': {'S1': {'name': 'Name'}}}},
                      'morning_no_bus': ['S1'], 'no_bus': [], 'eligible': ['S1'], 'expected_return': 1}
        self.transport = MagicMock()
        self.transport.get_state.return_value = self.state
        self.namespace = {
            'time_out': self.transport,
            'search_query': lambda query: query or '',
            'search_button': lambda day, **values: {'search': values},
            'paragraph': lambda text: {'text': text},
            '_stat_row': lambda label, value, **kwargs: {'label': label, 'value': value},
            '_button': lambda label, data, **kwargs: {'label': label, 'data': data},
            'action': lambda name, **values: urlencode({'action': name, **values}),
            'card': lambda title, contents, buttons, **kwargs: {'title': title, 'contents': contents, 'buttons': buttons},
        }
        tree = ast.parse(Path('bot/time_out_portal.py').read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {'bus_message', 'handle_time_out'}]
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'bot/time_out_portal.py', 'exec'), self.namespace)

    def test_morning_picker_shows_morning_count_and_trip_in_toggle(self):
        db = ModuleType('database.google_sheets')
        db.search_active_students = lambda query: [{'student_id': 'S1'}]
        with patch.dict(sys.modules, {'database.google_sheets': db}):
            card = self.namespace['bus_message'](self.day, query='S1', trip='morning')
        self.assertEqual(card['title'], 'Morning Bus')
        self.assertIn({'label': 'No Bus', 'value': '1'}, card['contents'])
        self.assertEqual(card['buttons'][0]['search']['trip'], 'morning')
        data = parse_qs(card['buttons'][1]['data'])
        self.assertEqual(data['trip'], ['morning'])
        self.assertEqual(data['excluded'], ['0'])

    def test_afternoon_picker_does_not_inherit_morning_selection(self):
        card = self.namespace['bus_message'](self.day, trip='afternoon')
        self.assertEqual(card['title'], 'Afternoon Bus')
        self.assertIn({'label': 'No Bus', 'value': '0'}, card['contents'])

    def test_search_context_keeps_trip(self):
        try:
            begin_search('Uadmin', self.day, bus=True, trip='morning')
            context = consume_search('Uadmin')
            self.assertEqual(context.trip, 'morning')
            self.assertTrue(context.bus)
        finally:
            clear_search('Uadmin')

    def test_postback_writes_and_reopens_selected_trip(self):
        commands = ModuleType('bot.commands')
        commands.is_admin_user = lambda actor: True
        self.namespace['bus_message'] = MagicMock(return_value='picker')
        data = {'action': ['admin_timeout_set_bus'], 'student': ['S1'], 'excluded': ['1'], 'trip': ['morning']}
        with patch.dict(sys.modules, {'bot.commands': commands}):
            self.assertEqual(self.namespace['handle_time_out'](data, 'Uadmin', self.day), 'picker')
        self.transport.set_bus_exception.assert_called_once_with(self.day, 'S1', True, trip='morning')
        self.assertEqual(self.namespace['bus_message'].call_args.kwargs['trip'], 'morning')


if __name__ == '__main__':
    unittest.main()
