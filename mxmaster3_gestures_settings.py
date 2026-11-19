#!/usr/bin/env python3
"""GNOME-native libadwaita preferences for MX Touchpad Gestures.

All gesture and Solaar configuration remains in the existing backend modules.
License: AGPL-3.0-only.
"""

import subprocess
import sys
import threading

# Package data is installed in /usr/lib, while checkouts import locally.
if __file__.startswith('/usr/bin/'):
    sys.path.insert(0, '/usr/lib/mx-touchpad-gestures')
from mxmaster3_gesture_config import GestureSettings, read_settings, write_settings
from mxmaster3_gesture_setup import setup_and_start, needs_initial_setup, stop_gestures
from mxmaster3_gesture_device import list_mice, selected_serial, save_selection

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Adw, Gio, Gtk, GLib
except (ImportError, ValueError) as exc:
    sys.exit(f'MX Touchpad Gestures Settings requires libadwaita and GTK 4: {exc}')

SERVICE = 'mxmaster3-gestures.service'


def service_active():
    try:
        return subprocess.run(['systemctl', '--user', 'is-active', '--quiet', SERVICE],
                              check=False, timeout=3).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def service_action(action):
    try:
        result = subprocess.run(['systemctl', '--user', action, SERVICE],
                                capture_output=True, text=True, check=False, timeout=12)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(str(exc)) from exc
    if result.returncode:
        raise RuntimeError((result.stderr or f'Unable to {action} service').strip()[:240])


class Preferences(Adw.Application):
    """Adaptive libadwaita preferences with persistent, nonblocking actions."""

    def __init__(self):
        super().__init__(application_id='io.github.johnniePM.MXTouchpadGestures.Settings',
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None
        self.mouse_settings = None
        self._setup_busy = False
        self._device_refreshing = False
        self._mice = []

    def do_activate(self):
        if self.window is not None:
            self.window.present()
            return

        self.window = Adw.ApplicationWindow(application=self)
        self.window.set_title('MX Touchpad Gestures')
        self.window.set_default_size(680, 730)
        self.window.set_size_request(400, 480)

        self.toasts = Adw.ToastOverlay()
        self.window.set_content(self.toasts)

        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle.new('MX Touchpad Gestures',
                                                    'Preferences'))
        toolbar.add_top_bar(header)

        page = Adw.PreferencesPage()
        toolbar.set_content(page)

        device_group = self._group(page, 'Connected mouse',
                                   'Choose the Logitech mouse to use for gestures.')
        self.mouse_choice = Adw.ComboRow()
        self.mouse_choice.set_title('Mouse')
        self.mouse_choice.set_subtitle('Identified by serial number or Unit ID')
        self.mouse_choice.set_model(Gtk.StringList.new(['Searching for mice…']))
        self.mouse_choice.set_sensitive(False)
        device_group.add(self.mouse_choice)

        refresh_row = Adw.ActionRow()
        refresh_row.set_title('Refresh connected mice')
        refresh_row.set_subtitle('Scan for paired or reconnected MX Master mice')
        self.refresh_button = Gtk.Button.new_from_icon_name('view-refresh-symbolic')
        self.refresh_button.set_valign(Gtk.Align.CENTER)
        self.refresh_button.set_tooltip_text('Refresh connected mice')
        self.refresh_button.add_css_class('flat')
        self.refresh_button.connect('clicked', self._refresh_mice)
        refresh_row.add_suffix(self.refresh_button)
        refresh_row.set_activatable_widget(self.refresh_button)
        device_group.add(refresh_row)

        gesture_group = self._group(page, 'Touchpad gestures',
                                    'Native GNOME workspace and Overview swipes')
        self.fingers = Adw.ComboRow()
        self.fingers.set_title('Fingers')
        self.fingers.set_subtitle('Number of virtual fingers used for gestures')
        self.fingers.set_model(Gtk.StringList.new(['Three fingers', 'Four fingers']))
        gesture_group.add(self.fingers)
        self.gesture_speed = self._slider(
            gesture_group, 'Gesture speed', 'Distance traveled for each mouse movement',
            .25, 6.0, .05, 2)

        flick_group = self._group(page, 'Flick response',
                                  'Boost fast movements while retaining reversible control')
        self.flick_enabled = Adw.SwitchRow()
        self.flick_enabled.set_title('Flick boost')
        self.flick_enabled.set_subtitle('Accelerate quick gestures')
        flick_group.add(self.flick_enabled)
        self.boost = self._slider(flick_group, 'Flick strength',
                                  'Additional distance during fast movements',
                                  0, 2.0, .05, 2)
        self.threshold = self._slider(flick_group, 'Activation speed',
                                      'How quickly you must move to trigger a flick',
                                      150, 2000, 50, 0)
        self.flick_enabled.connect('notify::active', self._update_flick_controls)

        pointer_group = self._group(page, 'GNOME mouse pointer',
                                    'Applies to normal pointer movement throughout GNOME')
        self.pointer = self._slider(pointer_group, 'Pointer speed',
                                    'Uses the system mouse-speed preference',
                                    -1.0, 1.0, .05, 2)
        try:
            self.mouse_settings = Gio.Settings.new('org.gnome.desktop.peripherals.mouse')
            self.pointer.set_value(self.mouse_settings.get_double('speed'))
        except (GLib.Error, ValueError):
            self.pointer.set_sensitive(False)
            self.pointer_row.set_subtitle('GNOME mouse settings are unavailable')

        connection_group = self._group(page, 'Connection',
                                       'Manage the gesture service and Solaar integration')
        self.service_row = Adw.ActionRow()
        self.service_row.set_title('Gestures')
        self.service_row.set_subtitle('Checking service…')
        self.daemon_button = Gtk.Button(label='Start')
        self.daemon_button.set_valign(Gtk.Align.CENTER)
        self.daemon_button.connect('clicked', self._toggle_service)
        self.service_row.add_suffix(self.daemon_button)
        self.service_row.set_activatable_widget(self.daemon_button)
        connection_group.add(self.service_row)

        repair_row = Adw.ActionRow()
        repair_row.set_title('Solaar connection')
        repair_row.set_subtitle('Restore thumb-button diversion and reconnect the driver')
        self.repair_button = Gtk.Button(label='Repair')
        self.repair_button.set_valign(Gtk.Align.CENTER)
        self.repair_button.connect('clicked', self._repair)
        repair_row.add_suffix(self.repair_button)
        repair_row.set_activatable_widget(self.repair_button)
        connection_group.add(repair_row)

        self.status_row = Adw.ActionRow()
        self.status_row.set_title('Status')
        self.status_row.set_subtitle('Ready')
        self.status_row.set_subtitle_lines(3)
        connection_group.add(self.status_row)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        bottom.add_css_class('toolbar')
        bottom.set_margin_start(12)
        bottom.set_margin_end(12)
        bottom.set_margin_top(6)
        bottom.set_margin_bottom(6)
        self.reset_button = Gtk.Button(label='Restore Defaults')
        self.reset_button.connect('clicked', self._restore_defaults)
        bottom.append(self.reset_button)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        bottom.append(spacer)
        self.apply_button = Gtk.Button(label='Apply Changes')
        self.apply_button.add_css_class('suggested-action')
        self.apply_button.connect('clicked', self._apply)
        bottom.append(self.apply_button)
        toolbar.add_bottom_bar(bottom)

        self._load_values(read_settings())
        self._refresh_service()
        self.window.present()
        GLib.idle_add(self._refresh_mice)
        if needs_initial_setup() and not service_active():
            GLib.idle_add(self._begin_setup)

    @staticmethod
    def _group(page, title, description):
        group = Adw.PreferencesGroup()
        group.set_title(title)
        group.set_description(description)
        page.add(group)
        return group

    def _slider(self, group, title, description, minimum, maximum, step, digits):
        row = Adw.ActionRow()
        row.set_title(title)
        row.set_subtitle(description)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, minimum,
                                          maximum, step)
        scale.set_digits(digits)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.set_size_request(190, -1)
        scale.set_valign(Gtk.Align.CENTER)
        scale.set_tooltip_text(description)
        row.add_suffix(scale)
        group.add(row)
        if title == 'Pointer speed':
            self.pointer_row = row
        return scale

    def _notice(self, message, error=False):
        # Keep failures visible; ephemeral toasts are only for success messages.
        self.status_row.set_subtitle(message[:280])
        if not error:
            self.toasts.add_toast(Adw.Toast.new(message[:140]))

    def _load_values(self, settings):
        self.fingers.set_selected(settings.fingers - 3)
        self.gesture_speed.set_value(settings.sensitivity)
        self.flick_enabled.set_active(settings.flick_enabled)
        self.boost.set_value(settings.flick_boost)
        self.threshold.set_value(settings.flick_threshold)
        self._update_flick_controls()

    def _update_flick_controls(self, *_args):
        active = self.flick_enabled.get_active()
        self.boost.set_sensitive(active)
        self.threshold.set_sensitive(active)

    def _restore_defaults(self, *_args):
        self._load_values(GestureSettings())
        if self.mouse_settings:
            self.pointer.set_value(0.0)
        self.status_row.set_subtitle('Defaults selected; select Apply Changes to save')

    def _refresh_service(self):
        active = service_active()
        self.daemon_button.set_label('Stop' if active else 'Start')
        self.service_row.set_subtitle('Running' if active else 'Stopped')

    def _refresh_mice(self, *_args):
        if self._device_refreshing:
            return False
        self._device_refreshing = True
        self.refresh_button.set_sensitive(False)
        current_selection = self._selected_mouse_serial()

        def worker():
            try:
                mice, error = list_mice(), ''
            except (OSError, RuntimeError) as exc:
                mice, error = [], str(exc)
            GLib.idle_add(self._mice_refreshed, mice, error, current_selection)

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _mice_refreshed(self, mice, error, current_selection):
        self._device_refreshing = False
        self.refresh_button.set_sensitive(True)
        self._mice = mice
        choices = (['Select a mouse…'] + [m.label for m in mice]
                   if mice else ['No connected MX Master'])
        self.mouse_choice.set_model(Gtk.StringList.new(choices))
        self.mouse_choice.set_sensitive(bool(mice))
        preferred = current_selection or selected_serial()
        index = next((i + 1 for i, mouse in enumerate(mice)
                      if mouse.serial == preferred), 0)
        if not preferred and len(mice) == 1:
            index = 1
        self.mouse_choice.set_selected(index)
        if error:
            self._notice('Mouse discovery: ' + error[:180], error=True)
        elif not mice:
            self.status_row.set_subtitle('No MX Master found; check Solaar and refresh')
        return False

    def _selected_mouse_serial(self):
        index = self.mouse_choice.get_selected()
        return self._mice[index - 1].serial if 0 < index <= len(self._mice) else None

    def _run_async(self, work, busy_message):
        if self._setup_busy:
            return False
        self._setup_busy = True
        self.daemon_button.set_sensitive(False)
        self.repair_button.set_sensitive(False)
        self.apply_button.set_sensitive(False)
        self.status_row.set_subtitle(busy_message)
        self.hold()

        def worker():
            try:
                message = work()
                failure = False
            except (OSError, RuntimeError) as exc:
                message = 'Connection failed: ' + str(exc)
                failure = True
            GLib.idle_add(self._async_finished, message, failure)

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _async_finished(self, message, failure):
        self._setup_busy = False
        self.daemon_button.set_sensitive(True)
        self.repair_button.set_sensitive(True)
        self.apply_button.set_sensitive(True)
        self._notice(message, error=failure)
        self._refresh_service()
        self.release()
        return False

    def _repair(self, *_args):
        self._begin_setup()

    def _begin_setup(self):
        serial = self._selected_mouse_serial()
        if self._mice and not serial and len(self._mice) > 1:
            self._notice('Select a mouse before starting gestures', error=True)
            return False
        return self._run_async(lambda: setup_and_start(serial),
                               'Connecting Solaar and starting gestures…')

    def _toggle_service(self, *_args):
        if not service_active():
            self._begin_setup()
        else:
            self._run_async(lambda: (stop_gestures() or 'Gestures stopped'),
                            'Stopping gestures…')

    def _apply(self, *_args):
        if self._setup_busy:
            return
        settings = GestureSettings(
            sensitivity=round(self.gesture_speed.get_value(), 2),
            fingers=3 + self.fingers.get_selected(),
            flick_enabled=self.flick_enabled.get_active(),
            flick_boost=round(self.boost.get_value(), 2),
            flick_threshold=round(self.threshold.get_value()),
        )
        try:
            write_settings(settings)
            selected = self._selected_mouse_serial()
            new_device = bool(selected and selected != selected_serial())
            if new_device:
                save_selection(selected)
            if self.mouse_settings:
                pointer = self.pointer.get_value()
                if abs(self.mouse_settings.get_double('speed') - pointer) >= .005:
                    self.mouse_settings.set_double('speed', pointer)
            if service_active():
                if new_device:
                    self._begin_setup()
                else:
                    self._run_async(
                        lambda: (service_action('restart') or 'Settings applied'),
                        'Restarting gestures…')
            else:
                self._notice('Preferences saved; start gestures to apply them')
        except (OSError, ValueError, RuntimeError, GLib.Error) as exc:
            self._notice('Could not save preferences: ' + str(exc), error=True)
        self._refresh_service()


def main():
    return Preferences().run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
