# xdptype

`wtype` for Wayland desktops that don't implement the virtual-keyboard
protocol (GNOME/mutter, among others). `xdptype` types text through the
[xdg-desktop-portal RemoteDesktop portal][portal], the sanctioned way for an
app to send input on Wayland.

[portal]: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html

```sh
xdptype "Hello, Wayland"
xdptype "user" -k Tab - -k Return < password.txt
```

## Why not ydotool / dotool / wtype?

| Tool      | How it types          | GNOME Wayland | Needs                       |
|-----------|-----------------------|---------------|-----------------------------|
| `wtype`   | virtual-keyboard-v1   | no            | wlroots / KWin              |
| `xdotool` | XTEST                 | XWayland only | X11 windows                 |
| `ydotool` | `/dev/uinput`         | yes           | write access to uinput      |
| `dotool`  | `/dev/uinput`         | yes           | write access to uinput      |
| `xdptype` | RemoteDesktop portal  | yes           | one click in a dialog       |

Write access to `/dev/uinput` lets **any** process of your user inject input
into **any** window, silently and permanently. The portal asks once, shows an
indicator while a session is active, and the grant can be revoked in the
desktop settings.

The portal also takes *keysyms*, not keycodes, so non-ASCII text (`zażółć
gęślą jaźń`, `€`, `ß`) is typed as-is, without guessing the keyboard layout.

## Install

### Debian / Ubuntu (APT repository)

```sh
curl -fsSL https://iplweb.github.io/xdptype/xdptype-archive-keyring.gpg \
  | sudo tee /usr/share/keyrings/xdptype-archive-keyring.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/xdptype-archive-keyring.gpg] https://iplweb.github.io/xdptype/ ./" \
  | sudo tee /etc/apt/sources.list.d/xdptype.list
sudo apt update && sudo apt install xdptype
```

The repository is signed with key
`D266 40BB DC97 0AC5 702D  4557 CA8B 93C8 A67D 75D2`. A plain `.deb` is also
attached to every [GitHub release](https://github.com/iplweb/xdptype/releases).

### PyPI

```sh
uv tool install xdptype      # or: pipx install xdptype
```

The only dependencies are [jeepney](https://pypi.org/project/jeepney/), a
pure-Python D-Bus library, and libxkbcommon (present on every Wayland
desktop; used to map characters to the keysyms your layout uses).

The portal identifies non-sandboxed apps by a `.desktop` file matching the
app id. Install the bundled one so the dialog and the stored grant are
attributed to `xdptype`:

```sh
install -Dm644 data/io.github.mpasternak.xdptype.desktop \
  ~/.local/share/applications/io.github.mpasternak.xdptype.desktop
```

Without it `xdptype` still works, but prints a warning and the grant is
tied to an anonymous app.

## Usage

```
xdptype [options] [TEXT | -k KEY | -P KEY | -p KEY | -s MS | -] ...
```

Actions run in order, like `wtype`:

| Action    | Meaning                                                   |
|-----------|-----------------------------------------------------------|
| `TEXT`    | type `TEXT`                                               |
| `-`       | type text read from stdin (trailing newline dropped)      |
| `-k KEY`  | tap a key: `Return`, `Tab`, `Escape`, `F5`, `0xff0d`, `a` |
| `-P KEY`  | press and hold (`-M` alias)                               |
| `-p KEY`  | release (`-m` alias)                                      |
| `-s MS`   | sleep                                                     |

Options: `-d MS` delay between key events, `--delay SEC` wait before typing,
`--app-id ID`, `--forget` (drop the stored grant).

`--app-id io.github.iplweb.xdptype` makes the permission dialog show
"xdptype" instead of a generic name; it needs the matching `.desktop` file
(shipped by the Debian package, or copy `data/io.github.iplweb.xdptype.desktop`
to `~/.local/share/applications/`). The grant is stored per app id, so
switching ids asks once more.

Keys still held at the end are released, so a crashed script never leaves
`Shift` stuck down.

**Secrets:** pass passwords on stdin (`-`), not as arguments; command lines
are visible to every process through `/proc`.

## Permission and the restore token

The first run shows the desktop's "Remote Desktop" / "Remote control"
dialog. `xdptype` asks for keyboard-only access with `persist_mode=2` and
stores the returned restore token in
`$XDG_STATE_HOME/xdptype/restore-token` (mode 0600). Later runs present the
token and start without a dialog until you revoke the permission.

To revoke: `xdptype --forget`, and/or remove the grant in your desktop's
privacy settings.

## Tested on

- GNOME 50 (mutter, xdg-desktop-portal 1.21, xdg-desktop-portal-gnome 50),
  Ubuntu 26.04

Reports from KDE Plasma and other portal backends are welcome.

## Prior art

- [RDtype](https://github.com/Sporif/RDtype): the same idea in C++,
  KDE-focused.

## License

MIT
