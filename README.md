# MX Touchpad Gestures for GNOME

Make the Logitech MX Master 3 thumb gesture button behave like a touchpad on **GNOME Wayland**. Hold the button and move the mouse for continuous, reversible three-finger workspace swipes and Overview gestures. Normal pointer movement is unaffected when the gesture button is released.

The project provides a native **Arch Linux package** built with `makepkg` and managed with `pacman`. GNOME 51 is the target desktop.

## Installation (Arch Linux)

```bash
git clone https://github.com/johnniePM/mx-touchpad-gestures.git
cd mx-touchpad-gestures
makepkg -si
```

For MX Master 3 gesture-button support through Solaar, install Solaar and configure the user-session bridge:

```bash
sudo pacman -S solaar
mxmaster3-gestures-setup
```

Run the setup command as your regular desktop user, **not** with `sudo`. In Solaar's main device settings under **Key/Button Diversion** (`Tangent/knapp avledning`), select **Mouse Gesture Button** (`Mus gestknapp`) and set it to **Diverted** (`Avledd`), not **Mouse Gestures**. Quit Solaar completely and restart it so it loads the rules. Keep Solaar running for the button bridge.

If the mouse exposes its gesture-button press/release directly through evdev, Solaar is not required. It is an optional pacman dependency.

Open GNOME Activities and launch **MX Master 3 Gestures**. Selecting the launcher again stops the service. Installation does not automatically start the gesture driver.

## Permissions

If the driver cannot access `/dev/uinput` or the mouse input device, reconnect the mouse or log out and back in so `udev`/logind permissions take effect. You can also load the module immediately using `sudo modprobe uinput`. The package installs rules for input access and loading the module at boot.

## Diagnostics and configuration

```bash
systemctl --user status mxmaster3-gestures.service
journalctl --user -u mxmaster3-gestures -n 60 --no-pager
mxmaster3-gestures --list-devices
mxmaster3-gestures --probe-thumb
mxmaster3-gestures --test-swipe left
```

The standalone swipe test writes to `/dev/uinput` and does not need Solaar. To adjust sensitivity, add `MXG_SENSITIVITY=2.0` to `~/.config/mxmaster3-gestures.conf` and restart the service. Advanced device selection can use `MXG_MOUSE`, `MXG_BUTTON`, or `MXG_KEY_DEVICE`.

## Uninstall

To remove this project's generated Solaar rules and then uninstall the pacman package:

```bash
mxmaster3-solaar-bridge remove
sudo pacman -Rns mx-touchpad-gestures
```

Pacman removes the files owned by the package. Personal configuration is retained.

## Development

- The Python daemon uses `evdev` to read mouse movement and grabs the motion device only during a held gesture.
- Linux `uinput` presents a virtual three-contact touchpad to GNOME/libinput; gestures are not simulated with keyboard shortcuts.
- A small compiled helper forwards diverted Solaar button presses and releases to a private socket under `$XDG_RUNTIME_DIR` without launching Python for every click.
- The pacman package compiles `fast_signal.c` locally and does not write to individual home directories during package installation.

Run the automated tests and basic checks from the repository root:

```bash
python3 -m unittest -v test_gestures.py
bash -n PKGBUILD mxmaster3-gestures-setup mx-touchpad-gestures.install
cc -std=c11 -Wall -Wextra -o /tmp/mxmaster3-gesture-signal fast_signal.c
```

## License

**AGPL-3.0-only**, per the repository's [`LICENSE`](LICENSE). Gesture-protocol research referenced [magic-mouse-wayland-gestures](https://github.com/Salacfrantisek/magic-mouse-wayland-gestures).
