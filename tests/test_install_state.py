# SPDX-License-Identifier: AGPL-3.0-only
"""Lifecycle regression tests in disposable directories; no installed service changes."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import install_state
import lte_service
import local_access


class InstallationState(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.preference = self.base / 'preferences.json'

    def test_missing_configuration_never_infers_consent_from_old_state(self):
        (self.base / 'auto-state.json').write_text('{"active":true}')
        self.assertFalse(install_state.read_preference(self.preference))
        self.assertFalse(install_state.initialize(self.base))
        self.assertEqual(json.loads(self.preference.read_text()), {'enabled': False})

    def test_upgrade_preserves_only_explicit_boolean_intent(self):
        for enabled in (True, False):
            self.preference.write_text(json.dumps({'enabled': enabled}))
            self.assertEqual(install_state.initialize(self.base), enabled)
            self.assertEqual(install_state.read_preference(self.preference), enabled)
            self.assertEqual(self.preference.stat().st_mode & 0o777, 0o600)

    def test_invalid_preferences_abort_instead_of_guessing(self):
        for data in ('{', 'null', '[]', '{}', '{"enabled":1}', '{"enabled":"true"}'):
            self.preference.write_text(data)
            with self.assertRaises(ValueError):
                install_state.initialize(self.base)

    def test_symlink_preference_is_rejected_without_modifying_target(self):
        other = self.base / 'other'
        other.write_text('{"enabled":true}')
        self.preference.symlink_to(other)
        with self.assertRaises(PermissionError):
            install_state.initialize(self.base)
        self.assertEqual(other.read_text(), '{"enabled":true}')

    def seed_uninstall(self):
        self.preference.write_text('{"enabled":true}')
        for name in install_state.RUNTIME_STATE:
            (self.base / name).write_text('old state')
        (self.base / 'logs').mkdir()
        (self.base / 'logs/service.log').write_text('diagnostic')
        (self.base / 'Source').mkdir()
        (self.base / 'Source/LICENSE').write_text('source notice')

    def test_uninstall_then_reinstall_is_disabled_and_preserves_logs_source(self):
        self.seed_uninstall()
        with patch.object(lte_service, 'TARGET', self.base), \
             patch.object(lte_service, 'PLIST', self.base / 'daemon.plist'), \
             patch.object(lte_service, 'hard_stop') as stop:
            lte_service.uninstall()
        stop.assert_called_once_with()
        self.assertFalse(install_state.initialize(self.base))
        self.assertFalse(any((self.base / name).exists() for name in install_state.RUNTIME_STATE))
        self.assertTrue((self.base / 'logs/service.log').exists())
        self.assertTrue((self.base / 'Source/LICENSE').exists())

    def test_failed_stop_cannot_erase_live_process_identity_or_consent(self):
        self.seed_uninstall()
        with patch.object(lte_service, 'TARGET', self.base), \
             patch.object(lte_service, 'hard_stop', side_effect=RuntimeError('still running')):
            with self.assertRaises(RuntimeError):
                lte_service.uninstall()
        self.assertTrue(install_state.read_preference(self.preference))
        self.assertTrue((self.base / 'auto-state.json').exists())

    def test_remove_logs_is_explicit_and_retains_source(self):
        self.seed_uninstall()
        install_state.reset_after_stop(self.base, remove_logs=True)
        self.assertFalse((self.base / 'logs').exists())
        self.assertTrue((self.base / 'Source/LICENSE').exists())


class DiagnosticAccess(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def acl(self, path):
        import subprocess
        return subprocess.check_output(['/bin/ls', '-lde', str(path)], text=True)

    def test_existing_and_future_files_are_private_with_read_only_console_acl(self):
        logs = self.base / 'logs'
        logs.mkdir()
        old = logs / 'service.log'
        old.write_text('diagnostic')
        state = self.base / 'modem-state.json'
        state.write_text('{}')
        local_access.configure(self.base, os.getuid())
        fresh = logs / 'managed.log'
        with local_access.private_output(fresh) as output:
            output.write('new diagnostic')
        for path in (old, fresh, state):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            acl = self.acl(path)
            self.assertIn('allow read,readattr,readextattr,readsecurity', acl)
            self.assertNotIn('allow write', acl)
        self.assertEqual(logs.stat().st_mode & 0o777, 0o700)
        local_access.write_json(self.base / 'auto-state.json', {'active': False})
        self.assertIn('inherited allow read', self.acl(self.base / 'auto-state.json'))
        install_state.initialize(self.base)
        self.assertNotIn('allow read', self.acl(self.base / 'preferences.json'))

    def test_logout_revokes_old_console_acl_on_existing_and_future_files(self):
        local_access.configure(self.base, os.getuid())
        with local_access.private_output(self.base / 'logs/service.log') as output:
            output.write('diagnostic')
        local_access.configure(self.base, 0)
        for path in (self.base, self.base / 'logs', self.base / 'logs/service.log'):
            self.assertNotIn('allow ', self.acl(path))

    def test_output_cannot_follow_symlink_or_truncate_hardlink(self):
        target = self.base / 'target'
        target.write_text('keep')
        link = self.base / 'link'
        link.symlink_to(target)
        with self.assertRaises(OSError):
            local_access.private_output(link)
        link.unlink()
        os.link(target, link)
        with self.assertRaises(PermissionError):
            local_access.private_output(link)
        self.assertEqual(target.read_text(), 'keep')

    def test_log_directory_symlink_is_rejected(self):
        other = self.base / 'other'
        other.mkdir()
        (self.base / 'logs').symlink_to(other, target_is_directory=True)
        with self.assertRaises(PermissionError):
            local_access.configure(self.base, os.getuid())
