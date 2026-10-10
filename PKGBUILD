# Maintainer: MX Touchpad Gestures contributors
pkgname=mx-touchpad-gestures
pkgver=0.5.0
pkgrel=4
pkgdesc='Continuous native GNOME Wayland touchpad gestures with Logitech MX Master 3'
arch=('x86_64')
url='https://github.com/johnniePM/mx-touchpad-gestures'
license=('AGPL-3.0-only')
depends=('python' 'python-evdev' 'systemd')
makedepends=('gcc')
optdepends=('solaar: handles diverted Logitech gesture-button press and release'
            'libnotify: desktop launcher notifications')
install=mx-touchpad-gestures.install
# Local sources: clone this repository and run makepkg -si in its root.
source=('mxmaster3_gestures.py'
        'solaar_bridge.py'
        'fast_signal.c'
        'mxmaster3-gestures.service'
        'mxmaster3-gestures.desktop'
        '71-mxmaster3-gestures.rules'
        'mxmaster3-gestures.conf'
        'mxmaster3-gestures-setup'
        'README.md'
        'LICENSE')
sha256sums=(
  'b503cb905bedb24131fea7b0f35f22dced64910f8fe5f3bab59da48ba83861f7'
  '3d3d76ee7128672cf90b526434093f56f44c661fbe29860e566803b09c833219'
  '90d4a3f608005523aaefa456cbf98e267be88a81c519751bb4907a881a82371e'
  '09c4ec5c1d22092321d716a26cf47a6cb68be6d91bf4e6ec77da51afc9ed72c5'
  'cc7803166afea852a12a1a333a33833cb9f11f5c33f91c096ded6a785ee6d3c7'
  'b50fdfdd253387cfc01795b33df828c6cad5f100012fb70cfe3d9e37639788fd'
  'a771c9695d7283f7771adc00b680bd27391e6ac00e9fd026f4796067ee9a87eb'
  'f3894f519358118d53cdf03878da4e4f114553a12ebb32173ba868ce7541dc7b'
  '2b85c51414898ee2af92a3adbf246096d3eca4d0f9986641932b445518e96387'
  '8486a10c4393cee1c25392769ddd3b2d6c242d6ec7928e1414efff7dfb2f07ef'
)

build() {
  cc ${CFLAGS:-} -std=c11 -Wall -Wextra \
    "$srcdir/fast_signal.c" -o "$srcdir/mxmaster3-gesture-signal" ${LDFLAGS:-}
}

package() {
  install -Dm755 "$srcdir/mxmaster3_gestures.py" "$pkgdir/usr/bin/mxmaster3-gestures"
  install -Dm755 "$srcdir/solaar_bridge.py" "$pkgdir/usr/bin/mxmaster3-solaar-bridge"
  install -Dm755 "$srcdir/mxmaster3-gestures-setup" "$pkgdir/usr/bin/mxmaster3-gestures-setup"
  install -Dm755 "$srcdir/mxmaster3-gesture-signal" "$pkgdir/usr/bin/mxmaster3-gesture-signal"
  install -Dm644 "$srcdir/mxmaster3-gestures.service" "$pkgdir/usr/lib/systemd/user/mxmaster3-gestures.service"
  install -Dm644 "$srcdir/mxmaster3-gestures.desktop" "$pkgdir/usr/share/applications/mxmaster3-gestures.desktop"
  install -Dm644 "$srcdir/71-mxmaster3-gestures.rules" "$pkgdir/usr/lib/udev/rules.d/71-mxmaster3-gestures.rules"
  install -Dm644 "$srcdir/mxmaster3-gestures.conf" "$pkgdir/usr/lib/modules-load.d/mxmaster3-gestures.conf"
  install -Dm644 "$srcdir/README.md" "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm644 "$srcdir/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
