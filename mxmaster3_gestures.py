#!/usr/bin/env python3
"""MX Master 3/3S -> native GNOME three-finger gestures (Wayland).

Hold the thumb gesture button (BTN_TASK, KEY_PROG3 or remapped F24) and move.
The normal physical mouse remains kernel-controlled; only during a gesture is
its REL_X/REL_Y event node temporarily EVIOCGRAB'ed. The virtual touchpad is
an isolated type-B multitouch device, not a keyboard-shortcut emulator.

License: AGPL-3.0-only. The gesture-only uinput protocol was also demonstrated
by Salacfrantisek/magic-mouse-wayland-gestures; this implementation is
adapted for Logitech evdev movement.
"""

import argparse
import logging
import os
import stat
import selectors
import socket
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    from evdev import AbsInfo, InputDevice, UInput, ecodes as e, list_devices
except ImportError:
    AbsInfo = InputDevice = UInput = e = list_devices = None

LOG = logging.getLogger("mxmaster3-gestures")
VENDOR_LOGITECH = 0x046D
# Logitech devices can expose the thumb button as BTN_TASK (282), remap it
# to KEY_PROG3 (202), or send KEY_F24 (194) via a separate virtual keyboard.
GESTURE_KEY = 202  # Keep the original code as a known alternative.
BTN_TASK = 282
KEY_F24 = 194
MOUSE_BUTTONS = (GESTURE_KEY, BTN_TASK)
DEFAULT_BUTTONS = (GESTURE_KEY, BTN_TASK, KEY_F24)
TOUCH_MAX = 4095
CENTER = TOUCH_MAX // 2
FINGER_SPACING = 260  # ~5.8 mm at 45 units/mm
TOUCH_RESOLUTION = 45
try:
    SENSITIVITY = max(0.1, min(10.0, float(os.environ.get("MXG_SENSITIVITY", "2.0"))))
except ValueError:
    SENSITIVITY = 2.0
NAME = "MX Master 3 Native Gesture Touchpad"
SERVICE = "mxmaster3-gestures.service"
CONTROL_SOCKET = "mxmaster3-gestures-control.sock"
SOLAAR_SOURCE = object()


class SwipeTouchpad:
    """Emit a three-contact type-B sequence that GNOME interprets natively."""

    def __init__(self, factory=None):
        if e is None:
            raise RuntimeError("Missing python-evdev. On Arch: sudo pacman -S python-evdev")
        position = AbsInfo(CENTER, 0, TOUCH_MAX, 0, 0, TOUCH_RESOLUTION)
        caps = {
            e.EV_KEY: [e.BTN_TOUCH, e.BTN_TOOL_FINGER,
                       e.BTN_TOOL_DOUBLETAP, e.BTN_TOOL_TRIPLETAP],
            e.EV_ABS: [
                (e.ABS_X, position),
                (e.ABS_Y, position),
                (e.ABS_MT_SLOT, AbsInfo(0, 0, 2, 0, 0, 0)),
                (e.ABS_MT_POSITION_X, position),
                (e.ABS_MT_POSITION_Y, position),
                (e.ABS_MT_TRACKING_ID, AbsInfo(0, 0, 65535, 0, 0, 0)),
            ],
        }
        self.device = (factory or UInput)(
            events=caps, name=NAME, bustype=e.BUS_VIRTUAL,
            vendor=0x0001, product=0x0003, version=1,
            input_props=[e.INPUT_PROP_POINTER], max_effects=0,
        )
        self.active = False
        self.ids = 1
        self.x = 0.0
        self.y = 0.0
        self.gain = SENSITIVITY
        LOG.info("Created virtual touchpad: %s", NAME)

    def _position(self):
        cx, cy = round(CENTER + self.x), round(CENTER + self.y)
        self.device.write(e.EV_ABS, e.ABS_X, cx)
        self.device.write(e.EV_ABS, e.ABS_Y, cy)
        for slot, offset in enumerate((-FINGER_SPACING, 0, FINGER_SPACING)):
            self.device.write(e.EV_ABS, e.ABS_MT_SLOT, slot)
            self.device.write(e.EV_ABS, e.ABS_MT_POSITION_X, cx + offset)
            self.device.write(e.EV_ABS, e.ABS_MT_POSITION_Y, cy)
        self.device.syn()

    def begin(self):
        if self.active:
            return
        self.x = self.y = 0.0
        if self.ids > 65000:
            self.ids = 1
        self.device.write(e.EV_KEY, e.BTN_TOUCH, 1)
        self.device.write(e.EV_KEY, e.BTN_TOOL_TRIPLETAP, 1)
        for slot in range(3):
            self.device.write(e.EV_ABS, e.ABS_MT_SLOT, slot)
            self.device.write(e.EV_ABS, e.ABS_MT_TRACKING_ID, self.ids + slot)
        self.ids += 3
        self._position()
        self.active = True

    def move(self, dx, dy):
        if not self.active:
            return
        # Preserve direction and reversal; clamp to the physical pad limits.
        xlimit = CENTER - FINGER_SPACING
        ylimit = CENTER
        self.x = max(-xlimit, min(xlimit, self.x + dx * self.gain))
        self.y = max(-ylimit, min(ylimit, self.y + dy * self.gain))
        self._position()

    def end(self):
        if not self.active:
            return
        for slot in range(3):
            self.device.write(e.EV_ABS, e.ABS_MT_SLOT, slot)
            self.device.write(e.EV_ABS, e.ABS_MT_TRACKING_ID, -1)
        self.device.write(e.EV_KEY, e.BTN_TOUCH, 0)
        self.device.write(e.EV_KEY, e.BTN_TOOL_TRIPLETAP, 0)
        self.device.syn()
        self.active = False

    def close(self):
        try:
            self.end()
        finally:
            self.device.close()


def read_input_caps(dev):
    """Only read capabilities; observing input never requires grabbing it."""
    caps = dev.capabilities(absinfo=False)
    keys = set(caps.get(e.EV_KEY, []))
    rel = set(caps.get(e.EV_REL, []))
    pointer = e.REL_X in rel and e.REL_Y in rel
    return pointer, keys


def open_logitech_inputs():
    """Open Logitech inputs only; never grab keyboards or unrelated mice."""
    found = []
    errors = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
            if dev.info.vendor != VENDOR_LOGITECH or NAME in dev.name:
                dev.close()
                continue
            # This deliberately does not open unrelated keyboards, including
            # real user keyboards. A receiver keyboard is only used if it
            # advertises a known gesture key and is paired with the mouse.
            pointer, keys = read_input_caps(dev)
            trigger = any(code in keys for code in MOUSE_BUTTONS)
            if pointer or trigger:
                found.append((dev, pointer, trigger))
            else:
                dev.close()
        except PermissionError as exc:
            errors.append((path, str(exc)))
        except OSError:
            continue
    return found, errors


def open_f24_keyboards(explicit=None):
    """Observe ONLY F24-capable non-pointer devices, without grabbing them.

    Solaar/input-remapper may send the thumb button from a virtual keyboard,
    not from Logitech's mouse evdev node. Other key events are discarded,
    never logged or forwarded. Input events remain delivered normally to GNOME.
    """
    found, errors = [], []
    for path in list_devices():
        try:
            if explicit and path != explicit and os.path.realpath(path) != os.path.realpath(explicit):
                continue
            dev = InputDevice(path)
            if NAME in dev.name:
                dev.close()
                continue
            pointer, keys = read_input_caps(dev)
            if not pointer and KEY_F24 in keys:
                found.append(dev)
            else:
                dev.close()
        except PermissionError as exc:
            errors.append((path, str(exc)))
        except OSError:
            continue
    return found, errors


def parse_button(value):
    """Parse optional MXG_BUTTON: KEY_PROG3, BTN_TASK, KEY_F24 or number."""
    if value is None or str(value).strip().lower() in ("", "auto"):
        return None
    val = str(value).strip().upper()
    if val.startswith(("BTN_", "KEY_")):
        code = getattr(e, val, None)
    else:
        try:
            code = int(val, 0)
        except ValueError:
            code = None
    if not isinstance(code, int) or not 1 <= code <= 767:
        raise InputSetupError(f"Unknown button {value!r}. Use BTN_TASK, KEY_PROG3, KEY_F24 or an evdev code.")
    return code


class InputSetupError(RuntimeError):
    """Setup problem: don't restart endlessly until the user has fixed it."""


def select_button(sources, requested=None):
    """Pick a button that an associated source actually advertises."""
    available = set()
    for dev in sources:
        available.update(read_input_caps(dev)[1])
    if requested is not None:
        if requested not in available:
            raise InputSetupError(
                f"Configured button {e.KEY.get(requested, requested)} ({requested}) "
                "is not available on this mouse. Run --list-devices and --probe-thumb."
            )
        return requested
    for code in DEFAULT_BUTTONS:
        if code in available:
            return code
    raise InputSetupError(
        "No standard gesture button detected (KEY_PROG3=202 or BTN_TASK=282). "
        "Run --probe-thumb and press the thumb button. If nothing appears, "
        "the mouse is probably reporting the button using Logitech HID++; "
        "configure Solaar button diversion before retrying."
    )


def select_mouse(inputs, explicit=None):
    candidates = [(d, is_pointer, is_trigger)
                  for d, is_pointer, is_trigger in inputs if is_pointer]
    if explicit:
        candidates = [item for item in candidates
                      if item[0].path == explicit or
                      os.path.realpath(item[0].path) == os.path.realpath(explicit)]
    else:
        # Prefer the precise product name, not an arbitrary Logitech mouse.
        named = [item for item in candidates
                 if "mx master 3" in item[0].name.casefold()]
        if named:
            candidates = named
        else:
            # Receivers can expose generic names. Only accept one unique
            # receiver mouse node; refuse to choose between multiple mice.
            candidates = [item for item in candidates
                          if "receiver" in item[0].name.casefold()]
    if len(candidates) != 1:
        summary = ", ".join(f"{d.path}: {d.name}" for d, _, _ in candidates)
        raise InputSetupError(
            "Cannot uniquely identify the MX Master 3 motion device. "
            f"Candidates: {summary or '(none)'}. Run --list-devices then "
            "set MXG_MOUSE=/dev/input/eventN in ~/.config/mxmaster3-gestures.conf."
        )
    return candidates[0][0]


class GestureRunner:
    def __init__(self, mouse, sources, touchpad, button=None):
        self.mouse = mouse
        self.sources = sources
        self.touchpad = touchpad
        self.buttons = {button} if button is not None else set(DEFAULT_BUTTONS)
        self.trigger_source = None
        self.trigger_code = None
        self.held = False
        self.grabbed = False
        self.running = True
        self.dx = self.dy = 0
        self.started = 0.0
        self.control_socket = None

    def flush(self):
        if self.held and (self.dx or self.dy):
            self.touchpad.move(self.dx, self.dy)
        self.dx = self.dy = 0

    def press(self, source=None, code=None):
        if self.held:
            return
        # An EVIOCGRAB on the physical REL device blocks GNOME from seeing
        # cursor movement; no replacement virtual mouse is needed.
        self.mouse.grab()
        self.grabbed = True
        try:
            self.touchpad.begin()
        except Exception:
            self.mouse.ungrab()
            self.grabbed = False
            raise
        self.held = True
        self.trigger_source = source
        self.trigger_code = code
        self.started = time.monotonic()
        LOG.info("Gesture started: %s on %s (cursor frozen)",
                 e.KEY.get(code, code), getattr(source, 'name', '(unknown)'))

    def release(self):
        if not self.held and not self.grabbed:
            return
        self.flush()
        try:
            self.touchpad.end()
        finally:
            self.held = False
            self.trigger_source = None
            self.trigger_code = None
            self.dx = self.dy = 0
            if self.grabbed:
                self.mouse.ungrab()
                self.grabbed = False
        LOG.info("Gesture ended (normal pointer restored)")

    def event(self, source, event):
        if event.type == e.EV_KEY and event.code in self.buttons:
            if event.value == 1:
                self.press(source, event.code)
            elif (event.value == 0 and self.held and
                  self.trigger_source is source and self.trigger_code == event.code):
                self.release()
            return
        if source is not self.mouse:
            return
        if event.type == e.EV_REL and self.held:
            if event.code == e.REL_X:
                self.dx += event.value
            elif event.code == e.REL_Y:
                self.dy += event.value
        elif event.type == e.EV_SYN and event.code == e.SYN_REPORT:
            self.flush()
        elif event.type == e.EV_SYN and event.code == e.SYN_DROPPED:
            LOG.warning("Input stream overflow; releasing gesture")
            self.release()

    def control(self, command):
        """Short control signals from Solaar press/release Execute rules."""
        if command == b'press':
            self.press(SOLAAR_SOURCE, 'solaar')
        elif command == b'release':
            if self.held and self.trigger_source is SOLAAR_SOURCE:
                self.release()
        else:
            LOG.warning('Unknown control command ignored')

    def close(self):
        try:
            self.release()
        finally:
            self.touchpad.close()
            for dev in self.sources:
                try:
                    dev.close()
                except OSError:
                    pass

    def run(self):
        sel = selectors.DefaultSelector()
        path = control_socket_path()
        # No keylogger, external keyboard grab, or long-lived privileged IPC.
        # Our socket lives inside the owner's private XDG runtime directory.
        if os.path.lexists(path):
            if not stat.S_ISSOCK(os.lstat(path).st_mode):
                raise InputSetupError('Unexpected non-socket at control path; refusing to unlink')
            os.unlink(path)
        channel = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        channel.setblocking(False)
        try:
            channel.bind(str(path))
            os.chmod(path, 0o600)
        except Exception:
            channel.close()
            raise
        self.control_socket = channel
        try:
            for dev in self.sources:
                sel.register(dev.fd, selectors.EVENT_READ, dev)
            sel.register(channel, selectors.EVENT_READ, None)
            # Tell systemd the driver is READY only after it has successfully
            # opened the mouse and created the uinput touchpad.
            systemd_notify_ready()
            while self.running:
                ready = sel.select(timeout=0.5)
                for key, _ in ready:
                    dev = key.data
                    if dev is None:
                        try:
                            payload = channel.recv(128)
                            self.control(payload)
                        except BlockingIOError:
                            pass
                        continue
                    try:
                        events = dev.read()
                        for event in events:
                            self.event(dev, event)
                    except BlockingIOError:
                        continue
                    except OSError as exc:
                        LOG.warning("Input disconnected: %s: %s", dev.name, exc)
                        return 1  # systemd retries after reconnect
                # Prevent a disconnected or missing thumb-up report from
                # permanently suppressing the pointer.
                if self.held and time.monotonic() - self.started > 30.0:
                    LOG.warning("Gesture timed out after 30s; ungrabbing mouse")
                    self.release()
        finally:
            sel.close()
            try:
                channel.close()
            finally:
                if os.path.exists(path):
                    os.unlink(path)
            self.control_socket = None
            self.close()
        return 0


def control_socket_path():
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
    st = runtime.stat()
    if st.st_uid != os.getuid() or not stat.S_ISDIR(st.st_mode) or (st.st_mode & 0o077):
        raise InputSetupError('XDG_RUNTIME_DIR must be a private directory owned by the current user')
    return runtime / CONTROL_SOCKET


def send_solaar_signal(action):
    path = control_socket_path()
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
        try:
            channel.sendto(action.encode('ascii'), str(path))
        except OSError as exc:
            raise InputSetupError('Gesture driver is not running; start it from GNOME Activities') from exc


def systemd_notify_ready():
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    # systemd's abstract Unix sockets begin with @ in NOTIFY_SOCKET.
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as conn:
        conn.connect(addr)
        conn.sendall(b"READY=1")


def run_daemon(path, button=None, key_device=None):
    if e is None:
        raise RuntimeError("Install python-evdev: sudo pacman -S python-evdev")
    inputs, errors = open_logitech_inputs()
    keyboards, keyboard_errors = open_f24_keyboards(key_device)
    try:
        mouse = select_mouse(inputs, path)
        # Only observe key sources plausibly part of this mouse; Logitech USB
        # receivers can expose thumb keys through a separate event node.
        sources = [dev for dev, pointer, trigger in inputs
                   if dev is mouse or (trigger and (
                       "mx master 3" in dev.name.casefold() or
                       dev.name == mouse.name or
                       ("receiver" in mouse.name.casefold() and
                        "receiver" in dev.name.casefold()) or
                       (bool(mouse.uniq) and dev.uniq == mouse.uniq) or
                       dev.info.product == mouse.info.product
                   ))]
        sources.extend(keyboards)
        # Check each trigger code against its actual source. Advertising
        # BTN_TASK does NOT prove the thumb press reports BTN_TASK: Solaar may
        # instead emit KEY_F24 from a virtual keyboard.
        advertised = set().union(*(read_input_caps(dev)[1] for dev in sources))
        enabled = ({button} if button is not None else set(DEFAULT_BUTTONS))
        matching = advertised & enabled
        if not matching:
            raise InputSetupError(
                'No usable gesture button: BTN_TASK=282, KEY_PROG3=202, KEY_F24=194. '
                'Run --probe-thumb, and inspect any F24 keyboard sources.'
            )
        for dev, _, _ in inputs:
            if dev not in sources:
                dev.close()
        pad = SwipeTouchpad()
        runner = GestureRunner(mouse, sources, pad, button)
        def shutdown(_signum, _frame):
            runner.running = False
        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)
        LOG.info("Ready: %s (%s), watching codes %s across %s inputs, sensitivity %.2f",
                 mouse.name, mouse.path, sorted(matching), len(sources), SENSITIVITY)
        if keyboards:
            LOG.info('F24 keyboard sources: %s',
                     '; '.join(f'{dev.path} {dev.name}' for dev in keyboards))
        if keyboard_errors:
            LOG.warning('Some input devices could not be inspected; '
                        'try --probe-thumb if the remapped key does not work')
        return runner.run()
    except Exception:
        for dev in ([entry[0] for entry in inputs] + keyboards):
            try:
                dev.close()
            except OSError:
                pass
        raise


def list_input_devices():
    if e is None:
        raise RuntimeError("Missing python-evdev")
    inputs, errors = open_logitech_inputs()
    keyboards, keyboard_errors = open_f24_keyboards()
    try:
        print("Readable Logitech mouse and gesture-button devices:")
        if not inputs:
            print("  (none)")
        for d, pointer, trigger in inputs:
            _, keys = read_input_caps(d)
            hints = [f"{e.KEY.get(code, code)}({code})" for code in
                     (GESTURE_KEY, BTN_TASK, e.BTN_EXTRA, e.BTN_SIDE,
                      e.BTN_BACK, e.BTN_FORWARD) if code in keys]
            print(f"  {d.path:<21} {d.name} | motion={pointer} "
                  f"buttons={','.join(hints) if hints else '(none of the common ones)'}")
        print('Readable F24-capable keyboards (observed but never grabbed):')
        for dev in keyboards:
            print(f'  {dev.path:<21} {dev.name} | KEY_F24(194)')
        if not keyboards:
            print('  (none)')
        if errors:
            print("Inaccessible input paths:", ", ".join(p for p, _ in errors))
        if keyboard_errors:
            print('Inaccessible keyboard paths:',
                  ', '.join(p for p, _ in keyboard_errors))
        print("/dev/uinput:", "available" if os.access("/dev/uinput", os.W_OK) else "not writable")
    finally:
        for d, _, _ in inputs:
            d.close()
        for d in keyboards:
            d.close()


def probe_thumb(seconds=10.0):
    """Listen for mouse buttons AND F24 on virtual/physical keyboards.

    Never grab the keyboard or log normal typing. This probe reports only
    F24/PROG3, Logitech mouse buttons, and their press/release transitions.
    """
    if e is None:
        raise RuntimeError("Missing python-evdev")
    inputs, errors = open_logitech_inputs()
    keyboards, keyboard_errors = open_f24_keyboards()
    # Reopen Logitech devices we omitted because they only have nonstandard
    # mouse buttons. We still refuse to monitor generic or other keyboards.
    found_paths = {d.path for d, _, _ in inputs}
    for path in list_devices():
        if path in found_paths:
            continue
        try:
            dev = InputDevice(path)
            if dev.info.vendor == VENDOR_LOGITECH and (
                "mx master" in dev.name.casefold() or
                "receiver" in dev.name.casefold()
            ):
                inputs.append((dev, False, False))
            else:
                dev.close()
        except OSError:
            continue
    sel = selectors.DefaultSelector()
    try:
        for dev, _, _ in inputs:
            sel.register(dev.fd, selectors.EVENT_READ, dev)
        for dev in keyboards:
            sel.register(dev.fd, selectors.EVENT_READ, dev)
        print("Press and RELEASE only the thumb gesture button several times now.", flush=True)
        print(f"Listening to {len(inputs)} Logitech inputs and "
              f"{len(keyboards)} F24-capable keyboards for {seconds:g} seconds. "
              "No input is intercepted.", flush=True)
        for dev in keyboards:
            print(f'  F24 source: {dev.path} {dev.name}', flush=True)
        deadline = time.monotonic() + seconds
        matched = 0
        while time.monotonic() < deadline:
            for key, _ in sel.select(min(0.3, max(0, deadline - time.monotonic()))):
                dev = key.data
                try:
                    for ev in dev.read():
                        if ev.type == e.EV_KEY and ev.value in (0, 1):
                            # Never log regular keyboard keys/typing.
                            if ((dev in keyboards and ev.code == KEY_F24) or
                                (dev not in keyboards and
                                 (ev.code >= e.BTN_MOUSE or ev.code in DEFAULT_BUTTONS))):
                                print(f"  {dev.path} {dev.name}: "
                                      f"{e.KEY.get(ev.code, ev.code)}({ev.code}) "
                                      f"{'PRESS' if ev.value else 'RELEASE'}", flush=True)
                                matched += 1
                except (BlockingIOError, OSError):
                    continue
        if not matched:
            print('No recognized button events. Thumb may be handled outside evdev '
                  '(e.g. by Solaar HID++). Also check read permissions for the '
                  'F24 virtual keyboard and inspect `solaar show`.')
    finally:
        sel.close()
        for dev, _, _ in inputs:
            dev.close()
        for dev in keyboards:
            dev.close()


def test_swipe(direction):
    pad = SwipeTouchpad()
    vectors = {"left": (-13, 0), "right": (13, 0),
               "up": (0, -13), "down": (0, 13)}
    dx, dy = vectors[direction]
    try:
        time.sleep(0.3)  # allow udev/libinput to register the device
        pad.begin()
        for _ in range(65):
            pad.move(dx, dy)
            time.sleep(0.012)
        time.sleep(0.08)
        pad.end()
    finally:
        pad.close()


def toggle():
    status = subprocess.run(["systemctl", "--user", "is-active", "--quiet", SERVICE], check=False)
    starting = status.returncode != 0
    operation = "start" if starting else "stop"
    result = subprocess.run(["systemctl", "--user", operation, SERVICE], capture_output=True, text=True)
    message = ("Gestures started — hold the thumb button and move"
               if starting else "Gestures stopped — normal mouse unchanged")
    if result.returncode:
        message = (result.stderr or "Unable to control service").strip()[:250]
        LOG.error(message)
    else:
        LOG.info(message)
    if subprocess.run(["sh", "-c", "command -v notify-send >/dev/null 2>&1"]).returncode == 0:
        subprocess.run(["notify-send", "MX Master 3 Gestures", message], check=False)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="run the gesture daemon (systemd)")
    parser.add_argument("--solaar", choices=("press", "release"), help="Solaar-only button signal to the running daemon")
    parser.add_argument("--toggle", action="store_true", help="start/stop daemon from GNOME launcher")
    parser.add_argument("--list-devices", action="store_true", help="diagnose Logitech input nodes")
    parser.add_argument("--probe-thumb", action="store_true", help="watch Logitech mouse buttons and F24 keyboards for 10s without grabbing")
    parser.add_argument('--key-device', default=os.environ.get('MXG_KEY_DEVICE'),
                        help='optional exact /dev/input/eventN for a remapped F24 keyboard')
    parser.add_argument("--test-swipe", choices=("left", "right", "up", "down"), help="test native swipe without the physical mouse")
    parser.add_argument("--mouse", default=os.environ.get("MXG_MOUSE", None), help="exact /dev/input/event path when auto-detection is ambiguous")
    parser.add_argument("--button", default=os.environ.get("MXG_BUTTON", "auto"),
                        help="thumb button evdev code or name (auto, BTN_TASK, KEY_PROG3, KEY_F24)")
    args = parser.parse_args()
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    try:
        if args.solaar:
            send_solaar_signal(args.solaar)
            return 0
        if args.toggle:
            return toggle()
        if args.list_devices:
            list_input_devices()
            return 0
        if args.probe_thumb:
            probe_thumb()
            return 0
        if args.test_swipe:
            test_swipe(args.test_swipe)
            return 0
        return run_daemon(args.mouse, parse_button(args.button), args.key_device)
    except InputSetupError as ex:
        LOG.error("%s", ex)
        return 78  # EX_CONFIG; systemd RestartPreventExitStatus=78
    except (OSError, RuntimeError, ValueError) as ex:
        LOG.error("%s", ex)
        return 1


if __name__ == "__main__":
    sys.exit(main())
