import importlib.util
import pathlib
import types
import unittest
import io
import contextlib
from unittest.mock import patch

MODULE = pathlib.Path(__file__).with_name('mxmaster3_gestures.py')
spec = importlib.util.spec_from_file_location('mxmaster3_gestures', MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Codes:
    EV_KEY = 1
    EV_REL = 2
    EV_ABS = 3
    EV_SYN = 0
    BTN_TOUCH = 330
    BTN_TOOL_FINGER = 325
    BTN_TOOL_DOUBLETAP = 333
    BTN_TOOL_TRIPLETAP = 334
    BTN_TOOL_QUADTAP = 335
    ABS_X = 0
    ABS_Y = 1
    ABS_MT_SLOT = 47
    ABS_MT_POSITION_X = 53
    ABS_MT_POSITION_Y = 54
    ABS_MT_TRACKING_ID = 57
    BUS_VIRTUAL = 6
    INPUT_PROP_POINTER = 0
    REL_X = 0
    REL_Y = 1
    SYN_REPORT = 0
    SYN_DROPPED = 3
    KEY = {202: 'KEY_PROG3', 282: 'BTN_TASK', 276: 'BTN_EXTRA'}
    BTN_TASK = 282
    BTN_MOUSE = 272
    BTN_EXTRA = 276
    BTN_SIDE = 275
    BTN_BACK = 278
    BTN_FORWARD = 277
    KEY_PROG3 = 202
    KEY_F24 = 194
    KEY_A = 30


class Recorder:
    def __init__(self, *args, **kwargs):
        self.capabilities = kwargs['events']
        self.kwargs = kwargs
        self.writes = []
        self.closed = False

    def write(self, kind, code, value):
        self.writes.append((kind, code, value))

    def syn(self):
        self.writes.append(('SYN',))

    def close(self):
        self.closed = True


class Mouse:
    name = 'Logitech MX Master 3'
    path = '/dev/input/event9'
    def __init__(self):
        self.grabbed = False
        self.calls = []
    def grab(self):
        assert not self.grabbed
        self.grabbed = True
        self.calls.append('grab')
    def ungrab(self):
        assert self.grabbed
        self.grabbed = False
        self.calls.append('ungrab')
    def close(self):
        self.calls.append('close')


class FakeInput:
    name = 'Logitech MX Master 3'
    path = '/dev/input/event24'
    def __init__(self, keys, pointer=True, name='Logitech MX Master 3', path='/dev/input/event24'):
        self.keys = keys
        self.pointer = pointer
        self.name = name
        self.path = path
        self.closed = False
    def capabilities(self, absinfo=False):
        return {Codes.EV_KEY: list(self.keys),
                Codes.EV_REL: [Codes.REL_X, Codes.REL_Y] if self.pointer else []}
    def close(self):
        self.closed = True


class GestureTests(unittest.TestCase):
    def setUp(self):
        m.e = Codes
        m.AbsInfo = lambda *args: args
        self.pad = m.SwipeTouchpad(Recorder)
        self.pad.gain = 2.0
        self.ui = self.pad.device

    def tearDown(self):
        self.pad.close()

    def get_written(self, typ, code):
        return [w[2] for w in self.ui.writes if len(w) == 3 and w[0] == typ and w[1] == code]

    def test_virtual_device_gesture_only_no_mouse_or_keyboard(self):
        caps = self.ui.capabilities
        self.assertEqual(set(caps), {Codes.EV_ABS, Codes.EV_KEY})
        self.assertEqual(caps[Codes.EV_KEY], [Codes.BTN_TOUCH, Codes.BTN_TOOL_FINGER,
                                           Codes.BTN_TOOL_DOUBLETAP, Codes.BTN_TOOL_TRIPLETAP,
                                           Codes.BTN_TOOL_QUADTAP])
        self.assertEqual(self.ui.kwargs['input_props'], [Codes.INPUT_PROP_POINTER])
        self.assertEqual(self.ui.kwargs['max_effects'], 0)

    def test_press_creates_three_fingers_and_release_lifts_them(self):
        self.pad.begin()
        self.assertTrue(self.pad.active)
        self.assertEqual(self.get_written(Codes.EV_ABS, Codes.ABS_MT_TRACKING_ID), [1, 2, 3])
        self.assertEqual(self.get_written(Codes.EV_KEY, Codes.BTN_TOOL_TRIPLETAP), [1])
        self.pad.end()
        self.assertFalse(self.pad.active)
        self.assertEqual(self.get_written(Codes.EV_ABS, Codes.ABS_MT_TRACKING_ID), [1,2,3,-1,-1,-1])
        self.assertEqual(self.get_written(Codes.EV_KEY, Codes.BTN_TOUCH), [1,0])
        self.assertEqual(self.get_written(Codes.EV_KEY, Codes.BTN_TOOL_TRIPLETAP), [1,0])

    def test_continuous_reversible_horizontal_motion(self):
        self.pad.begin()
        self.pad.move(100, 0)
        self.assertEqual(self.pad.x, 200)
        self.pad.move(-40, 0)
        self.assertEqual(self.pad.x, 120)
        self.pad.move(-60, 0)
        self.assertEqual(self.pad.x, 0)
        self.assertEqual(self.get_written(Codes.EV_ABS, Codes.ABS_X)[-1], m.CENTER)

    def test_up_and_down_motion_and_edges(self):
        self.pad.begin()
        self.pad.move(0, -90)
        self.assertEqual(self.pad.y, -180)
        self.pad.move(0, 40)
        self.assertEqual(self.pad.y, -100)
        self.pad.move(100000, -100000)
        self.assertTrue(all(0 <= v <= m.TOUCH_MAX for v in self.get_written(Codes.EV_ABS, Codes.ABS_MT_POSITION_X)))
        self.assertTrue(all(0 <= v <= m.TOUCH_MAX for v in self.get_written(Codes.EV_ABS, Codes.ABS_MT_POSITION_Y)))

    def test_slot_three_contacts_translate_as_single_group(self):
        self.pad.begin()
        self.ui.writes.clear()
        self.pad.move(20, -30)
        coords = self.get_written(Codes.EV_ABS, Codes.ABS_MT_POSITION_X)
        self.assertEqual(coords, [m.CENTER+40-m.FINGER_SPACING, m.CENTER+40, m.CENTER+40+m.FINGER_SPACING])
        self.assertEqual(self.get_written(Codes.EV_ABS, Codes.ABS_MT_POSITION_Y), [m.CENTER-60]*3)

    def test_gesture_mode_grabs_and_releases_mouse(self):
        mouse = Mouse()
        runner = m.GestureRunner(mouse, [mouse], self.pad)
        event = lambda t,c,v: types.SimpleNamespace(type=t, code=c, value=v)
        runner.event(mouse, event(Codes.EV_KEY, m.GESTURE_KEY, 1))
        self.assertTrue(mouse.grabbed)
        runner.event(mouse, event(Codes.EV_REL, Codes.REL_X, 48))
        runner.event(mouse, event(Codes.EV_SYN, Codes.SYN_REPORT, 0))
        self.assertEqual(self.pad.x, 96)
        runner.event(mouse, event(Codes.EV_KEY, m.GESTURE_KEY, 0))
        self.assertFalse(mouse.grabbed)
        self.assertFalse(self.pad.active)
        self.assertEqual(mouse.calls, ['grab', 'ungrab'])
        runner.close()
        self.assertTrue(self.ui.closed)

    def test_release_flushes_pending_motion_and_on_stream_error(self):
        mouse = Mouse()
        runner = m.GestureRunner(mouse, [mouse], self.pad)
        event = lambda t,c,v: types.SimpleNamespace(type=t, code=c, value=v)
        runner.event(mouse, event(Codes.EV_KEY, m.GESTURE_KEY, 1))
        runner.event(mouse, event(Codes.EV_REL, Codes.REL_Y, -50))
        runner.event(mouse, event(Codes.EV_KEY, m.GESTURE_KEY, 0))
        self.assertEqual(self.pad.y, -100)
        runner.event(mouse, event(Codes.EV_KEY, m.GESTURE_KEY, 1))
        runner.event(mouse, event(Codes.EV_SYN, Codes.SYN_DROPPED, 0))
        self.assertFalse(mouse.grabbed)
        self.assertFalse(self.pad.active)

    def test_disabling_mouse_gesture_does_not_change_pointer_events(self):
        mouse = Mouse()
        runner = m.GestureRunner(mouse, [mouse], self.pad)
        event = types.SimpleNamespace(type=Codes.EV_REL, code=Codes.REL_X, value=55)
        runner.event(mouse, event)
        self.assertEqual((runner.dx, runner.dy), (0,0))
        self.assertEqual(mouse.calls, [])

    def test_pick_mouse_prefers_product_name(self):
        def d(path, name):
            return types.SimpleNamespace(path=path, name=name)
        items = [(d('/dev/input/event1','Logitech USB Receiver'), True, False),
                 (d('/dev/input/event2','Logitech MX Master 3'), True, True)]
        self.assertEqual(m.select_mouse(items).path, '/dev/input/event2')
        with self.assertRaisesRegex(RuntimeError, 'Cannot uniquely identify'):
            m.select_mouse([(d('/dev/input/event3','other'), True, False)])

    def test_auto_detect_btn_task_when_prog3_absent(self):
        dev = FakeInput({Codes.BTN_TASK})
        self.assertEqual(m.select_button([dev]), Codes.BTN_TASK)

    def test_auto_detect_legacy_prog3(self):
        dev = FakeInput({Codes.KEY_PROG3})
        self.assertEqual(m.select_button([dev]), Codes.KEY_PROG3)

    def test_explicit_other_button_can_be_selected(self):
        dev = FakeInput({Codes.BTN_EXTRA})
        self.assertEqual(m.select_button([dev], Codes.BTN_EXTRA), Codes.BTN_EXTRA)
        self.assertEqual(m.parse_button('BTN_EXTRA'), Codes.BTN_EXTRA)
        self.assertEqual(m.parse_button('282'), Codes.BTN_TASK)
        self.assertEqual(m.parse_button('auto'), None)

    def test_no_button_fails_with_safe_setup_status(self):
        with self.assertRaisesRegex(m.InputSetupError, 'No standard gesture button'):
            m.select_button([FakeInput({Codes.BTN_BACK})])
        with self.assertRaisesRegex(m.InputSetupError, 'not available'):
            m.select_button([FakeInput({Codes.BTN_BACK})], Codes.BTN_TASK)

    def test_btn_task_event_grabs_moves_and_releases(self):
        mouse = Mouse()
        runner = m.GestureRunner(mouse, [mouse], self.pad, button=Codes.BTN_TASK)
        event = lambda t,c,v: types.SimpleNamespace(type=t, code=c, value=v)
        runner.event(mouse, event(Codes.EV_KEY, Codes.KEY_PROG3, 1))
        self.assertFalse(runner.held)
        runner.event(mouse, event(Codes.EV_KEY, Codes.BTN_TASK, 1))
        self.assertTrue(runner.held)
        runner.event(mouse, event(Codes.EV_REL, Codes.REL_X, 80))
        runner.event(mouse, event(Codes.EV_SYN, Codes.SYN_REPORT, 0))
        self.assertEqual(self.pad.x, 160)
        runner.event(mouse, event(Codes.EV_KEY, Codes.BTN_TASK, 0))
        self.assertFalse(runner.held)
        self.assertFalse(mouse.grabbed)

    def test_f24_from_other_keyboard_controls_physical_mouse(self):
        mouse = Mouse()
        keyboard = FakeInput({Codes.KEY_F24, Codes.KEY_A}, pointer=False,
                             name='Solaar virtual keyboard', path='/dev/input/event12')
        runner = m.GestureRunner(mouse, [mouse, keyboard], self.pad)
        event = lambda t, c, v: types.SimpleNamespace(type=t, code=c, value=v)
        runner.event(keyboard, event(Codes.EV_KEY, Codes.KEY_A, 1))
        self.assertFalse(runner.held)
        runner.event(keyboard, event(Codes.EV_KEY, Codes.KEY_F24, 1))
        self.assertTrue(runner.held)
        self.assertTrue(mouse.grabbed)
        runner.event(mouse, event(Codes.EV_REL, Codes.REL_X, 50))
        runner.event(mouse, event(Codes.EV_REL, Codes.REL_Y, -20))
        runner.event(mouse, event(Codes.EV_SYN, Codes.SYN_REPORT, 0))
        self.assertEqual((self.pad.x, self.pad.y), (100, -40))
        runner.event(keyboard, event(Codes.EV_KEY, Codes.KEY_F24, 2))
        self.assertTrue(runner.held)  # autorepeat is not a release
        runner.event(keyboard, event(Codes.EV_KEY, Codes.KEY_F24, 0))
        self.assertFalse(runner.held)
        self.assertFalse(mouse.grabbed)
        self.assertFalse(self.pad.active)

    def test_releasing_different_button_or_source_keeps_gesture_active(self):
        mouse = Mouse()
        keyboard = FakeInput({Codes.KEY_F24}, pointer=False)
        other = FakeInput({Codes.KEY_F24}, pointer=False, name='another keyboard')
        runner = m.GestureRunner(mouse, [mouse, keyboard, other], self.pad)
        event = lambda t, c, v: types.SimpleNamespace(type=t, code=c, value=v)
        runner.event(keyboard, event(Codes.EV_KEY, Codes.KEY_F24, 1))
        runner.event(other, event(Codes.EV_KEY, Codes.KEY_F24, 0))
        runner.event(mouse, event(Codes.EV_KEY, Codes.BTN_TASK, 0))
        self.assertTrue(runner.held)
        runner.event(keyboard, event(Codes.EV_KEY, Codes.KEY_F24, 0))
        self.assertFalse(runner.held)

    def test_f24_sources_discovered_without_grabbing_keyboards(self):
        devices = {
            '/dev/input/event1': FakeInput({Codes.KEY_F24, Codes.KEY_A}, False,
                                           'Solaar keyboard', '/dev/input/event1'),
            '/dev/input/event2': FakeInput({Codes.BTN_TASK}, True,
                                           'Logitech MX Master 3', '/dev/input/event2'),
            '/dev/input/event3': FakeInput({Codes.KEY_A}, False,
                                           'Physical keyboard', '/dev/input/event3'),
        }
        with patch.object(m, 'list_devices', return_value=list(devices)), \
             patch.object(m, 'InputDevice', side_effect=lambda path: devices[path]):
            found, errors = m.open_f24_keyboards()
        self.assertEqual([d.path for d in found], ['/dev/input/event1'])
        self.assertFalse(errors)
        self.assertTrue(devices['/dev/input/event2'].closed)
        self.assertTrue(devices['/dev/input/event3'].closed)

    def test_explicit_f24_keyboard_device_is_respected(self):
        devices = {
            '/dev/input/event1': FakeInput({Codes.KEY_F24}, False,
                                           path='/dev/input/event1'),
            '/dev/input/event2': FakeInput({Codes.KEY_F24}, False,
                                           path='/dev/input/event2'),
        }
        with patch.object(m, 'list_devices', return_value=list(devices)), \
             patch.object(m, 'InputDevice', side_effect=lambda path: devices[path]):
            found, errors = m.open_f24_keyboards('/dev/input/event2')
        self.assertEqual([d.path for d in found], ['/dev/input/event2'])
        self.assertFalse(errors)

    def test_explicit_f24_button_setting(self):
        self.assertEqual(m.parse_button('KEY_F24'), Codes.KEY_F24)
        self.assertEqual(m.parse_button('194'), Codes.KEY_F24)


# Integration-style bridge checks do not need real Logitech input hardware.
class SolaarBridgeTests(unittest.TestCase):
    def setUp(self):
        m.e = Codes
        m.AbsInfo = lambda *args: args
        self.pad = m.SwipeTouchpad(Recorder)

    def tearDown(self):
        self.pad.close()

    def test_solaar_controls_live_motion_and_releases(self):
        mouse = Mouse()
        runner = m.GestureRunner(mouse, [mouse], self.pad)
        runner.control(b'press')
        self.assertTrue(mouse.grabbed)
        event = lambda t, c, v: types.SimpleNamespace(type=t, code=c, value=v)
        runner.event(mouse, event(Codes.EV_REL, Codes.REL_X, -52))
        runner.event(mouse, event(Codes.EV_SYN, Codes.SYN_REPORT, 0))
        self.assertEqual(self.pad.x, -104)
        runner.control(b'release')
        self.assertFalse(mouse.grabbed)
        self.assertFalse(self.pad.active)

    def test_invalid_control_does_not_grab_mouse(self):
        mouse = Mouse()
        runner = m.GestureRunner(mouse, [mouse], self.pad)
        runner.control(b'random')
        self.assertFalse(runner.held)
        self.assertFalse(mouse.grabbed)

    def test_repeated_press_and_release_do_not_leak_grab(self):
        mouse = Mouse()
        runner = m.GestureRunner(mouse, [mouse], self.pad)
        runner.control(b'press')
        runner.control(b'press')
        runner.control(b'release')
        runner.control(b'release')
        self.assertEqual(mouse.calls, ['grab', 'ungrab'])

    def test_control_socket_is_private_and_delivers_datagram(self):
        import tempfile, os, socket
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            Path(directory).chmod(0o700)
            with patch.dict(os.environ, {'XDG_RUNTIME_DIR': directory}):
                path = m.control_socket_path()
                self.assertEqual(path.parent, Path(directory))
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
                    server.bind(str(path))
                    m.send_solaar_signal('press')
                    self.assertEqual(server.recv(128), b'press')
                path.unlink()


class SolaarRulesTests(unittest.TestCase):
    def test_rules_install_preserves_other_rules_and_is_idempotent(self):
        import tempfile
        from pathlib import Path
        import sys
        path = Path(__file__).with_name('solaar_bridge.py')
        spec = importlib.util.spec_from_file_location('solaar_bridge', path)
        sm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sm)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'rules.yaml'
            other = '---\n- Key: [Forward Button, pressed]\n- Execute: [notify-send, hello]\n...\n'
            config.write_text(other)
            self.assertTrue(sm.update(config, 'install', Path('/tmp/test gesture.py')))
            first = config.read_text()
            self.assertIn('Mouse Gesture Button, pressed', first)
            self.assertIn('Mouse Gesture Button, released', first)
            self.assertIn(other, first)
            sm.update(config, 'install', Path('/tmp/test gesture.py'))
            self.assertEqual(first, config.read_text())
            self.assertTrue(sm.update(config, 'remove'))
            self.assertEqual(config.read_text(), other)


class SolaarSocketLoopTests(unittest.TestCase):
    def test_live_socket_dispatches_press_and_release(self):
        import os
        import tempfile
        import threading
        import time
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory).chmod(0o700)
            with patch.dict(os.environ, {'XDG_RUNTIME_DIR': directory}):
                m.e = Codes
                m.AbsInfo = lambda *args: args
                pad = m.SwipeTouchpad(Recorder)
                mouse = Mouse()
                rfd, wfd = os.pipe()
                mouse.fd = rfd
                runner = m.GestureRunner(mouse, [mouse], pad)
                errors = []
                def run():
                    try:
                        runner.run()
                    except Exception as ex:
                        errors.append(ex)
                thread = threading.Thread(target=run, daemon=True)
                try:
                    with patch.object(m, 'systemd_notify_ready'):
                        thread.start()
                        path = m.control_socket_path()
                        for _ in range(100):
                            if path.exists():
                                break
                            time.sleep(0.005)
                        self.assertTrue(path.exists())
                        m.send_solaar_signal('press')
                        for _ in range(100):
                            if runner.held:
                                break
                            time.sleep(0.005)
                        self.assertTrue(runner.held)
                        self.assertTrue(mouse.grabbed)
                        m.send_solaar_signal('release')
                        for _ in range(100):
                            if not runner.held:
                                break
                            time.sleep(0.005)
                        self.assertFalse(runner.held)
                        self.assertFalse(mouse.grabbed)
                finally:
                    runner.running = False
                    thread.join(2)
                    os.close(rfd)
                    os.close(wfd)
                self.assertFalse(thread.is_alive())
                self.assertFalse(errors)
                self.assertFalse(path.exists())



class FastSolaarSignalTests(unittest.TestCase):
    """Real executable tests, with an ephemeral private UNIX socket."""

    def _build(self, out):
        import shutil, subprocess
        if not shutil.which('cc'):
            self.skipTest('C compiler unavailable')
        source = pathlib.Path(__file__).with_name('fast_signal.c')
        subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-std=c11',
                        '-o', str(out), str(source)], check=True, capture_output=True)

    def test_fast_helper_signals_press_release_to_socket(self):
        import os, tempfile, socket, subprocess
        with tempfile.TemporaryDirectory() as directory:
            runtime = pathlib.Path(directory) / 'run'
            runtime.mkdir(mode=0o700)
            helper = pathlib.Path(directory) / 'mxmaster3-gesture-signal'
            self._build(helper)
            env = {**os.environ, 'XDG_RUNTIME_DIR': str(runtime)}
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as listener:
                listener.bind(str(runtime / m.CONTROL_SOCKET))
                listener.settimeout(1)
                for action in ('press', 'release'):
                    proc = subprocess.run([str(helper), action], env=env,
                                          capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(listener.recv(128), action.encode())

    def test_fast_helper_does_not_send_invalid_actions(self):
        import os, tempfile, socket, subprocess
        with tempfile.TemporaryDirectory() as directory:
            runtime = pathlib.Path(directory) / 'run'
            runtime.mkdir(mode=0o700)
            helper = pathlib.Path(directory) / 'signal'
            self._build(helper)
            env = {**os.environ, 'XDG_RUNTIME_DIR': str(runtime)}
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as listener:
                listener.bind(str(runtime / m.CONTROL_SOCKET))
                listener.settimeout(0.05)
                self.assertNotEqual(subprocess.run([str(helper), 'delete'], env=env,
                                                  capture_output=True).returncode, 0)
                with self.assertRaises(socket.timeout):
                    listener.recv(128)

    def test_fast_helper_rejects_nonprivate_runtime(self):
        import os, tempfile, subprocess
        with tempfile.TemporaryDirectory() as directory:
            runtime = pathlib.Path(directory) / 'run'
            runtime.mkdir(mode=0o755)
            helper = pathlib.Path(directory) / 'signal'
            self._build(helper)
            env = {**os.environ, 'XDG_RUNTIME_DIR': str(runtime)}
            p = subprocess.run([str(helper), 'press'], env=env, capture_output=True)
            self.assertNotEqual(p.returncode, 0)

    def test_bridge_migrates_v4_python_rules_to_fast_helper(self):
        import tempfile, importlib.util
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            helper = root / 'native messenger'
            helper.write_text('#!/bin/sh\nexit 0\n')
            helper.chmod(0o700)
            rules = root / 'rules.yaml'
            source = pathlib.Path(__file__).with_name('solaar_bridge.py')
            spec = importlib.util.spec_from_file_location('fast_solaar_bridge', source)
            bridge = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bridge)
            original = bridge.bridge_rule_block(root / 'old_driver.py', fast_helper=root / 'no-helper')
            other = '---\n- Key: [Back Button, pressed]\n- KeyPress: [Left]\n...\n'
            rules.write_text(original + other)
            with patch.object(bridge, 'FAST_HELPER_PATH', helper):
                self.assertTrue(bridge.update(rules, 'install', root / 'old_driver.py'))
                updated = rules.read_text()
                self.assertIn(str(helper), updated)
                self.assertNotIn('--solaar', updated)
                self.assertTrue(updated.endswith(other))
                self.assertFalse(bridge.update(rules, 'install', root / 'old_driver.py'))
                self.assertTrue(bridge.update(rules, 'remove'))
                self.assertEqual(rules.read_text(), other)


class SettingsTests(unittest.TestCase):
    """Test settings with no GTK, Logitech hardware, or real user config."""

    def test_four_finger_swipe_is_real_four_contact_mt(self):
        from mxmaster3_gesture_config import GestureSettings
        m.e = Codes
        m.AbsInfo = lambda *args: args
        pad = m.SwipeTouchpad(Recorder, settings=GestureSettings(fingers=4))
        try:
            caps = pad.device.capabilities
            self.assertIn(Codes.BTN_TOOL_QUADTAP, caps[Codes.EV_KEY])
            slot_cap = next(info for code, info in caps[Codes.EV_ABS] if code == Codes.ABS_MT_SLOT)
            self.assertEqual(slot_cap[2], 3)
            pad.begin()
            tool_events = pad.device.writes
            self.assertIn((Codes.EV_KEY, Codes.BTN_TOOL_QUADTAP, 1), tool_events)
            tracks = [e[2] for e in tool_events if len(e) == 3 and e[:2] == (Codes.EV_ABS, Codes.ABS_MT_TRACKING_ID)]
            self.assertEqual(tracks, [1, 2, 3, 4])
            pad.move(20, -15)
            self.assertEqual(pad.x, 40)
            pad.end()
            self.assertEqual([e[2] for e in pad.device.writes if len(e)==3 and e[:2]==(Codes.EV_ABS, Codes.ABS_MT_TRACKING_ID)][-4:], [-1]*4)
            self.assertIn((Codes.EV_KEY, Codes.BTN_TOOL_QUADTAP, 0), pad.device.writes)
            self.assertNotIn((Codes.EV_KEY, Codes.BTN_TOOL_TRIPLETAP, 1), pad.device.writes)
        finally:
            pad.close()

    def test_flick_threshold_and_strength(self):
        from mxmaster3_gesture_config import GestureSettings
        m.e = Codes
        m.AbsInfo = lambda *args: args
        settings = GestureSettings(flick_enabled=True, flick_boost=1.0, flick_threshold=600)
        pad = m.SwipeTouchpad(Recorder, settings=settings)
        mouse = Mouse()
        runner = m.GestureRunner(mouse, [mouse], pad)
        try:
            with patch.object(m.time, 'monotonic', side_effect=[100.0, 100.02, 100.04]):
                runner.press()
                runner.dx = 10  # 500 counts/sec: no extra movement
                runner.flush()
                self.assertEqual(pad.x, 20)
                runner.dx = 40  # 2000 counts/sec: max 2x velocity multiplier
                runner.flush()
                self.assertEqual(pad.x, 180)
            runner.release()
        finally:
            runner.close()

    def test_flick_disabled_preserves_exact_old_motion(self):
        from mxmaster3_gesture_config import GestureSettings
        m.e = Codes
        m.AbsInfo = lambda *args: args
        pad = m.SwipeTouchpad(Recorder, settings=GestureSettings(flick_enabled=False, flick_boost=2.0))
        mouse = Mouse()
        runner = m.GestureRunner(mouse, [mouse], pad)
        try:
            runner.press()
            runner.dx = 20
            runner.flush()
            self.assertEqual(pad.x, 40)
        finally:
            runner.close()

    def test_settings_save_load_preserves_custom_device_variables(self):
        import tempfile
        from mxmaster3_gesture_config import read_settings, write_settings, GestureSettings
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / 'config.conf'
            path.write_text('# Manual settings\nMXG_MOUSE=/dev/input/event42\nMXG_FINGERS=3\n')
            settings = GestureSettings(3.25, 4, True, 1.5, 950)
            write_settings(settings, path)
            first = path.read_text()
            self.assertIn('MXG_MOUSE=/dev/input/event42', first)
            self.assertEqual(first.count('MXG_FINGERS='), 1)
            self.assertEqual(read_settings(path, env={}), settings)
            write_settings(settings, path)
            self.assertEqual(first, path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(read_settings(path, env={'MXG_FINGERS':'3'}).fingers, 3)

    def test_invalid_configs_are_safe_and_do_not_change_user_file(self):
        import tempfile
        from mxmaster3_gesture_config import read_settings, write_settings, GestureSettings
        with tempfile.TemporaryDirectory() as root:
            path = pathlib.Path(root) / 'config.conf'
            path.write_text('MXG_SENSITIVITY=nan\nMXG_FINGERS=100\nMXG_FLICK_BOOST=inf\nMXG_FLICK_THRESHOLD=-500\n')
            self.assertEqual(read_settings(path, env={}), GestureSettings())
            original = path.read_text()
            with self.assertRaises(ValueError):
                write_settings(GestureSettings(fingers=12), path)
            self.assertEqual(path.read_text(), original)
            path.write_text('# BEGIN MX Touchpad Gestures preferences\ncorrupted')
            with self.assertRaises(ValueError):
                write_settings(GestureSettings(), path)

    def test_config_has_no_gtk_runtime_dependency(self):
        import mxmaster3_gesture_config as config
        self.assertFalse('gi' in config.__dict__)


if __name__ == '__main__':
    unittest.main(verbosity=2)
