# Maintainer: MX Touchpad Gestures contributors
pkgname=mx-touchpad-gestures
pkgver=0.6.0
pkgrel=2
pkgdesc='Configure native GNOME touchpad swipes with a Logitech MX Master 3 gesture button'
arch=('x86_64')
url='https://github.com/johnniePM/mx-touchpad-gestures'
license=('AGPL-3.0-only')
depends=('python' 'python-evdev' 'systemd' 'python-gobject' 'gtk4' 'gsettings-desktop-schemas')
makedepends=('gcc')
optdepends=('solaar: handles diverted Logitech gesture-button press and release'
            'libnotify: desktop launcher notifications')
install=mx-touchpad-gestures.install
# Local source package: clone this repository, then run makepkg -si.
source=('mxmaster3_gestures.py'
        'mxmaster3_gesture_config.py'
        'mxmaster3_gestures_settings.py'
        'solaar_bridge.py'
        'fast_signal.c'
        'mxmaster3-gestures.service'
        'mxmaster3-gestures.desktop'
        'mxmaster3-gestures-settings.desktop'
        '71-mxmaster3-gestures.rules'
        'mxmaster3-gestures.conf'
        'mxmaster3-gestures-setup'
        'test_gestures.py'
        'README.md'
        'LICENSE')
sha256sums=(
  '847fb1617a87eea1ca7222b79597e63110b2bf9d3f03bf8c54ba9bbc1cc5eea9'
  'cd78a0e20d245140c5dbe9e140ecc9a0cb1148b226aafe186160248f83909071'
  '79489940096c68f126ee076dfe76d44d4e3cb6d7a77889f019e65ec4f9bf11c3'
  '3d3d76ee7128672cf90b526434093f56f44c661fbe29860e566803b09c833219'
  '90d4a3f608005523aaefa456cbf98e267be88a81c519751bb4907a881a82371e'
  '09c4ec5c1d22092321d716a26cf47a6cb68be6d91bf4e6ec77da51afc9ed72c5'
  'cc7803166afea852a12a1a333a33833cb9f11f5c33f91c096ded6a785ee6d3c7'
  'bb9b72a20c6d170574a7ea0425ff75dfac75c31ca37edd44bc56c82d38157b0c'
  'b50fdfdd253387cfc01795b33df828c6cad5f100012fb70cfe3d9e37639788fd'
  'a771c9695d7283f7771adc00b680bd27391e6ac00e9fd026f4796067ee9a87eb'
  '08704ed1df538f522a2216207f19345cafffdd665481c05199ca1806b524c106'
  'c081dce3b31f5c365abcd77c3910cc922b04a64fc0317cf860f3db80cd161096'
  '6efb188eaeb35b6dbf0c8c1b77a5dc9790806ca7dc0a2a43669695633de0d760'
  '8486a10c4393cee1c25392769ddd3b2d6c242d6ec7928e1414efff7dfb2f07ef'
)

build() {
  cc ${CFLAGS:-} -std=c11 -Wall -Wextra \
    "$srcdir/fast_signal.c" -o "$srcdir/mxmaster3-gesture-signal" ${LDFLAGS:-}
}

check() {
  cd "$srcdir"
  python3 -m unittest -q test_gestures.py
}

package() {
  install -Dm755 "$srcdir/mxmaster3_gestures.py" "$pkgdir/usr/bin/mxmaster3-gestures"
  install -Dm755 "$srcdir/mxmaster3_gestures_settings.py" "$pkgdir/usr/bin/mxmaster3-gestures-settings"
  install -Dm644 "$srcdir/mxmaster3_gesture_config.py" "$pkgdir/usr/lib/mx-touchpad-gestures/mxmaster3_gesture_config.py"
  install -Dm755 "$srcdir/solaar_bridge.py" "$pkgdir/usr/bin/mxmaster3-solaar-bridge"
  install -Dm755 "$srcdir/mxmaster3-gestures-setup" "$pkgdir/usr/bin/mxmaster3-gestures-setup"
  install -Dm755 "$srcdir/mxmaster3-gesture-signal" "$pkgdir/usr/bin/mxmaster3-gesture-signal"
  install -Dm644 "$srcdir/mxmaster3-gestures.service" "$pkgdir/usr/lib/systemd/user/mxmaster3-gestures.service"
  install -Dm644 "$srcdir/mxmaster3-gestures.desktop" "$pkgdir/usr/share/applications/mxmaster3-gestures.desktop"
  install -Dm644 "$srcdir/mxmaster3-gestures-settings.desktop" "$pkgdir/usr/share/applications/mxmaster3-gestures-settings.desktop"
  install -Dm644 "$srcdir/71-mxmaster3-gestures.rules" "$pkgdir/usr/lib/udev/rules.d/71-mxmaster3-gestures.rules"
  install -Dm644 "$srcdir/mxmaster3-gestures.conf" "$pkgdir/usr/lib/modules-load.d/mxmaster3-gestures.conf"
  install -Dm644 "$srcdir/README.md" "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm644 "$srcdir/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
