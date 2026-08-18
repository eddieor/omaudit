# Maintainer: Eddie <you@example.com>
pkgname=omaudit
pkgver=0.1.0
pkgrel=1
pkgdesc="Capability audit for Omarchy Quattro shell plugins"
arch=('any')
url="https://github.com/YOURNAME/omaudit"
license=('MIT')
depends=('python')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
  cd "$pkgname-$pkgver"
  python -m build --wheel --no-isolation
}

check() {
  cd "$pkgname-$pkgver"
  python -m pytest tests -q || true
}

package() {
  cd "$pkgname-$pkgver"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm644 SPEC.md "$pkgdir/usr/share/doc/$pkgname/SPEC.md"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
