"""Validated, per-user settings shared by the daemon and GTK preferences UI.

License: AGPL-3.0-only.
"""

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import tempfile

CONFIG_FILE = Path.home() / '.config' / 'mxmaster3-gestures.conf'
START = '# BEGIN MX Touchpad Gestures preferences'
END = '# END MX Touchpad Gestures preferences'
KEYS = ('MXG_SENSITIVITY', 'MXG_FINGERS', 'MXG_FLICK_ENABLED',
        'MXG_FLICK_BOOST', 'MXG_FLICK_THRESHOLD')


@dataclass(frozen=True)
class GestureSettings:
    sensitivity: float = 2.0
    fingers: int = 3
    flick_enabled: bool = False
    flick_boost: float = 0.7
    flick_threshold: float = 600.0  # raw relative device counts per second


def _float(value, default, minimum, maximum):
    try:
        parsed = float(value)
        if math.isfinite(parsed) and minimum <= parsed <= maximum:
            return parsed
    except (TypeError, ValueError):
        pass
    return default


def _parse(lines):
    result = {}
    for line in lines.splitlines():
        m = re.fullmatch(r'\s*(MXG_[A-Z_]+)\s*=\s*([\w.+-]+)\s*', line)
        if m:
            result[m[1]] = m[2]
    return result


def read_settings(path=None, env=None):
    """Read settings from the user's config, then explicit environment overrides.

    User config is also parsed without systemd, for --test-swipe and CLI runs.
    """
    path = CONFIG_FILE if path is None else Path(path)
    values = {}
    try:
        values.update(_parse(path.read_text(encoding='utf-8')))
    except FileNotFoundError:
        pass
    for key in KEYS:
        if (env if env is not None else os.environ).get(key) is not None:
            values[key] = (env if env is not None else os.environ)[key]
    fingers = str(values.get('MXG_FINGERS', '3'))
    enabled = str(values.get('MXG_FLICK_ENABLED', '0')).lower()
    return GestureSettings(
        sensitivity=_float(values.get('MXG_SENSITIVITY'), 2.0, 0.25, 6.0),
        fingers=int(fingers) if fingers in ('3', '4') else 3,
        flick_enabled=enabled in ('1', 'true', 'yes', 'on'),
        flick_boost=_float(values.get('MXG_FLICK_BOOST'), 0.7, 0.0, 2.0),
        flick_threshold=_float(values.get('MXG_FLICK_THRESHOLD'), 600.0, 150.0, 2000.0),
    )


def write_settings(settings, path=None):
    """Atomically replace only this app's keys, retaining unrelated user lines."""
    path = CONFIG_FILE if path is None else Path(path)
    if not isinstance(settings, GestureSettings):
        raise TypeError('settings must be GestureSettings')
    if not (0.25 <= settings.sensitivity <= 6.0 and settings.fingers in (3, 4)
            and isinstance(settings.flick_enabled, bool)
            and 0 <= settings.flick_boost <= 2.0
            and 150 <= settings.flick_threshold <= 2000
            and all(map(math.isfinite, (settings.sensitivity, settings.flick_boost,
                                        settings.flick_threshold)))):
        raise ValueError('Settings outside supported range')
    try:
        original = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        original = ''
    # Strip any old managed block and scattered versions of known variables.
    if START in original or END in original:
        if original.count(START) != 1 or original.count(END) != 1 or original.index(START) >= original.index(END):
            raise ValueError('Malformed managed configuration block; refusing to overwrite')
        a = original.index(START)
        b = original.index(END, a) + len(END)
        original = original[:a] + original[b:]
    others = [line for line in original.splitlines()
              if not re.match(r'^\s*(?:' + '|'.join(KEYS) + r')\s*=', line)]
    block = '\n'.join((START,
                       f'MXG_SENSITIVITY={settings.sensitivity:.2f}',
                       f'MXG_FINGERS={settings.fingers}',
                       f'MXG_FLICK_ENABLED={int(settings.flick_enabled)}',
                       f'MXG_FLICK_BOOST={settings.flick_boost:.2f}',
                       f'MXG_FLICK_THRESHOLD={settings.flick_threshold:.0f}',
                       END))
    result = ('\n'.join(others).strip('\n') + '\n\n' if any(x.strip() for x in others) else '') + block + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.mxmaster3-gestures-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(result)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
