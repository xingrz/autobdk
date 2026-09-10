import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('autobdk', ROOT / 'autobdk.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


def instant(value='2026-09-26T20:00'):
    return datetime.fromisoformat(value).replace(tzinfo=b.ZONE)


def item(kind=1, day='2026-09-01', at=None):
    return {'date': day, 'clock_type': kind, 'range_id': 'r1', 'time': at or ('10:00' if kind == 1 else '19:00'), 'reason': ''}


def plan(entries=None):
    return {'schema_version': 1, 'kind': 'attendance_plan', 'host': 'https://attendance.example.com', 'account': 'Example User', 'month': '2026-09', 'entries': [item()] if entries is None else entries}


class FakeClient:
    host = 'https://attendance.example.com'
    account = 'Example User'

    def __init__(self):
        self.sent, self.flows, self.months = [], [], []
        self.slots = [dict(clockAttribution=1, rangeId='r1', clockTime='', statusDesc=''), dict(clockAttribution=2, rangeId='r1', clockTime='19:00', statusDesc='')]
        self.error = None

    def month(self, month):
        self.months.append(month)
        return [{'time': b.timestamp('2026-09-01'), 'situation': -1, 'isWorkday': 1}] if month == '2026-09' else []

    def detail(self, day):
        return {'signTimeList': self.slots, 'bdkErrorMessage': None}

    def approvals(self, day):
        return self.flows

    def settings(self):
        return {'flow_type': 6, 'flowSettingId': 7, 'departmentList': [{'departmentId': 'd1'}]}

    def submit(self, entry, settings, department):
        self.sent.append(entry)
        if self.error:
            raise self.error
        self.flows.append({'startDate': int(datetime.fromisoformat(entry['date']+'T'+entry['time']).replace(tzinfo=b.ZONE).timestamp()), 'flowSid': 'f1'})
        return {'flowSid': 'f1'}


class AttendanceTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(b, 'now', return_value=instant())
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.client = FakeClient()

    def test_cycle_boundaries_and_year_rollover(self):
        for value, state in [('2026-09-25T23:59', 'not_open'), ('2026-09-26T00:00', 'open'), ('2026-09-30T23:59', 'open'), ('2026-10-01T00:00', 'frozen')]:
            self.assertEqual(b.cycle('2026-09', instant(value))['state'], state)
        self.assertEqual(b.cycle('2026-01')['start'], '2025-12-26')
        self.assertEqual(b.cycle('2024-02')['freezes_at'], '2024-03-01T00:00:00+08:00')

    def test_timezone_is_explicit(self):
        with patch.dict(os.environ, {'TZ': 'UTC'}):
            self.assertEqual(datetime.fromtimestamp(b.timestamp('2026-09-01'), b.ZONE).date().isoformat(), '2026-09-01')
            report = b.inspect(self.client, ['2026-09'])
            self.assertEqual(report['cycles'][0]['records'][0]['date'], '2026-09-01')

    def test_scan_two_months_and_keep_incomplete_slots(self):
        self.client.slots = self.client.slots[:1]
        report = b.inspect(self.client, ['2026-09'])
        self.assertEqual(self.client.months, ['2026-08', '2026-09'])
        self.assertTrue(report['cycles'][0]['records'][0]['incomplete_slots'])
        self.assertEqual(len(b.make_plan(report)['entries']), 1)

    def test_other_anomalies_require_explicit_inclusion(self):
        self.client.slots[0].update(clockTime='10:05', statusDesc='Late')
        report = b.inspect(self.client, ['2026-09'])
        self.assertEqual(b.make_plan(report)['entries'], [])
        self.assertEqual(len(b.make_plan(report, True)['entries']), 1)

    def test_unknown_approval_at_eleven_requires_review(self):
        self.client.flows = [{'startDate': b.timestamp('2026-09-01')+11*3600, 'isFinish': 1}]
        report = b.inspect(self.client, ['2026-09'])
        self.assertEqual(b.make_plan(report)['entries'], [])
        with self.assertRaisesRegex(b.ToolError, 'cannot be mapped'):
            b.apply_plan(self.client, plan(), interval=0)
        self.assertEqual(self.client.sent, [])

    def test_apply_and_repeat_skip_existing(self):
        self.assertEqual(b.apply_plan(self.client, plan(), interval=0)['submitted'], 1)
        self.assertEqual(b.apply_plan(self.client, plan(), interval=0)['skipped'], 1)
        self.assertEqual(len(self.client.sent), 1)

    def test_two_missing_slots_submit_and_replay_without_self_blocking(self):
        self.client.slots[1]['clockTime'] = ''
        both = plan([item(kind=2), item()])
        self.assertEqual(b.apply_plan(self.client, both, interval=0)['submitted'], 2)
        self.assertEqual(b.apply_plan(self.client, both, interval=0)['skipped'], 2)
        self.assertEqual(len(self.client.sent), 2)

    def test_resolved_planned_start_uses_actual_time_for_order(self):
        self.client.slots[0]['clockTime'] = '10:05'
        self.client.slots[1]['clockTime'] = ''
        with self.assertRaisesRegex(b.ToolError, 'Start must precede'):
            b.apply_plan(self.client, plan([item(), item(kind=2, at='10:02')]), interval=0)
        self.assertEqual(self.client.sent, [])

    def test_freeze_between_entries_stops_remaining_writes(self):
        def after_write(*args):
            b.now.return_value = instant('2026-10-01T00:00')
        with patch.object(b.time, 'sleep', side_effect=after_write):
            result = b.apply_plan(self.client, plan([item(), item(day='2026-09-02'), item(day='2026-09-03')]), interval=0)
        self.assertEqual(result['submitted'], 1)
        self.assertEqual(result['failed'], 1)
        self.assertEqual(result['not_attempted'], 1)
        self.assertEqual(len(self.client.sent), 1)

    def test_malformed_write_response_is_unknown(self):
        class Response:
            url = b.DEFAULT_HOST + '/test'
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'[]'
        with patch.dict(os.environ, {}, clear=True):
            client = b.Client({'token': 'example-session', 'app_secret': 'example-key'})
        with patch.object(b, 'urlopen', return_value=Response()):
            with self.assertRaises(b.ToolError) as caught:
                client.request('/test', {}, write=True)
        self.assertTrue(caught.exception.uncertain)

    def test_all_entries_validated_before_writes(self):
        for bad in [item(day='2026-08-25'), item(at='24:00'), {**item(), 'clock_type': True}]:
            with self.assertRaises(b.ToolError):
                b.apply_plan(self.client, plan([item(), bad]), interval=0)
        self.assertEqual(self.client.sent, [])

    def test_no_cross_account_submission(self):
        with self.assertRaisesRegex(b.ToolError, 'another host or account'):
            b.apply_plan(self.client, {**plan(), 'account': 'Another User'}, interval=0)
        self.assertEqual(self.client.sent, [])

    def test_frozen_plan_cannot_submit(self):
        with patch.object(b, 'now', return_value=instant('2026-10-01T00:00')):
            with self.assertRaises(b.ToolError) as caught:
                b.apply_plan(self.client, plan(), interval=0)
        self.assertEqual(caught.exception.code, 'WINDOW_CLOSED')
        self.assertEqual(self.client.sent, [])

    def test_network_uncertainty_stops_batch_without_retry(self):
        self.client.error = b.ToolError('NETWORK_ERROR', 'Timed out', uncertain=True)
        result = b.apply_plan(self.client, plan([item(), item(day='2026-09-02')]), interval=0)
        self.assertEqual(result['unknown'], 1)
        self.assertEqual(result['not_attempted'], 1)
        self.assertEqual(len(self.client.sent), 1)

    def test_duplicate_response_is_reconciled_once(self):
        self.client.error = b.ToolError('DUPLICATE_SUBMISSION', 'Duplicate')
        result = b.apply_plan(self.client, plan(), interval=0)
        self.assertEqual(result['unknown'], 1)
        self.assertEqual(len(self.client.sent), 1)

    def test_known_failure_is_reported(self):
        self.client.error = b.ToolError('API_ERROR', 'Limit exceeded')
        result = b.apply_plan(self.client, plan(), interval=0)
        self.assertEqual(result['failed'], 1)
        self.assertEqual(result['submitted'], 0)

    def test_end_before_actual_start_is_rejected(self):
        self.client.slots[0]['clockTime'] = '19:30'
        self.client.slots[1]['clockTime'] = ''
        with self.assertRaisesRegex(b.ToolError, 'Start must precede'):
            b.apply_plan(self.client, plan([item(kind=2)]), interval=0)
        self.assertEqual(self.client.sent, [])

    def test_department_is_not_guessed(self):
        with patch.object(self.client, 'settings', return_value={'flow_type': 6, 'flowSettingId': 7, 'departmentList': [{'departmentId': 'a'}, {'departmentId': 'b'}]}):
            with self.assertRaises(b.ToolError) as caught:
                b.apply_plan(self.client, plan(), interval=0)
        self.assertEqual(caught.exception.code, 'DEPARTMENT_REQUIRED')

    def test_token_precedence_builds_session_cookie(self):
        cfg = {'token': 'config-session', 'app_secret': 'example-key'}
        with patch.dict(os.environ, {'AUTOBDK_TOKEN': 'env-session'}, clear=True):
            client = b.Client(cfg, token='cli-session')
            self.assertEqual(client.headers['Cookie'], 'QJYDSID=cli-session')
            self.assertEqual(b.Client(cfg).headers['Cookie'], 'QJYDSID=env-session')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(b.Client(cfg).headers['Cookie'], 'QJYDSID=config-session')

    def test_token_is_sent_as_cookie_before_and_after_csrf_bootstrap(self):
        class Response:
            url = b.DEFAULT_HOST
            def __init__(self, data): self.data = data
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps({'status': True, 'data': self.data}).encode()
        cookie = 'QJYDSID=example-session-id'
        responses = [Response({'employeeName': 'Example User', 'csrf': 'example-csrf'}), Response({'records': []})]
        with patch.dict(os.environ, {}, clear=True), patch.object(b, 'urlopen', side_effect=responses) as transport:
            client = b.Client({'app_secret': 'example-key'}, token='example-session-id')
            client.login()
            client.month('2026-08')
        bootstrap, monthly = [call.args[0] for call in transport.call_args_list]
        for request in (bootstrap, monthly):
            self.assertEqual(request.get_header('Cookie'), cookie)
            self.assertIsNone(request.get_header('Authorization'))
        self.assertIsNone(bootstrap.get_header('X-csrf-token'))
        self.assertEqual(monthly.get_header('X-csrf-token'), 'example-csrf')
        self.assertEqual(monthly.data, b'yearmo=202608')

    def test_configure_does_not_echo_values(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(b, 'CONFIG_PATH', Path(tmp)/'config.json'), patch('sys.stdin', io.StringIO('{"token":"example-session"}')):
            result = b.configure('-')
            self.assertNotIn('example-session', json.dumps(result))
            self.assertEqual(b.CONFIG_PATH.stat().st_mode & 0o777, 0o600)

    def test_business_failure_not_treated_as_success(self):
        class Response:
            url = b.DEFAULT_HOST + '/test'
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"status":false,"message":"Rejected"}'
        with patch.dict(os.environ, {}, clear=True):
            client = b.Client({'token': 'example-session', 'app_secret': 'example-key'})
        with patch.object(b, 'urlopen', return_value=Response()):
            with self.assertRaises(b.ToolError) as caught:
                client.request('/test')
        self.assertEqual(caught.exception.code, 'API_ERROR')

    def test_cli_from_another_directory_has_json_errors_without_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, 'XDG_CONFIG_HOME': tmp}
            for key in list(env):
                if key.startswith('AUTOBDK_'): del env[key]
            result = subprocess.run([sys.executable, str(ROOT/'autobdk.py'), 'inspect'], cwd=tmp, env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)['error']['code'], 'AUTH_REQUIRED')
            self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
