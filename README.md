# MX Touchpad Gestures

Native **GNOME Wayland** touchpad swipes using a Logitech MX Master 3 / MX Master 3S thumb gesture button. Hold the button and move the mouse to navigate workspaces or open the Overview. Swipes follow your movement continuously, including reversing direction before release. Outside gesture mode the mouse behaves normally.

The application includes a graphical **Settings** window for gesture speed, three- or four-finger swipes, flick acceleration, and the GNOME mouse pointer speed. It uses real Linux multitouch input rather than keyboard shortcuts, so GNOME handles the gestures consistently across the desktop. This does **not** add GNOME gestures to other desktop environments such as KDE.

## Install on Arch Linux

```bash
git clone https://github.com/johnniePM/mx-touchpad-gestures.git
cd mx-touchpad-gestures
makepkg -si
```

For Logitech thumb-button diversion, install Solaar and configure its bridge:

```bash
sudo pacman -S solaar
mxmaster3-gestures-setup
```

In Solaar's main window, select your MX Master 3, open **Key/Button Diversion** (`Tangent/knapp avledning`), select **Mouse Gesture Button** (`Mus gestknapp`), and set it to **Diverted** (`Avledd`), **not** Mouse Gestures. Completely quit and restart Solaar. Keep Solaar running. If your mouse exposes the thumb button through Linux evdev directly, Solaar is optional.

## Open Settings

Open **MX Touchpad Gestures Settings** from GNOME Activities, or run:

```bash
mxmaster3-gestures-settings
```

Available settings:

- **Gesture fingers:** Emit **three** or **four** actual synchronized virtual touch points. Both are supported by GNOME 47+ native swipe handling. Three fingers is the default.
- **Gesture speed:** Scale mouse motion while holding the gesture button without changing normal pointer speed. Range: 0.25–6.0, default 2.0.
- **Enable flick boost:** Optionally give short, fast motion more travel. Disabled by default to preserve precise, reversible motion.
- **Flick strength:** Maximum additional distance for quick movement (0–200%).
- **Flick activation speed:** Minimum mouse movement speed before boost begins. GNOME supplies its own native release animation; this app does not keep moving the virtual touchpad after you release the button.
- **GNOME pointer speed:** Changes GNOME's real system mouse-speed setting for all GNOME applications, independently of gesture speed. It does not alter the hardware DPI.

Select **Save and apply**. Settings persist in `~/.config/mxmaster3-gestures.conf`. The running user service restarts automatically on Apply; a stopped service remains stopped. The window also has **Start gestures** and **Stop gestures** controls.

The existing **MX Master 3 Gestures** launcher toggles the driver. Installation does not auto-start the service.

## Troubleshooting

If the driver cannot access `/dev/uinput` or your mouse device, reconnect the mouse or log out and back in to refresh `udev` permissions. To load the kernel module immediately:

```bash
sudo modprobe uinput
```

Diagnostic commands:

```bash
systemctl --user status mxmaster3-gestures.service
journalctl --user -u mxmaster3-gestures -n 60 --no-pager
mxmaster3-gestures --list-devices
mxmaster3-gestures --probe-thumb
mxmaster3-gestures --test-swipe left
```

If you use an unusual input device, configure `MXG_MOUSE`, `MXG_BUTTON`, or `MXG_KEY_DEVICE` in `~/.config/mxmaster3-gestures.conf`. The graphical preferences editor preserves these custom options.

## Update / uninstall

From the cloned repository run `git pull` followed by `makepkg -si` to update.

To remove the Solaar bridge rules first, then uninstall:

```bash
mxmaster3-solaar-bridge remove
sudo pacman -Rns mx-touchpad-gestures
```

Personal configuration remains untouched by pacman removal.

## Development

- The Python daemon uses `evdev` to read the Logitech mouse and grab its motion events only while the gesture button is held. No keyboard grabbing or logging of regular keystrokes.
- A virtual `uinput` touchpad emits Linux type-B multitouch frames for 3 or 4 contacts; GNOME's compositor controls workspace movement and final animations.
- Flick boost is velocity-sensitive amplification during the swipe, not a separate simulated pointer gesture or a background inertial cursor.
- The native C Solaar helper sends press/release signals over a private Unix socket, avoiding Python interpreter startup on every press.
- The GUI uses GTK 4 / PyGObject and GNOME GSettings. Per-user configuration is atomically updated without overwriting unrelated device settings.

Development checks:

```bash
python3 -m unittest -q test_gestures.py
bash -n PKGBUILD mxmaster3-gestures-setup mx-touchpad-gestures.install
cc -std=c11 -Wall -Wextra -o /tmp/mxmaster3-gesture-signal fast_signal.c
```

## License

**AGPL-3.0-only**; see [LICENSE](LICENSE). Gesture protocol research referenced [magic-mouse-wayland-gestures](https://github.com/Salacfrantisek/magic-mouse-wayland-gestures).
