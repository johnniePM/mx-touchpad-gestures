"""Per-user Solaar and gesture-service provisioning.

Runs on application launch, not from pacman hooks or the daemon.
License: AGPL-3.0-only.
"""
import os
from pathlib import Path
import shutil
import subprocess
import time

SERVICE = 'mxmaster3-gestures.service'
BRIDGE = '/usr/bin/mxmaster3-solaar-bridge'
MARKER = Path.home() / '.config' / 'mx-touchpad-gestures' / 'integration-ready'


class SetupError(RuntimeError):
    pass


def _run(args, timeout=12):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError(f'Cannot run {args[0]}: {exc}') from exc


def _checked(args, timeout=12):
    result = _run(args, timeout)
    if result.returncode:
        raise SetupError(f'{args[0]}: {(result.stderr or result.stdout or "Command failed").strip()[:300]}')
    return result


def solaar_running():
    return _run(['pgrep', '-u', str(os.getuid()), '-x', 'solaar'], 3).returncode == 0


def restart_solaar():
    if solaar_running():
        _run(['pkill', '-u', str(os.getuid()), '-TERM', '-x', 'solaar'], 4)
        for _ in range(30):
            if not solaar_running():
                break
            time.sleep(0.1)
        if solaar_running():
            raise SetupError('Solaar did not exit; quit it using its menu and retry.')
    try:
        subprocess.Popen(['solaar', '--window=hide'], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise SetupError(f'Could not start Solaar: {exc}') from exc
    for _ in range(20):
        if solaar_running():
            return
        time.sleep(0.1)
    raise SetupError('Solaar did not start. Check its status in the Solaar application.')


def configure_solaar():
    """Add only our marked rules, reload if necessary, and divert the thumb."""
    if not shutil.which('solaar'):
        return False  # Mice exposing BTN_TASK in evdev can work without Solaar.
    result = _checked([BRIDGE, 'install'])
    rules_changed = 'Solaar bridge rules installed' in result.stdout
    if rules_changed or not solaar_running():
        restart_solaar()
    errors = []
    for device in ('MX Master 3', 'MX Master 3S'):
        for attempt in range(3):
            result = _run(['solaar', 'config', device, 'divert-keys',
                           'Mouse Gesture Button', 'Diverted'])
            if result.returncode == 0:
                return True
            errors.append((result.stderr or result.stdout or '').strip()[:100])
            if attempt != 2:
                time.sleep(0.35)
    raise SetupError('Solaar cannot divert the thumb button. Confirm the MX Master '
                     'is connected, or set Mouse Gesture Button to Diverted in Solaar, '
                     'then select Repair connection. ' + '; '.join(x for x in errors if x))


def service_action(action):
    if action not in ('start', 'stop', 'restart'):
        raise ValueError('Invalid gesture service action')
    _checked(['systemctl', '--user', action, SERVICE], 20)


def setup_and_start():
    """Configure before starting; report errors instead of falsely claiming success."""
    solaar_connected = configure_solaar()
    service_action('start')
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.touch(mode=0o600, exist_ok=True)
    return ('Solaar connected. Gestures are running.' if solaar_connected else
            'Gestures started using direct input. Install Solaar if the thumb button is not detected.')


def needs_initial_setup():
    return not MARKER.exists()
