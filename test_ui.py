"""Exercise the real libadwaita UI under a temporary X11 display.

Run with: xvfb-run -a /usr/bin/python3 -m unittest -q test_ui.py
No input hardware, Solaar daemon, or user's GNOME session is required.
"""
import importlib.util
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault('GSETTINGS_BACKEND', 'memory')

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gtk

src = Path(__file__).with_name('mxmaster3_gestures_settings.py')
spec = importlib.util.spec_from_file_location('mx_native_preferences', src)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


class NativePreferencesTests(TestCase):
    def test_window_builds_with_native_controls_and_persists_values(self):
        with patch.object(ui, 'service_active', return_value=False), \
             patch.object(ui, 'needs_initial_setup', return_value=False), \
             patch.object(ui.GLib, 'idle_add', return_value=0):
            app = ui.Preferences()
            self.assertTrue(app.register(None))
            app.activate()
            try:
                self.assertIsInstance(app.window, Adw.ApplicationWindow)
                self.assertIsInstance(app.toasts, Adw.ToastOverlay)
                toolbar = app.toasts.get_child()
                self.assertIsInstance(toolbar, Adw.ToolbarView)
                self.assertIsInstance(toolbar.get_content(), Adw.PreferencesPage)
                self.assertIsInstance(app.mouse_choice, Adw.ComboRow)
                self.assertIsInstance(app.fingers, Adw.ComboRow)
                self.assertIsInstance(app.flick_enabled, Adw.SwitchRow)
                self.assertIsInstance(app.status_row, Adw.ActionRow)
                self.assertIsInstance(app.gesture_speed, Gtk.Scale)
                self.assertIsInstance(app.pointer, Gtk.Scale)
                self.assertIsInstance(app.apply_button, Gtk.Button)
                self.assertIsInstance(app.daemon_button, Gtk.Button)

                from mxmaster3_gesture_config import GestureSettings
                original = GestureSettings(sensitivity=3.5, fingers=4,
                                           flick_enabled=True,
                                           flick_boost=1.1, flick_threshold=850)
                app._load_values(original)
                self.assertEqual(app.fingers.get_selected(), 1)
                self.assertAlmostEqual(app.gesture_speed.get_value(), 3.5)
                self.assertTrue(app.flick_enabled.get_active())
                self.assertTrue(app.boost.get_sensitive())
                app.flick_enabled.set_active(False)
                self.assertFalse(app.boost.get_sensitive())
                self.assertFalse(app.threshold.get_sensitive())
                app._notice('Connection failed: test error', error=True)
                self.assertIn('test error', app.status_row.get_subtitle())
            finally:
                app.window.destroy()
                app.quit()
