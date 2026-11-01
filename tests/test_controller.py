# SPDX-License-Identifier: AGPL-3.0-only
"""Lifecycle tests: all process, USB, HTTP and route access is mocked."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('lte_control', Path(__file__).resolve().parents[1] / 'tools/lte_control.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        for key, value in [('BASE', self.base), ('ENGINE', self.base/'magicbay_lte'),
                           ('STATE', self.base/'connection-state.json'), ('LOG', self.base/'connection.log')]:
            p = patch.object(c, key, value); p.start(); self.addCleanup(p.stop)
        c.ENGINE.touch()
        self.output = io.StringIO()
        p = contextlib.redirect_stdout(self.output); p.__enter__(); self.addCleanup(p.__exit__, None, None, None)
        # Any unmocked subprocess call fails immediately, never touches the host network.
        for name in ('run', 'Popen'):
            p = patch.object(c.subprocess, name, side_effect=AssertionError('Unmocked subprocess'))
            p.start(); self.addCleanup(p.stop)

    def launch(self, health=None, route=True, identity='birth', poll=None):
        process = Mock(pid=12345, returncode=1)
        process.poll.side_effect = poll
        if poll is None:
            process.poll.return_value = None
        def spawn(*args, **kwargs):
            kwargs['stdout'].write('UTUN : utun99\nutun + routes ready\n')
            kwargs['stdout'].flush()
            return process
        health = health or subprocess.CompletedProcess([], 0, '{"Status":0,"Answer":[{}]}', '')
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(c, 'running', return_value=None))
            stack.enter_context(patch.object(c, 'conflict', return_value=False))
            stack.enter_context(patch.object(c, 'identity', return_value=identity))
            stack.enter_context(patch.object(c, 'route_matches', return_value=route))
            stack.enter_context(patch.object(c.time, 'sleep'))
            stack.enter_context(patch.object(c.subprocess, 'Popen', side_effect=spawn))
            stack.enter_context(patch.object(c.subprocess, 'run', side_effect=health if isinstance(health, Exception) else None,
                                            return_value=None if isinstance(health, Exception) else health))
            result = c.start()
        return result, process

    def test_success_preserves_process(self):
        result, process = self.launch()
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(c.STATE.read_text())['phase'], 'connected')
        process.send_signal.assert_not_called()

    def test_http_failure_stops_child(self):
        result, process = self.launch(subprocess.CompletedProcess([], 7, '', 'failed'))
        self.assertEqual(result, 1)
        process.send_signal.assert_called_once_with(c.signal.SIGUSR1)
        self.assertFalse(c.STATE.exists())

    def test_malformed_json_stops_child(self):
        result, process = self.launch(subprocess.CompletedProcess([], 0, 'not JSON', ''))
        self.assertEqual(result, 1)
        process.wait.assert_called_once()
        self.assertFalse(c.STATE.exists())

    def test_health_exception_stops_child(self):
        result, process = self.launch(subprocess.TimeoutExpired('mock curl', 10))
        self.assertEqual(result, 1)
        process.wait.assert_called_once()

    def test_route_mismatch_stops_child(self):
        result, process = self.launch(route=False)
        self.assertEqual(result, 1)
        process.wait.assert_called_once()

    def test_identity_failure_stops_child(self):
        result, process = self.launch(identity=None)
        self.assertEqual(result, 1)
        process.wait.assert_called_once()

    def test_early_exit_not_success(self):
        result, process = self.launch(poll=[1, 1, 1, 1])
        self.assertEqual(result, 1)
        self.assertFalse(c.STATE.exists())
        process.send_signal.assert_not_called()

    def test_state_write_failure_stops_child(self):
        with patch.object(c, 'save_state', side_effect=OSError('mock disk full')):
            result, process = self.launch()
        self.assertEqual(result, 1)
        process.wait.assert_called_once()

    def test_stop_timeout_keeps_state(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired('mock engine', 25)
        self.assertFalse(c.shutdown(process))
        process.kill.assert_not_called()

    def test_old_pid_birth_is_rejected(self):
        c.STATE.write_text(json.dumps({'pid': 12345, 'process_started': 'old'}))
        with patch.object(c, 'identity', return_value='new'):
            self.assertIsNone(c.running())

    def test_archive_preserves_log(self):
        c.LOG.write_text('previous USB error')
        c.archive_log()
        self.assertFalse(c.LOG.exists())
        self.assertEqual(next((self.base/'logs').iterdir()).read_text(), 'previous USB error')

    def test_diagnostic_process_is_recognized_for_stop(self):
        c.STATE.write_text(json.dumps({'pid': 12345, 'process_started': 'birth', 'diagnostic': True}))
        with patch.object(c, 'identity', return_value='birth') as check:
            self.assertIsNotNone(c.running())
        check.assert_called_once_with(12345, diagnostic=True)

    def test_identity_requires_correct_binary(self):
        result = subprocess.CompletedProcess([], 0, str(c.ENGINE.with_name('magicbay_lte_test')), '')
        born = subprocess.CompletedProcess([], 0, 'birth', '')
        with patch.object(c, 'command', side_effect=[result, born, result, born]):
            self.assertIsNone(c.identity(12345))
            self.assertEqual(c.identity(12345, diagnostic=True), 'birth')

    def test_status_does_not_call_curl(self):
        with patch.object(c, 'running', return_value={'phase': 'connected', 'interface': 'utun99'}), \
                patch.object(c, 'route_matches', return_value=False):
            self.assertEqual(c.main(['status']), 0)
        self.assertIn('不能确认联网', self.output.getvalue())


if __name__ == '__main__':
    unittest.main()
