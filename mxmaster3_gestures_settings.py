#!/usr/bin/env python3
"""Native GNOME/GTK 4 preferences for MX Touchpad Gestures.

License: AGPL-3.0-only.
"""

import subprocess
import sys
import threading

# Shared configuration lives with package data; source checkouts import locally.
if __file__.startswith('/usr/bin/'):
    sys.path.insert(0, '/usr/lib/mx-touchpad-gestures')
from mxmaster3_gesture_config import GestureSettings, read_settings, write_settings
from mxmaster3_gesture_setup import setup_and_start, needs_initial_setup

try:
    import gi
    gi.require_version('Gtk', '4.0')
    from gi.repository import Gio, Gtk, GLib
except (ImportError, ValueError) as exc:
    sys.exit(f'MX Touchpad Gestures Settings requires python-gobject and gtk4: {exc}')

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


class Preferences(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='io.github.johnniePM.MXTouchpadGestures.Settings',
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None
        self.mouse_settings = None
        self._setup_busy = False

    def do_activate(self):
        if self.window is not None:
            self.window.present()
            return
        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title('MX Touchpad Gestures')
        self.window.set_default_size(680, 720)
        self.window.set_size_request(440, 520)
        header = Gtk.HeaderBar()
        self.window.set_titlebar(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.window.set_child(outer)
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        outer.append(scroll)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        page.set_margin_top(28)
        page.set_margin_bottom(28)
        page.set_margin_start(28)
        page.set_margin_end(28)
        scroll.set_child(page)

        self._text(page, 'Make your mouse feel like a touchpad', 'title-1')
        self._text(page, 'Hold the Logitech gesture button and move the mouse. '
                   'Your regular pointer stays unchanged outside gesture mode.', 'dim-label')

        gestures = self._section(page, 'Touchpad gesture',
                                 'These settings affect GNOME workspace and Overview swipes.')
        self.fingers = Gtk.DropDown.new_from_strings(['Three fingers', 'Four fingers'])
        self._row(gestures, 'Gesture fingers',
                  'The number of virtual fingers GNOME receives during a swipe.', self.fingers)
        self.gesture_speed = self._scale(0.25, 6.0, 0.05, 2)
        self._row(gestures, 'Gesture speed',
                  'How far a workspace swipe travels for each mouse movement.', self.gesture_speed,
                  expand_control=True)

        flick = self._section(page, 'Flick response',
                              'Quick movements can cover more distance. GNOME still controls '
                              'the release animation; there is no artificial movement afterward.')
        self.flick_enabled = Gtk.Switch()
        self._row(flick, 'Enable flick boost',
                  'Accelerate quick movements; slow and reversible gestures stay precise.',
                  self.flick_enabled)
        self.boost = self._scale(0, 2.0, 0.05, 2)
        self._row(flick, 'Flick strength',
                  'Extra distance for fast movement, from none to 200%.', self.boost, True)
        self.threshold = self._scale(150, 2000, 50, 0)
        self._row(flick, 'Flick activation speed',
                  'Lower values make even shorter, quicker movements count as a flick.',
                  self.threshold, True)
        self.flick_enabled.connect('notify::active', self._update_flick_controls)

        pointer = self._section(page, 'GNOME mouse pointer',
                                'This controls the normal mouse pointer across GNOME applications, '
                                'not just during gestures.')
        self.pointer = self._scale(-1.0, 1.0, 0.05, 2)
        self._row(pointer, 'Pointer speed',
                  'Uses GNOME’s own system mouse-speed setting.', self.pointer, True)
        try:
            self.mouse_settings = Gio.Settings.new('org.gnome.desktop.peripherals.mouse')
            self.pointer.set_value(self.mouse_settings.get_double('speed'))
        except (GLib.Error, ValueError):
            self.pointer.set_sensitive(False)
            self._text(pointer, 'GNOME mouse settings are unavailable in this session.', 'dim-label')

        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        footer.set_margin_start(26)
        footer.set_margin_end(26)
        footer.set_margin_top(12)
        footer.set_margin_bottom(22)
        outer.append(Gtk.Separator())
        outer.append(footer)
        self.status = Gtk.Label(label='')
        self.status.set_xalign(0)
        self.status.set_wrap(True)
        footer.append(self.status)
        self.repair_button = Gtk.Button(label='Repair Solaar connection')
        self.repair_button.set_tooltip_text('Reinstall the button rules, set diversion and start the driver')
        self.repair_button.connect('clicked', self._repair)
        footer.append(self.repair_button)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        footer.append(actions)
        self.daemon_button = Gtk.Button(label='')
        self.daemon_button.connect('clicked', self._toggle_service)
        actions.append(self.daemon_button)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        actions.append(spacer)
        reset = Gtk.Button(label='Restore defaults')
        reset.connect('clicked', self._restore_defaults)
        actions.append(reset)
        apply = Gtk.Button(label='Save and apply')
        apply.add_css_class('suggested-action')
        apply.connect('clicked', self._apply)
        actions.append(apply)

        self._load_values(read_settings())
        self._refresh_service()
        self.window.present()
        # On first launch, configure and start automatically in the user session.
        if needs_initial_setup() and not service_active():
            GLib.idle_add(self._begin_setup)

    @staticmethod
    def _text(container, value, style=None):
        label = Gtk.Label(label=value, xalign=0)
        label.set_wrap(True)
        if style:
            label.add_css_class(style)
        container.append(label)
        return label

    def _section(self, page, title, subtitle):
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.append(group)
        self._text(group, title, 'heading')
        self._text(group, subtitle, 'dim-label')
        frame = Gtk.Frame()
        frame.set_child(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1))
        group.append(frame)
        return frame.get_child()

    def _row(self, group, title, description, control, expand_control=False):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row.set_margin_start(16)
        row.set_margin_end(16)
        row.set_margin_top(13)
        row.set_margin_bottom(13)
        group.append(row)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        labels.set_hexpand(not expand_control)
        row.append(labels)
        label = self._text(labels, title)
        label.add_css_class('body')
        subtitle = self._text(labels, description, 'dim-label')
        subtitle.add_css_class('caption')
        if expand_control:
            control.set_hexpand(True)
            control.set_size_request(210, -1)
        else:
            control.set_valign(Gtk.Align.CENTER)
        row.append(control)
        control.set_tooltip_text(description)
        group.append(Gtk.Separator())

    @staticmethod
    def _scale(low, high, step, digits):
        slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
        slider.set_digits(digits)
        slider.set_draw_value(True)
        slider.set_value_pos(Gtk.PositionType.RIGHT)
        return slider

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
        self.status.set_text('Defaults selected. Select Save and apply to keep them.')

    def _refresh_service(self):
        self.daemon_button.set_label('Stop gestures' if service_active() else 'Start gestures')

    def _repair(self, *_args):
        self._begin_setup()

    def _begin_setup(self):
        if self._setup_busy:
            return False
        self._setup_busy = True
        self.daemon_button.set_sensitive(False)
        self.repair_button.set_sensitive(False)
        self.status.set_text('Connecting Solaar and starting gestures…')
        self.hold()

        def worker():
            try:
                message = setup_and_start()
            except (OSError, RuntimeError) as exc:
                message = 'Connection setup failed: ' + str(exc)
            GLib.idle_add(self._setup_finished, message)

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _setup_finished(self, message):
        self._setup_busy = False
        self.daemon_button.set_sensitive(True)
        self.repair_button.set_sensitive(True)
        self.status.set_text(message)
        self._refresh_service()
        self.release()
        return False

    def _toggle_service(self, *_args):
        if not service_active():
            self._begin_setup()
            return
        try:
            service_action('stop')
            self.status.set_text('Gestures stopped.')
        except RuntimeError as exc:
            self.status.set_text(str(exc))
        self._refresh_service()

    def _apply(self, *_args):
        settings = GestureSettings(
            sensitivity=round(self.gesture_speed.get_value(), 2),
            fingers=3 + self.fingers.get_selected(),
            flick_enabled=self.flick_enabled.get_active(),
            flick_boost=round(self.boost.get_value(), 2),
            flick_threshold=round(self.threshold.get_value()),
        )
        try:
            write_settings(settings)
            if self.mouse_settings:
                new_pointer = self.pointer.get_value()
                if abs(self.mouse_settings.get_double('speed') - new_pointer) >= 0.005:
                    self.mouse_settings.set_double('speed', new_pointer)
            if service_active():
                service_action('restart')
                self.status.set_text('Settings saved and gestures restarted.')
            else:
                self.status.set_text('Settings saved. Start gestures to use them.')
        except (OSError, ValueError, RuntimeError, GLib.Error) as exc:
            self.status.set_text('Could not apply settings: ' + str(exc))
        self._refresh_service()


def main():
    return Preferences().run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
