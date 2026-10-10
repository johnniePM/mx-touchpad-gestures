"""Integration provisioning tests (no hardware, Gtk or live Solaar required)."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('gesture_setup',
                                               Path(__file__).with_name('mxmaster3_gesture_setup.py'))
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def result(rc=0, out='', err=''):
    return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


class SetupTests(unittest.TestCase):
    def test_rule_install_restarts_solaar_and_diverts_button(self):
        calls = []
        def command(args, timeout=12):
            calls.append(args)
            if args[0] == setup.BRIDGE:
                return result(0, 'Solaar bridge rules installed')
            return result()
        with patch.object(setup, '_run', side_effect=command), \
             patch.object(setup.shutil, 'which', return_value='/usr/bin/solaar'), \
             patch.object(setup, 'solaar_running', return_value=True), \
             patch.object(setup, 'restart_solaar') as restart:
            self.assertTrue(setup.configure_solaar())
            restart.assert_called_once()
            self.assertEqual(calls[1], ['solaar', 'config', 'MX Master 3', 'divert-keys',
                                        'Mouse Gesture Button', 'Diverted'])

    def test_rules_unchanged_skips_restart(self):
        with patch.object(setup, '_run', side_effect=[
             result(0, 'Solaar bridge rules up to date'), result()]), \
             patch.object(setup.shutil, 'which', return_value='/usr/bin/solaar'), \
             patch.object(setup, 'solaar_running', return_value=True), \
             patch.object(setup, 'restart_solaar') as restart:
            self.assertTrue(setup.configure_solaar())
            restart.assert_not_called()

    def test_no_solaar_allows_direct_input(self):
        with patch.object(setup.shutil, 'which', return_value=None), \
             patch.object(setup, '_run') as command:
            self.assertFalse(setup.configure_solaar())
            command.assert_not_called()

    def test_unavailable_mouse_never_claims_success(self):
        with patch.object(setup, '_run', side_effect=[
             result(0, 'Solaar bridge rules up to date')] +
             [result(1, err='No matching device')]*6), \
             patch.object(setup.shutil, 'which', return_value='/usr/bin/solaar'), \
             patch.object(setup, 'solaar_running', return_value=True), \
             patch.object(setup.time, 'sleep'):
            with self.assertRaisesRegex(setup.SetupError, 'cannot divert'):
                setup.configure_solaar()

    def test_initial_setup_starts_service_and_records_success(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(setup, 'MARKER', Path(tmp)/'marker'), \
             patch.object(setup, 'configure_solaar', return_value=True), \
             patch.object(setup, 'service_action') as action:
            self.assertTrue(setup.needs_initial_setup())
            self.assertIn('Gestures are running', setup.setup_and_start())
            action.assert_called_once_with('start')
            self.assertFalse(setup.needs_initial_setup())

    def test_failed_setup_does_not_start_or_mark_success(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(setup, 'MARKER', Path(tmp)/'marker'), \
             patch.object(setup, 'configure_solaar', side_effect=setup.SetupError('offline')), \
             patch.object(setup, 'service_action') as action:
            with self.assertRaisesRegex(setup.SetupError, 'offline'):
                setup.setup_and_start()
            self.assertTrue(setup.needs_initial_setup())
            action.assert_not_called()

    def test_service_action_whitelist(self):
        with self.assertRaises(ValueError):
            setup.service_action('disable')


if __name__ == '__main__':
    unittest.main()
