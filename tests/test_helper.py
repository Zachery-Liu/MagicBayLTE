# SPDX-License-Identifier: AGPL-3.0-only
"""Privilege boundary and persistent intent; no USB or network changes."""
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch, Mock
import lte_helper as helper


class HelperProtocol(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        p=patch.object(helper,'PREFERENCE',Path(self.temporary.name)/'preferences.json')
        p.start();self.addCleanup(p.stop)

    def call(self, data, uid=501, console=501, enabled=True):
        connection=Mock()
        connection.recv.return_value=data
        with patch.object(helper,'peer_uid',return_value=uid), patch.object(helper,'console_uid',return_value=console):
            result=helper.accept_command(connection,enabled)
        return result,connection

    def test_disable_is_saved_before_ack_and_survives_restart(self):
        result,connection=self.call(b'D\n')
        self.assertFalse(result)
        self.assertFalse(helper.read_preference())
        self.assertEqual(helper.PREFERENCE.stat().st_mode & 0o777,0o600)
        connection.sendall.assert_called_once_with(b'OK\n')

    def test_enable_is_idempotent(self):
        self.call(b'E\n');result,_=self.call(b'E\n')
        self.assertTrue(result)
        self.assertTrue(helper.read_preference())

    def test_other_login_user_and_login_window_denied_before_read(self):
        for uid,console in ((502,501),(501,502),(0+100,100)):
            result,connection=self.call(b'D\n',uid,console)
            self.assertTrue(result)
            connection.recv.assert_not_called()
            connection.sendall.assert_called_once_with(b'DENIED\n')
            self.assertFalse(helper.PREFERENCE.exists())

    def test_only_exact_bounded_commands_are_accepted(self):
        for data in (b'X\n',b'E x',b'D\x00\n',b'/bin/sh\n',b''):
            result,connection=self.call(data)
            self.assertTrue(result)
            connection.sendall.assert_called_once_with(b'INVALID\n')
            self.assertFalse(helper.PREFERENCE.exists())

    def test_split_request_is_supported(self):
        connection=Mock();connection.recv.side_effect=[b'D',b'\n']
        with patch.object(helper,'peer_uid',return_value=501),patch.object(helper,'console_uid',return_value=501):
            self.assertFalse(helper.accept_command(connection,True))

    def test_reconnect_is_fixed_action_and_preserves_enabled_preference(self):
        connection=Mock();connection.recv.return_value=b'R\n';restart=Mock()
        with patch.object(helper,'peer_uid',return_value=501),patch.object(helper,'console_uid',return_value=501):
            self.assertTrue(helper.accept_command(connection,True,restart))
        restart.assert_called_once_with()
        connection.sendall.assert_called_once_with(b'OK\n')
        self.assertFalse(helper.PREFERENCE.exists())

    def test_disabled_or_other_user_cannot_request_reconnect(self):
        for enabled,uid in ((False,501),(True,502)):
            connection=Mock();connection.recv.return_value=b'R\n';restart=Mock()
            with patch.object(helper,'peer_uid',return_value=uid),patch.object(helper,'console_uid',return_value=501):
                self.assertEqual(helper.accept_command(connection,enabled,restart),enabled)
            restart.assert_not_called()
            self.assertFalse(helper.PREFERENCE.exists())

    def test_reconnect_only_signals_verified_supervisor(self):
        with patch.object(helper.auto,'alive',return_value={'pid':123}),patch.object(helper.os,'kill') as kill:
            helper.reconnect_worker()
        kill.assert_called_once_with(123,helper.signal.SIGUSR2)
        with patch.object(helper.auto,'alive',return_value=None),patch.object(helper.os,'kill') as kill:
            with self.assertRaises(OSError):helper.reconnect_worker()
        kill.assert_not_called()

    def test_failed_write_is_not_acknowledged(self):
        with patch.object(helper,'atomic_json',side_effect=OSError('disk error')):
            with self.assertRaises(OSError): self.call(b'D\n')

    def test_invalid_root_preference_fails_closed(self):
        helper.PREFERENCE.write_text(json.dumps({'enabled':'false'}))
        with self.assertRaises(ValueError): helper.read_preference()

    def test_missing_preference_defaults_to_disabled(self):
        self.assertFalse(helper.read_preference())

    def test_real_peer_credentials(self):
        import os
        left,right=socket.socketpair()
        with left,right:
            self.assertEqual(helper.peer_uid(left),os.getuid())


if __name__=='__main__':
    unittest.main()
