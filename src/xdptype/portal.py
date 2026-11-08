"""Minimal client for the xdg-desktop-portal RemoteDesktop interface.

Only the keyboard part is implemented: a session is created with
``types=KEYBOARD`` and ``persist_mode=2``, so after the user approves the
dialog once, the returned restore token lets later sessions start without
asking again (until the permission is revoked in the desktop settings).
"""

from __future__ import annotations

import secrets
import sys
import time

from jeepney import DBusAddress, DBusErrorResponse, MatchRule, new_method_call
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import DBusConnection, Proxy, open_dbus_connection
from jeepney.wrappers import unwrap_msg

BUS_NAME = "org.freedesktop.portal.Desktop"
OBJECT_PATH = "/org/freedesktop/portal/desktop"
REMOTE_DESKTOP = DBusAddress(
    OBJECT_PATH, bus_name=BUS_NAME, interface="org.freedesktop.portal.RemoteDesktop"
)
HOST_REGISTRY = DBusAddress(
    OBJECT_PATH, bus_name=BUS_NAME, interface="org.freedesktop.host.portal.Registry"
)

DEVICE_KEYBOARD = 1
PERSIST_UNTIL_REVOKED = 2

KEY_RELEASED = 0
KEY_PRESSED = 1


class PortalError(Exception):
    """The portal refused or failed a request."""


class PortalCancelled(PortalError):
    """The user dismissed the permission dialog."""


class KeyboardSession:
    """A RemoteDesktop portal session that can send keysyms.

    Use as a context manager; the session is closed on exit.
    """

    def __init__(
        self,
        restore_token: str | None = None,
        app_id: str | None = None,
        timeout: float | None = 300.0,
    ) -> None:
        self._restore_token_in = restore_token
        self._app_id = app_id
        self._timeout = timeout
        self._conn: DBusConnection | None = None
        self._session: str | None = None
        self.restore_token: str | None = None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> KeyboardSession:
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def open(self) -> None:
        self._conn = open_dbus_connection(bus="SESSION")
        if self._app_id:
            self._register_app_id(self._app_id)

        results = self._request(
            REMOTE_DESKTOP,
            "CreateSession",
            "a{sv}",
            lambda opts: ({**opts, "session_handle_token": ("s", _token())},),
        )
        self._session = results["session_handle"][1]

        def select_devices(opts: dict) -> tuple:
            opts = {
                **opts,
                "types": ("u", DEVICE_KEYBOARD),
                "persist_mode": ("u", PERSIST_UNTIL_REVOKED),
            }
            if self._restore_token_in:
                opts["restore_token"] = ("s", self._restore_token_in)
            return (self._session, opts)

        self._request(REMOTE_DESKTOP, "SelectDevices", "oa{sv}", select_devices)

        results = self._request(
            REMOTE_DESKTOP,
            "Start",
            "osa{sv}",
            lambda opts: (self._session, "", opts),
        )
        devices = results.get("devices", ("u", 0))[1]
        if not devices & DEVICE_KEYBOARD:
            raise PortalError("portal did not grant keyboard access")
        if "restore_token" in results:
            self.restore_token = results["restore_token"][1]

    def close(self) -> None:
        if self._conn is None:
            return
        try:
            if self._session is not None:
                session = DBusAddress(
                    self._session,
                    bus_name=BUS_NAME,
                    interface="org.freedesktop.portal.Session",
                )
                unwrap_msg(
                    self._conn.send_and_get_reply(new_method_call(session, "Close"))
                )
        finally:
            self._conn.close()
            self._conn = None
            self._session = None

    # -- input -------------------------------------------------------------

    def keysym(self, keysym: int, pressed: bool) -> None:
        assert self._conn is not None and self._session is not None
        state = KEY_PRESSED if pressed else KEY_RELEASED
        msg = new_method_call(
            REMOTE_DESKTOP,
            "NotifyKeyboardKeysym",
            "oa{sv}iu",
            (self._session, {}, keysym, state),
        )
        unwrap_msg(self._conn.send_and_get_reply(msg))

    def tap(self, keysym: int, key_delay: float = 0.0) -> None:
        self.keysym(keysym, True)
        if key_delay:
            time.sleep(key_delay)
        self.keysym(keysym, False)
        if key_delay:
            time.sleep(key_delay)

    # -- internals ---------------------------------------------------------

    def _register_app_id(self, app_id: str) -> None:
        """Tell the portal who we are (host apps have no app id otherwise).

        Must happen before any other portal call on this connection. Older
        portals lack the interface; that only costs us a nicer dialog, so a
        D-Bus error here is not fatal.
        """
        assert self._conn is not None
        msg = new_method_call(HOST_REGISTRY, "Register", "sa{sv}", (app_id, {}))
        reply = self._conn.send_and_get_reply(msg)
        try:
            unwrap_msg(reply)
        except DBusErrorResponse as e:
            print(
                f"xdptype: could not register app id {app_id!r}: {e}", file=sys.stderr
            )

    def _request(self, address: DBusAddress, method: str, signature: str, build_args):
        """Call a portal method that answers through a Request object.

        The Response signal is subscribed to *before* the call, on the
        predictable request path, so a fast reply cannot be missed.
        """
        assert self._conn is not None
        handle_token = _token()
        sender = self._conn.unique_name.lstrip(":").replace(".", "_")
        request_path = f"{OBJECT_PATH}/request/{sender}/{handle_token}"
        rule = MatchRule(
            type="signal",
            interface="org.freedesktop.portal.Request",
            member="Response",
            path=request_path,
        )
        Proxy(message_bus, self._conn).AddMatch(rule)
        try:
            with self._conn.filter(rule) as queue:
                args = build_args({"handle_token": ("s", handle_token)})
                msg = new_method_call(address, method, signature, args)
                unwrap_msg(self._conn.send_and_get_reply(msg))
                signal = self._conn.recv_until_filtered(queue, timeout=self._timeout)
        finally:
            Proxy(message_bus, self._conn).RemoveMatch(rule)

        response, results = signal.body
        if response == 1:
            raise PortalCancelled(f"{method}: cancelled by the user")
        if response != 0:
            raise PortalError(f"{method}: portal returned response code {response}")
        return results


def _token() -> str:
    return "xdptype_" + secrets.token_hex(8)
