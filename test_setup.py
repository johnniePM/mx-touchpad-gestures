"""Device management tests; no hardware or Solaar process required."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch
import tempfile
import sys

source = Path(__file__).with_name('mxmaster3_gesture_device.py')
spec = importlib.util.spec_from_file_location('mx_gesture_device_test', source)
d = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = d
spec.loader.exec_module(d)

SHOW = """solaar version 1.1.20
Unifying Receiver
  Device path  : /dev/hidraw3
  1: MX Master 3S
     Device path  : None
     Kind         : mouse
     Serial number: A1B2C3D4
  2: MX Keys
     Kind         : keyboard
     Serial number: 22223333
  3: MX Master 3
     Kind         : mouse
     Serial number: ABCD1234
"""


def result(rc=0, out='', err=''):
    return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


class MouseTests(TestCase):
    def test_find_connected_devices_and_ignore_keyboards(self):
        mice=d.parse_mice(SHOW)
        self.assertEqual([(m.name,m.serial) for m in mice],
                         [('MX Master 3S','A1B2C3D4'),('MX Master 3','ABCD1234')])
        self.assertEqual(d.choose_mouse(mice,'ABCD1234').name,'MX Master 3')

    def test_multiple_mice_require_explicit_choice(self):
        with self.assertRaisesRegex(d.DeviceError,'Multiple mice'):
            d.choose_mouse(d.parse_mice(SHOW),'')

    def test_offline_device_ignored(self):
        self.assertFalse(d.parse_mice('  1: MX Master 3S\n     Device is offline.\n'))

    def test_persisted_selection_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'selection.json'
            d.save_selection('A1B2C3D4',path)
            self.assertEqual(d.selected_serial(path),'A1B2C3D4')
            self.assertEqual(path.stat().st_mode&0o777,0o600)

    def test_select_does_not_silently_switch_mice_after_disconnect(self):
        with self.assertRaisesRegex(d.DeviceError,'disconnected'):
            d.choose_mouse(d.parse_mice(SHOW),'MISSINGDEV')

    def test_numeric_control_and_diversion_choice(self):
        mouse=d.Mouse('MX Master 3S','A1B2C3D4')
        with patch.object(d,'run',side_effect=[
             result(out='divert-keys = {Mouse Gesture Button:Regular}'),
             result(out='Setting divert-keys key 195 to Diverted'),
             result(out='divert-keys = {Mouse Gesture Button:Diverted}')]) as runner:
            self.assertTrue(d.set_diversion(mouse))
        self.assertEqual(runner.call_args_list[1].args[0],
                         ['solaar','config','A1B2C3D4','divert-keys','195','2'])

    def test_idempotent_when_already_diverted(self):
        with patch.object(d,'run',return_value=result(out='divert-keys = {Mouse Gesture Button:Diverted}')) as runner:
            self.assertFalse(d.set_diversion(d.Mouse('MX Master 3','A1B2C3D4')))
            self.assertEqual(runner.call_count,1)

    def test_successful_wayland_warning_not_error(self):
        with patch.object(d,'run',return_value=result(
             out='divert-keys = {Mouse Gesture Button:Diverted}',
             err='rules cannot access modifier keys in Wayland, accessing process only works on GNOME with Solaar Gnom')):
            self.assertTrue(d.diverted(d.Mouse('MX Master 3','A1B2C3D4')))

    def test_failed_set_does_not_claim_success(self):
        with patch.object(d,'run',side_effect=[
             result(out='divert-keys = {Mouse Gesture Button:Regular}'),
             result(out='Changed'),
             result(out='divert-keys = {Mouse Gesture Button:Regular}'),
             result(out='divert-keys = {Mouse Gesture Button:Regular}'),
             result(out='divert-keys = {Mouse Gesture Button:Regular}')]), \
             patch.object(d.time, 'sleep'):
            with self.assertRaisesRegex(d.DeviceError,'did not confirm'):
                d.set_diversion(d.Mouse('MX Master 3','A1B2C3D4'))

    def test_start_fails_without_claiming_success(self):
        mouse=d.Mouse('MX Master 3','A1B2C3D4')
        with patch.object(d,'solaar_running',return_value=True), \
             patch.object(d,'list_mice',return_value=[mouse]), \
             patch.object(d,'install_rules',return_value=False), \
             patch.object(d,'set_diversion'), \
             patch.object(d,'selected_serial',return_value='A1B2C3D4'), \
             patch.object(d,'run',return_value=result(1,err='Service failed')):
            with self.assertRaisesRegex(d.DeviceError,'Service failed'):
                d.start_gestures()

    def test_serialless_connected_mouse_from_real_solaar_show(self):
        # User's actual "solaar show" output: top-level mouse has empty serial.
        # Its Unit ID is repeated in the firmware feature description.
        output = """MX Master 3 Wireless Mouse
     Device path  : /dev/hidraw4
     Codename     : MX Master 3
     Kind         : mouse
     Protocol     : HID++ 4.5
     Serial number:
     Model ID:      B02340820000
     Unit ID:       E7533B4B
     Supports 27 HID++ 2.0 features:
         0: ROOT {0000} V0
         1: FEATURE SET {0001} V0
         2: DEVICE FW VERSION {0003} V2
             Unit ID: E7533B4B  Model ID: B02340820000
             Name: Wireless Mouse MX Master 3
             Kind: mouse
             Friendly Name: MX Master 3
"""
        mice = d.parse_mice(output)
        self.assertEqual(len(mice), 1)
        self.assertEqual(mice[0].serial, 'E7533B4B')
        self.assertTrue(mice[0].unit_only)
        self.assertEqual(mice[0].cli_selector, 'MX Master 3 Wireless Mouse')
        self.assertEqual(d.choose_mouse(mice).serial, 'E7533B4B')

    def test_serialless_mice_with_same_cli_name_are_not_mutated(self):
        mice = [d.Mouse('MX Master 3 Wireless Mouse','E7533B4B',True),
                d.Mouse('MX Master 3 Wireless Mouse','OTHER123',True)]
        with self.assertRaisesRegex(d.DeviceError, 'cannot uniquely select'):
            d.choose_mouse(mice, 'E7533B4B')

    def test_full_map_query_avoids_solaar_keyed_read_bug(self):
        mouse = d.Mouse('MX Master 3 Wireless Mouse', 'E7533B4B', True)
        output = """# Key/Button Diversion
# Make the key or button send HID++ notifications
divert-keys = {Middle Button:Regular, Mouse Gesture Button:Diverted, Back Button:Regular}
"""
        with patch.object(d, 'run', return_value=result(out=output)) as run:
            self.assertTrue(d.diverted(mouse))
        self.assertEqual(run.call_args.args[0],
                         ['solaar', 'config', 'MX Master 3 Wireless Mouse', 'divert-keys'])

    def test_full_map_write_uses_mouse_name_for_unit_id_only_device(self):
        mouse = d.Mouse('MX Master 3 Wireless Mouse', 'E7533B4B', True)
        before = 'divert-keys = {Middle Button:Regular, Mouse Gesture Button:Regular}'
        after = 'divert-keys = {Middle Button:Regular, Mouse Gesture Button:Diverted}'
        with patch.object(d, 'run', side_effect=[result(out=before), result(out='Setting diverted'), result(out=after)]) as command:
            self.assertTrue(d.set_diversion(mouse))
        self.assertEqual(command.call_args_list[1].args[0],
                         ['solaar', 'config', 'MX Master 3 Wireless Mouse',
                          'divert-keys', '195', '2'])

    def test_full_map_missing_gesture_control_never_claims_diversion(self):
        with patch.object(d, 'run', return_value=result(out='divert-keys = {Middle Button:Regular}')):
            with self.assertRaisesRegex(d.DeviceError, 'does not report Mouse Gesture Button'):
                d.diverted(d.Mouse('MX Master 3', 'E7533B4B', True))

    def test_existing_serial_still_used_for_cli(self):
        mouse=d.Mouse('MX Master 3','ABCD1234')
        self.assertEqual(mouse.cli_selector,'ABCD1234')
        self.assertFalse(mouse.unit_only)

    def test_stop_disables_reconnect_monitor_then_driver(self):
        with patch.object(d,'run',return_value=result()) as runner:
            d.stop_gestures()
        self.assertEqual(runner.call_args_list[0].args[0],
                         ['systemctl','--user','stop',d.WATCH])
        self.assertEqual(runner.call_args_list[1].args[0],
                         ['systemctl','--user','stop',d.SERVICE])


if __name__ == '__main__':
    main()
