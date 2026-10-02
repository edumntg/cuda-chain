#!/bin/sh
# Install the plasmon CLI binary from GitHub Releases. Linux and macOS.
#   curl -fsSL https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.sh | sh
set -eu

REPO="edumntg/plasmon"
VERSION="${PLASMON_VERSION:-latest}"
INSTALL_DIR="${PLASMON_INSTALL_DIR:-$HOME/.local/bin}"

os=$(uname -s)
arch=$(uname -m)
case "$os" in
  Linux)  os_name="linux" ;;
  Darwin) os_name="darwin" ;;
  *) echo "unsupported OS: $os" >&2; exit 1 ;;
esac
case "$arch" in
  x86_64|amd64) arch_name="x86_64" ;;
  arm64|aarch64) arch_name="arm64" ;;
  *) echo "unsupported architecture: $arch" >&2; exit 1 ;;
esac
file="plasmon-${os_name}-${arch_name}"

if [ "$VERSION" = "latest" ]; then
  base="https://github.com/$REPO/releases/latest/download"
else
  base="https://github.com/$REPO/releases/download/$VERSION"
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
echo "downloading $file ($VERSION)"
curl -fsSL "$base/$file" -o "$tmp/plasmon"
curl -fsSL "$base/$file.sha256" -o "$tmp/plasmon.sha256"
expected=$(cut -d' ' -f1 "$tmp/plasmon.sha256")
if command -v sha256sum >/dev/null 2>&1; then actual=$(sha256sum "$tmp/plasmon" | cut -d' ' -f1); else actual=$(shasum -a 256 "$tmp/plasmon" | cut -d' ' -f1); fi
if [ "$expected" != "$actual" ]; then
  echo "checksum mismatch: expected $expected, got $actual" >&2
  exit 1
fi
mkdir -p "$INSTALL_DIR"
install -m 755 "$tmp/plasmon" "$INSTALL_DIR/plasmon"
echo "installed $INSTALL_DIR/plasmon"
case ":$PATH:" in
  *":$INSTALL_DIR:"*) ;;
  *) echo "add $INSTALL_DIR to your PATH, for example:"; echo "  echo 'export PATH=\"$INSTALL_DIR:\$PATH\"' >> ~/.zshrc" ;;
esac
"$INSTALL_DIR/plasmon" --version
echo "next: python -m pip install \"plasmon[engine] @ git+https://github.com/$REPO.git\"   (the engine: server and trainer)"
