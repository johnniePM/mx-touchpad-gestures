#!/usr/bin/env python3
"""Safely add/remove two narrowly scoped Solaar mouse-button bridge rules."""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from datetime import datetime

START = '# BEGIN MXMASTER3-GNOME-NATIVE-GESTURES BRIDGE\n'
END = '# END MXMASTER3-GNOME-NATIVE-GESTURES BRIDGE\n'
RULES_PATH = Path.home() / '.config' / 'solaar' / 'rules.yaml'
DRIVER_PATH = Path('/usr/bin/mxmaster3-gestures')
FAST_HELPER_PATH = Path('/usr/bin/mxmaster3-gesture-signal')


def bridge_rule_block(driver_path, fast_helper=None):
    """Prefer the native messenger to avoid a new Python startup on every press."""
    script = str(driver_path)
    fast_helper = FAST_HELPER_PATH if fast_helper is None else fast_helper
    use_fast = fast_helper.is_file() and os.access(fast_helper, os.X_OK)
    result = START
    for action in ('press', 'release'):
        args = [str(fast_helper), action] if use_fast else ['/usr/bin/python3', script, '--solaar', action]
        yaml_args = ', '.join(json.dumps(x) for x in args)
        result += f'---\n- Key: [Mouse Gesture Button, {"pressed" if action == "press" else "released"}]\n- Execute: [{yaml_args}]\n...\n'
    return result + END


def clean_rules(data):
    if START not in data and END not in data:
        return data, False
    if data.count(START) != 1 or data.count(END) != 1:
        raise RuntimeError('Unexpected bridge marker count; refusing to modify Solaar rules')
    a = data.index(START)
    b = data.index(END, a) + len(END)
    return data[:a] + data[b:], True


def update(path, action, driver_path=DRIVER_PATH):
    contents = path.read_text(encoding='utf-8') if path.exists() else ''
    contents, changed = clean_rules(contents)
    if action == 'install':
        # Prefix bridge rules: Solaar stops processing when Execute action runs,
        # preventing older F24 rules from firing for the same diverted key.
        result = bridge_rule_block(driver_path) + contents
        if path.exists() and result == path.read_text(encoding="utf-8"):
            return False
    else:
        if not changed:
            return False
        result = contents
    if path.exists():
        backup = path.with_name(path.name + '.mxmaster3-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        shutil.copy2(path, backup)
        print('Backed up existing Solaar rules:', backup)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.mxmaster3-tmp-' + str(os.getpid()))
    try:
        temp.write_text(result, encoding='utf-8')
        if path.exists():
            os.chmod(temp, path.stat().st_mode & 0o777)
        else:
            os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('operation', choices=['install', 'remove'])
    args = ap.parse_args()
    if args.operation == 'install' and not DRIVER_PATH.is_file():
        print('Install the Arch package first: makepkg -si', file=sys.stderr)
        return 1
    try:
        changed = update(RULES_PATH, args.operation)
    except (OSError, RuntimeError) as exc:
        print('Solaar bridge installation failed:', exc, file=sys.stderr)
        return 1
    print('Solaar bridge rules', 'installed' if changed and args.operation == 'install' else 'up to date' if args.operation == 'install' else 'removed' if changed else 'already absent')
    if args.operation == 'install':
        print('IMPORTANT: In Solaar > MX Master 3 > Key/Button Diversion:')
        print('  Mouse Gesture Button => Diverted  (NOT Mouse Gestures or Regular).')
        print('Quit and restart Solaar to reload rules. Then start the MX Master 3 Gestures GNOME launcher.')
        print('Bridge:', 'native low-latency helper' if FAST_HELPER_PATH.is_file() else 'Python fallback')
    return 0


if __name__ == '__main__':
    sys.exit(main())
