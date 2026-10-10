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
    serial: str

    @property
    def label(self):
        return f'{self.name}  ·  {self.serial}'


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


def parse_mice(output):
    """Parse Solaar's show output, handling receiver and Bluetooth device blocks."""
    blocks, current = [], None
    for line in output.splitlines():
        numbered = re.match(r'^\s{2,}\d+:\s+(.+?)\s*$', line)
        bare = re.match(r'^(?:Wireless Mouse )?MX Master 3S?(?: Wireless Mouse)?\s*$', line)
        if numbered or bare:
            if current:
                blocks.append(current)
            current = {'name': numbered.group(1) if numbered else line.strip(),
                       'serial': '', 'offline': False, 'kind': None}
            continue
        if current is None:
            continue
        if 'Device is offline.' in line:
            current['offline'] = True
        serial = re.match(r'^\s+Serial number\s*:\s*(\S+)', line)
        if serial:
            current['serial'] = serial.group(1)
        kind = re.match(r'^\s+Kind\s*:\s*(\S+)', line)
        if kind:
            current['kind'] = kind.group(1)
    if current:
        blocks.append(current)
    found, seen = [], set()
    for item in blocks:
        name, serial = item['name'], item['serial']
        if not re.search(r'\bMX Master 3S?\b', name, re.I) or item['offline']:
            continue
        if item['kind'] not in (None, 'mouse') or not re.fullmatch(r'[A-Za-z0-9:_-]{4,64}', serial):
            continue
        if serial not in seen:
            found.append(Mouse(name, serial))
            seen.add(serial)
    return found


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
        if match:
            return match
        raise DeviceError('Selected MX Master is disconnected. Reconnect it or choose a new mouse.')
    if not mice:
        raise DeviceError('No connected MX Master 3/3S detected by Solaar.')
    if len(mice) > 1:
        raise DeviceError('Multiple mice detected. Choose one in MX Touchpad Gestures Settings.')
    return mice[0]


def diverted(mouse):
    output = check(run(['solaar', 'config', mouse.serial, 'divert-keys', CONTROL]),
                   'Check thumb-button diversion')
    for line in output.splitlines():
        if re.match(r'^divert-keys\s', line):
            return bool(re.search(r'\bdiverted\b', line, re.I))
    raise DeviceError('Solaar could not report the gesture button setting.')


def set_diversion(mouse):
    if diverted(mouse):
        return False
    # Ordinal 2 means Diverted regardless of UI language. Only key 195 is changed.
    check(run(['solaar', 'config', mouse.serial, 'divert-keys', CONTROL, DIVERTED],
              timeout=15), 'Divert thumb button')
    if not diverted(mouse):
        raise DeviceError('Solaar did not confirm the gesture button is Diverted.')
    return True


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
