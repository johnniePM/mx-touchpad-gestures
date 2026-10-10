"""Manage per-device Solaar gesture diversion without touching other mouse settings.

License: AGPL-3.0-only.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

SELECTION = Path.home() / '.config' / 'mx-touchpad-gestures' / 'device.json'
SERVICE = 'mxmaster3-gestures.service'
WATCH = 'mxmaster3-gestures-watch.service'
CONTROL = '195'             # HID++ Mouse Gesture Button, 0x00C3
DIVERTED = '2'              # Solaar CLI choice ordinal (not underlying value 1)


class DeviceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Mouse:
    name: str
    serial: str  # Stable device identity: real serial, or Unit ID if serial is absent.
    unit_only: bool = False

    @property
    def label(self):
        return f'{self.name}  ·  {("Unit ID" if self.unit_only else "Serial")} {self.serial}'

    @property
    def cli_selector(self):
        # Solaar CLI looks up dev.serial or a substring of dev.name, NOT dev.unitId.
        # For serial-less HID++ mice address the device by its full reported name.
        return self.name if self.unit_only else self.serial


def run(args, timeout=12):
    try:
        # Solaar output is localized. C locale makes CLI choices and discovery
        # predictable without modifying the user's GNOME language settings.
        env = {**os.environ, 'LC_ALL': 'C'} if args[0] == 'solaar' else None
        return subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                              check=False, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeviceError(f'Cannot execute {args[0]}: {exc}') from exc


def check(result, operation):
    if result.returncode == 0:
        return result.stdout
    lines = [(line.strip()) for line in (result.stderr + '\n' + result.stdout).splitlines()
             if line.strip() and 'rules cannot access modifier keys in Wayland' not in line
             and 'accessing process only works on GNOME with Solaar Gnom' not in line]
    detail = next((line for line in reversed(lines) if not line.startswith('Traceback')), 'Command failed')
    raise DeviceError(f'{operation}: {detail[:180]}')


# Match only device section headings. Feature listings also have "1:" lines,
# and must NOT be mistaken for a new device (the former parser did exactly that).
MOUSE_NAME = r'(?:MX Master 3S?(?: Wireless Mouse)?|Wireless Mouse MX Master 3S?)'
DEVICE_HEADING = re.compile(r'^\s*(?:\d+:\s+)?('+MOUSE_NAME+r')\s*$', re.I)
NUMBERED_HEADING = re.compile(r'^(\s+)\d+:\s+(\S.*)$')
DEVICE_ID = re.compile(r'^[A-Za-z0-9:_-]{4,64}$')


def parse_mice(output):
    """Parse receiver and direct-device Solaar show blocks.

    Some MX Master 3/3S devices (including Bluetooth) have a blank
    "Serial number" but provide a stable "Unit ID". Solaar show also
    emits numbered HID++ feature lines, which are not new devices.
    """
    matches, current, heading_indent = [], None, 0

    def finish():
        if current is None or current['offline'] or current['kind'] not in (None, 'mouse'):
            return
        serial = current['serial'] or current['unit_id']
        if not DEVICE_ID.fullmatch(serial):
            return
        if serial not in {m.serial for m in matches}:
            matches.append(Mouse(current['name'], serial,
                                 unit_only=not bool(current['serial'])))

    for line in output.splitlines():
        heading = DEVICE_HEADING.fullmatch(line)
        if heading:
            finish()
            current = {'name': heading.group(1), 'serial': '',
                       'unit_id': '', 'offline': False, 'kind': None}
            heading_indent = len(line) - len(line.lstrip())
            continue

        # Stop at the next numbered device in the same list; ignore
        # lower-level firmware/feature indices embedded in the device block.
        numbered = NUMBERED_HEADING.match(line)
        if (numbered and current is not None
                and len(numbered.group(1)) <= heading_indent):
            finish()
            current = None
            continue

        if current is None:
            continue
        if 'Device is offline.' in line:
            current['offline'] = True

        serial = re.match(r'^\s+Serial number\s*:\s*(\S*)\s*$', line)
        if serial:
            current['serial'] = serial.group(1)

        # Require end-of-line so nested firmware "Unit ID: ... Model ID:"
        # details cannot overwrite the top-level identity.
        unit = re.match(r'^\s+Unit ID\s*:\s*([A-Za-z0-9:_-]+)\s*$', line)
        if unit:
            current['unit_id'] = unit.group(1)

        kind = re.match(r'^\s+Kind\s*:\s*(\w+)\s*$', line)
        if kind:
            current['kind'] = kind.group(1).lower()

    finish()
    return matches

def list_mice():
    if not shutil.which('solaar'):
        raise DeviceError('Solaar is not installed.')
    return parse_mice(check(run(['solaar', 'show'], timeout=15), 'Find connected mice'))


def selected_serial(path=None):
    path = SELECTION if path is None else Path(path)
    try:
        obj = json.loads(path.read_text(encoding='utf8'))
        value = obj.get('serial')
        return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9:_-]{4,64}', value) else None
    except (OSError, ValueError, AttributeError):
        return None


def save_selection(serial, path=None):
    if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{4,64}', serial):
        raise DeviceError('Invalid mouse serial number')
    path = SELECTION if path is None else Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.device-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf8') as f:
            json.dump({'serial': serial}, f)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def choose_mouse(mice, serial=None):
    selected = serial if serial is not None else selected_serial()
    if selected:
        match = next((m for m in mice if m.serial == selected), None)
        if not match:
            raise DeviceError('Selected MX Master is disconnected. Reconnect it or choose a new mouse.')
    elif not mice:
        raise DeviceError('No connected MX Master 3/3S detected by Solaar.')
    elif len(mice) > 1:
        raise DeviceError('Multiple mice detected. Choose one in MX Touchpad Gestures Settings.')
    else:
        match = mice[0]
    if match.unit_only and sum(m.name.casefold() == match.name.casefold()
                               for m in mice) > 1:
        raise DeviceError('Several identical MX Masters have no serial numbers. '
                          'Solaar CLI cannot uniquely select them by Unit ID; '
                          'unpair or disconnect the other mouse before configuring.')
    return match


def diverted(mouse):
    # Solaar CLI's "divert-keys 195" read path reports "(key not found)"
    # even for a valid 195: it compares the argument string to integer
    # map keys. Read the complete map instead (supported CLI read path).
    output = check(run(['solaar', 'config', mouse.cli_selector, 'divert-keys']),
                   'Check thumb-button diversion')
    setting = re.search(r'^\s*divert-keys\s*=\s*\{([^}]+)\}', output, re.M)
    if not setting:
        raise DeviceError('Solaar did not return the diversion settings for this mouse.')
    entries = [part.strip().split(':', 1) for part in setting.group(1).split(',')]
    value = next((parts[1].strip() for parts in entries if len(parts) == 2
                  and parts[0].strip().casefold() in ('mouse gesture button', '195')), None)
    if value is None:
        raise DeviceError('This mouse does not report Mouse Gesture Button in Solaar.')
    if value.casefold() not in ('regular', 'diverted', 'mouse gestures', 'sliding dpi'):
        raise DeviceError('Solaar reported an unknown gesture-button mode: ' + value[:40])
    return value.casefold() == 'diverted'


def set_diversion(mouse):
    if diverted(mouse):
        return False
    # With three possible values the second CLI choice is "Diverted".
    # Unlike the HID++ raw value, the Solaar command uses choice ordinal 2.
    check(run(['solaar', 'config', mouse.cli_selector, 'divert-keys', CONTROL, DIVERTED],
              timeout=15), 'Divert thumb button')
    # Give the active Solaar instance time to update its setting cache.
    for attempt in range(3):
        if diverted(mouse):
            return True
        if attempt < 2:
            time.sleep(0.25)
    raise DeviceError('Solaar did not confirm Mouse Gesture Button is Diverted.')

def solaar_running():
    return run(['pgrep', '-x', '-u', str(os.getuid()), 'solaar'], 3).returncode == 0


def launch_solaar():
    try:
        subprocess.Popen(['solaar', '--window=hide'], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as exc:
        raise DeviceError(f'Solaar could not start: {exc}') from exc
    for _ in range(20):
        if solaar_running():
            return
        time.sleep(.1)
    raise DeviceError('Solaar did not start.')


def restart_solaar():
    if solaar_running():
        run(['pkill', '-TERM', '-x', '-u', str(os.getuid()), 'solaar'], 4)
        for _ in range(30):
            if not solaar_running():
                break
            time.sleep(.1)
        if solaar_running():
            raise DeviceError('Solaar is still running; quit it and retry.')
    launch_solaar()


def install_rules():
    output = check(run(['/usr/bin/mxmaster3-solaar-bridge', 'install']),
                   'Install gesture-button rules')
    return 'rules installed' in output.lower()


def start_gestures(serial=None):
    if not solaar_running():
        launch_solaar()
    mouse = choose_mouse(list_mice(), serial)
    if install_rules():
        restart_solaar()
    set_diversion(mouse)
    if selected_serial() != mouse.serial:
        save_selection(mouse.serial)
    check(run(['systemctl', '--user', 'start', SERVICE], 20), 'Start gesture driver')
    check(run(['systemctl', '--user', 'start', WATCH], 20), 'Start reconnect monitor')
    return f'Gestures running with {mouse.label}.'


def stop_gestures():
    for name in (WATCH, SERVICE):
        check(run(['systemctl', '--user', 'stop', name], 15), 'Stop gestures')


def monitor(interval=12):
    """Reassert selected thumb diversion after a reconnect without starting gestures."""
    while True:
        try:
            mouse = choose_mouse(list_mice())
            set_diversion(mouse)
            # The watch service runs only while gestures were deliberately
            # started. Recover the input daemon if it exited during unplug.
            if run(['systemctl', '--user', 'is-active', '--quiet', SERVICE], 4).returncode != 0:
                check(run(['systemctl', '--user', 'start', SERVICE], 20),
                      'Restart gesture driver after reconnect')
        except DeviceError:
            pass  # Mouse may be asleep, unplugged, or Solaar may be reconnecting.
        time.sleep(interval)


if __name__ == '__main__':
    monitor()
