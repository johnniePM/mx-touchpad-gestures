"""Per-user automatic setup entrypoints for the GNOME interface.

License: AGPL-3.0-only.
"""
from mxmaster3_gesture_device import DeviceError as SetupError
from mxmaster3_gesture_device import selected_serial, start_gestures, stop_gestures


def needs_initial_setup():
    return selected_serial() is None


def setup_and_start(serial=None):
    return start_gestures(serial)
