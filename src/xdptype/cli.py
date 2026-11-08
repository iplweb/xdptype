"""Command line interface, modelled on wtype(1).

Arguments are processed in order, so text and keys can be interleaved::

    xdptype "user" -k Tab - -k Return   # "-" reads text from stdin
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from jeepney import DBusErrorResponse

from . import __version__
from .keysyms import SHIFT, char_to_keysym, char_to_strokes, key_to_keysym
from .portal import KeyboardSession, PortalCancelled, PortalError


USAGE = """\
usage: xdptype [options] [TEXT | -k KEY | -P KEY | -p KEY | -s MS | -] ...

Type text on Wayland through the xdg-desktop-portal RemoteDesktop portal.
The first run shows a permission dialog; the grant is remembered.

actions (executed in order):
  TEXT          type TEXT
  -             type text read from standard input (use this for secrets,
                argv is visible to other processes)
  -k KEY        press and release KEY (Return, Tab, Escape, F5, 0xff0d, a, ...)
  -P KEY        press KEY (held until -p KEY or the end)
  -p KEY        release KEY
  -M MOD        alias for -P (wtype compatibility)
  -m MOD        alias for -p (wtype compatibility)
  -s MS         sleep MS milliseconds

options:
  -d MS         delay between key events in milliseconds (default: 0)
  --delay SEC   wait SEC seconds before typing (time to focus a window)
  --app-id ID   register ID with the portal first (needs a matching
                ID.desktop file; the dialog then shows its name)
  --forget      delete the stored restore token and exit
  -h, --help    show this help and exit
  --version     show version and exit
"""


@dataclass
class Options:
    actions: list[tuple[str, object]] = field(default_factory=list)
    key_delay: float = 0.0
    start_delay: float = 0.0
    app_id: str | None = None
    forget: bool = False


class UsageError(Exception):
    pass


def parse_args(argv: list[str]) -> Options:
    opts = Options()
    args = iter(argv)

    def value(flag: str) -> str:
        try:
            return next(args)
        except StopIteration:
            raise UsageError(f"{flag} requires an argument") from None

    def number(flag: str) -> float:
        raw = value(flag)
        try:
            return float(raw)
        except ValueError:
            raise UsageError(f"{flag}: not a number: {raw!r}") from None

    def key(flag: str) -> int:
        raw = value(flag)
        try:
            return key_to_keysym(raw)
        except ValueError as e:
            raise UsageError(f"{flag}: {e}") from None

    for arg in args:
        if arg in ("-h", "--help"):
            print(USAGE, end="")
            raise SystemExit(0)
        if arg == "--version":
            print(f"xdptype {__version__}")
            raise SystemExit(0)
        if arg == "--":
            opts.actions.extend(("text", rest) for rest in args)
            break
        if arg == "-":
            opts.actions.append(("stdin", None))
        elif arg == "-k":
            opts.actions.append(("tap", key(arg)))
        elif arg in ("-P", "-M"):
            opts.actions.append(("press", key(arg)))
        elif arg in ("-p", "-m"):
            opts.actions.append(("release", key(arg)))
        elif arg == "-s":
            opts.actions.append(("sleep", number(arg) / 1000))
        elif arg == "-d":
            opts.key_delay = number(arg) / 1000
        elif arg == "--delay":
            opts.start_delay = number(arg)
        elif arg == "--app-id":
            opts.app_id = value(arg)
        elif arg == "--forget":
            opts.forget = True
        elif arg.startswith("-") and len(arg) > 1:
            raise UsageError(f"unknown option {arg!r}")
        else:
            opts.actions.append(("text", arg))

    if not opts.actions and not opts.forget:
        raise UsageError("nothing to type")
    return opts


def token_path() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(state) / "xdptype" / "restore-token"


def load_token(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except FileNotFoundError:
        return None


def save_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    os.replace(tmp, path)


def resolve_text(opts: Options) -> list[tuple[str, object]]:
    """Read stdin once, up front, so typing is not interleaved with I/O."""
    actions = []
    for kind, arg in opts.actions:
        if kind == "stdin":
            text = sys.stdin.read()
            # A trailing newline from `echo`/`printf '%s\n'` is almost never
            # meant to be typed (it would submit forms); use -k Return.
            if text.endswith("\n"):
                text = text[:-1]
            actions.append(("text", text))
        else:
            actions.append((kind, arg))
    for kind, arg in actions:
        if kind == "text":
            for char in arg:
                try:
                    char_to_keysym(char)
                except ValueError as e:
                    raise UsageError(str(e)) from None
    return actions


def run(opts: Options) -> None:
    path = token_path()
    if opts.forget:
        path.unlink(missing_ok=True)
        return

    actions = resolve_text(opts)
    held: list[int] = []

    with KeyboardSession(restore_token=load_token(path), app_id=opts.app_id) as kbd:
        if kbd.restore_token:
            save_token(path, kbd.restore_token)
        if opts.start_delay:
            time.sleep(opts.start_delay)
        try:
            for kind, arg in actions:
                if kind == "text":
                    for char in arg:
                        keysym, shift = char_to_strokes(char)
                        if shift:
                            kbd.keysym(SHIFT, True)
                        try:
                            kbd.tap(keysym, opts.key_delay)
                        finally:
                            if shift:
                                kbd.keysym(SHIFT, False)
                elif kind == "tap":
                    kbd.tap(arg, opts.key_delay)
                elif kind == "press":
                    kbd.keysym(arg, True)
                    held.append(arg)
                elif kind == "release":
                    kbd.keysym(arg, False)
                    if arg in held:
                        held.remove(arg)
                elif kind == "sleep":
                    time.sleep(arg)
        finally:
            # Never leave a modifier stuck down on the user's desktop.
            for keysym in reversed(held):
                kbd.keysym(keysym, False)


def main(argv: list[str] | None = None) -> int:
    try:
        opts = parse_args(sys.argv[1:] if argv is None else argv)
        run(opts)
    except UsageError as e:
        print(f"xdptype: {e}\nTry 'xdptype --help'.", file=sys.stderr)
        return 2
    except PortalCancelled as e:
        print(f"xdptype: {e}", file=sys.stderr)
        return 1
    except (PortalError, DBusErrorResponse, ConnectionError, TimeoutError) as e:
        print(f"xdptype: {e}", file=sys.stderr)
        return 1
    return 0
