import pytest

from xdptype.cli import UsageError, parse_args, save_token, load_token
from xdptype.keysyms import char_to_keysym, key_to_keysym


@pytest.mark.parametrize(
    ("char", "keysym"),
    [
        ("a", 0x61),
        ("A", 0x41),
        ("~", 0x7E),
        ("é", 0xE9),
        ("ą", 0x01B1),  # aogonek
        ("ż", 0x01BF),  # zabovedot
        ("€", 0x20AC),  # EuroSign
        ("\n", 0xFF0D),
        ("\t", 0xFF09),
    ],
)
def test_char_to_keysym(char, keysym):
    assert char_to_keysym(char) == keysym


def test_char_to_keysym_rejects_control_chars():
    with pytest.raises(ValueError):
        char_to_keysym("\x00")


def test_key_names():
    assert key_to_keysym("Return") == 0xFF0D
    assert key_to_keysym("TAB") == 0xFF09
    assert key_to_keysym("F12") == 0xFFC9
    assert key_to_keysym("0xff1b") == 0xFF1B
    assert key_to_keysym("x") == 0x78
    with pytest.raises(ValueError):
        key_to_keysym("NoSuchKey")


def test_actions_keep_order():
    opts = parse_args(["user", "-k", "Tab", "-", "-k", "Return", "-s", "50"])
    assert opts.actions == [
        ("text", "user"),
        ("tap", 0xFF09),
        ("stdin", None),
        ("tap", 0xFF0D),
        ("sleep", 0.05),
    ]


def test_options():
    opts = parse_args(["-d", "10", "--delay", "2", "--app-id", "a.b.c", "hi"])
    assert opts.key_delay == 0.01
    assert opts.start_delay == 2.0
    assert opts.app_id == "a.b.c"


def test_double_dash_types_rest_literally():
    assert parse_args(["--", "-k", "-"]).actions == [("text", "-k"), ("text", "-")]


@pytest.mark.parametrize("argv", [[], ["-k"], ["-k", "Nope"], ["--bogus", "x"]])
def test_usage_errors(argv):
    with pytest.raises(UsageError):
        parse_args(argv)


def test_token_roundtrip(tmp_path):
    path = tmp_path / "sub" / "restore-token"
    assert load_token(path) is None
    save_token(path, "abc")
    assert load_token(path) == "abc"
    assert path.stat().st_mode & 0o777 == 0o600


def test_char_to_keysym_without_xkbcommon(monkeypatch):
    from xdptype import keysyms

    monkeypatch.setattr(keysyms, "_xkb_utf32_to_keysym", lambda: None)
    assert keysyms.char_to_keysym("ą") == 0x01000105
    assert keysyms.char_to_keysym("é") == 0xE9


def test_char_without_legacy_keysym_uses_unicode_range():
    assert char_to_keysym("\u2603") == 0x01002603  # snowman


def test_char_to_strokes_shifts_non_ascii_uppercase():
    from xdptype.keysyms import char_to_strokes

    assert char_to_strokes("Ą") == (0x01B1, True)
    assert char_to_strokes("Ź") == (char_to_keysym("ź"), True)
    assert char_to_strokes("A") == (0x41, False)
    assert char_to_strokes("ą") == (0x01B1, False)
    assert char_to_strokes("1") == (0x31, False)
