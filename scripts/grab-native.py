#!/usr/bin/env python3
"""Grab pixel color + window id on Wayland (portal) or X11."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Any


def run_cmd(args: list[str], timeout: float = 2.0) -> str:
    try:
        out = subprocess.check_output(
            args, stderr=subprocess.DEVNULL, timeout=timeout, text=True
        )
        return out.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return ""


def session_type() -> str:
    explicit = (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
    if explicit in {"wayland", "x11", "tty"}:
        return explicit
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def desktop_hint() -> str:
    raw = (
        os.environ.get("XDG_CURRENT_DESKTOP")
        or os.environ.get("DESKTOP_SESSION")
        or ""
    )
    return raw.lower()


# --- Window-under-cursor helpers ---


def format_x11_id(raw: Any) -> str:
    """Normalize to padded hex like 0x01800007."""
    if raw is None or raw == "":
        return ""
    text = str(raw).strip()
    try:
        n = int(text, 16) if text.lower().startswith("0x") else int(text)
    except ValueError:
        return ""
    return f"0x{n:08x}"


def parse_mouselocation_shell(shell: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for line in shell.splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if key == "WINDOW":
            info["windowRaw"] = val
        elif key == "X":
            try:
                info["x"] = int(val)
            except ValueError:
                pass
        elif key == "Y":
            try:
                info["y"] = int(val)
            except ValueError:
                pass
    return info


def parse_xdotool_geometry(shell: str) -> dict[str, int]:
    geom: dict[str, int] = {}
    for line in shell.splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if key in {"X", "Y", "WIDTH", "HEIGHT"}:
            try:
                geom[key.lower()] = int(val.strip())
            except ValueError:
                pass
    return geom


def parse_kdotool_geometry(text: str) -> dict[str, int]:
    geom: dict[str, int] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("position:"):
            try:
                xs, ys = line.split(":", 1)[1].split(",", 1)
                geom["x"] = int(xs.strip())
                geom["y"] = int(ys.strip())
            except ValueError:
                pass
        elif line.lower().startswith("geometry:"):
            try:
                wh = line.split(":", 1)[1].strip().lower()
                w, h = wh.split("x", 1)
                geom["width"] = int(w.strip())
                geom["height"] = int(h.strip())
            except ValueError:
                pass
    return geom


def attach_relative_coords(info: dict[str, Any]) -> dict[str, Any]:
    """Add window-relative coords when screen x/y and a window geometry are known."""
    if info.get("x") is None or info.get("y") is None:
        return info
    if info.get("relX") is not None and info.get("relY") is not None:
        return info

    win_x = win_y = None

    xid = info.get("x11WindowId") or (
        info.get("windowId") if str(info.get("windowId", "")).lower().startswith("0x") else ""
    )
    if xid and shutil.which("xdotool") and os.environ.get("DISPLAY"):
        shell = run_cmd(["xdotool", "getwindowgeometry", "--shell", str(int(str(xid), 16))])
        geom = parse_xdotool_geometry(shell)
        if "x" in geom and "y" in geom:
            win_x, win_y = geom["x"], geom["y"]
            info["windowX"] = win_x
            info["windowY"] = win_y
            if "width" in geom:
                info["windowWidth"] = geom["width"]
            if "height" in geom:
                info["windowHeight"] = geom["height"]

    if win_x is None and info.get("kdeWindowId") and shutil.which("kdotool"):
        text = run_cmd(["kdotool", "getwindowgeometry", str(info["kdeWindowId"])])
        geom = parse_kdotool_geometry(text)
        if "x" in geom and "y" in geom:
            win_x, win_y = geom["x"], geom["y"]
            info["windowX"] = win_x
            info["windowY"] = win_y
            if "width" in geom:
                info["windowWidth"] = geom["width"]
            if "height" in geom:
                info["windowHeight"] = geom["height"]

    if win_x is None or win_y is None:
        return info

    rel_x = int(info["x"]) - int(win_x)
    rel_y = int(info["y"]) - int(win_y)
    info["relX"] = rel_x
    info["relY"] = rel_y
    info["relText"] = f"{rel_x}, {rel_y}"
    info["relGeom"] = f"+{rel_x}+{rel_y}"
    return info


def window_from_xdotool() -> dict[str, Any]:
    """X11 / XWayland window id under the cursor (what tools like grabc/xwininfo use)."""
    if not shutil.which("xdotool") or not os.environ.get("DISPLAY"):
        return {}
    shell = run_cmd(["xdotool", "getmouselocation", "--shell"])
    parsed = parse_mouselocation_shell(shell)
    raw = parsed.pop("windowRaw", None)
    xid = format_x11_id(raw)
    if not xid:
        return parsed
    info: dict[str, Any] = {**parsed, "x11WindowId": xid, "windowId": xid}
    # Optional title via xdotool — never used as the id.
    name = run_cmd(["xdotool", "getwindowname", str(int(xid, 16))])
    if name:
        info["windowTitle"] = name
    return attach_relative_coords(info)


def window_from_kdotool() -> dict[str, Any]:
    info: dict[str, Any] = {}
    if not shutil.which("kdotool"):
        return info

    shell = run_cmd(["kdotool", "getmouselocation", "--shell"])
    parsed = parse_mouselocation_shell(shell)
    raw = parsed.pop("windowRaw", None)
    if raw:
        info["kdeWindowId"] = raw
    info.update(parsed)

    wid = info.get("kdeWindowId")
    if wid:
        name = run_cmd(["kdotool", "getwindowname", wid])
        cls = run_cmd(["kdotool", "getwindowclassname", wid])
        if name:
            info["windowTitle"] = name
        if cls:
            info["windowClass"] = cls
    return attach_relative_coords(info)


def window_from_hyprland() -> dict[str, Any]:
    if not shutil.which("hyprctl"):
        return {}
    pos = run_cmd(["hyprctl", "cursorpos"])
    # "123, 456"
    x = y = None
    if "," in pos:
        try:
            xs, ys = pos.split(",", 1)
            x, y = int(xs.strip()), int(ys.strip())
        except ValueError:
            pass

    raw = run_cmd(["hyprctl", "-j", "activewindow"])
    info: dict[str, Any] = {}
    if x is not None:
        info["x"] = x
        info["y"] = y
    if not raw:
        return info
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return info

    addr = data.get("address")
    if addr:
        info["windowId"] = str(addr)
        info["hyprAddress"] = str(addr)
    title = data.get("title")
    if title:
        info["windowTitle"] = title
    cls = data.get("class")
    if cls:
        info["windowClass"] = cls
    return info


def window_from_sway() -> dict[str, Any]:
    if not shutil.which("swaymsg"):
        return {}
    raw = run_cmd(["swaymsg", "-t", "get_tree"])
    if not raw:
        return {}
    try:
        tree = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    focused = {"node": None}

    def walk(node: dict[str, Any]) -> None:
        if node.get("focused"):
            focused["node"] = node
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            walk(child)

    walk(tree)
    node = focused["node"]
    if not node:
        return {}
    info: dict[str, Any] = {}
    if node.get("id") is not None:
        info["windowId"] = str(node["id"])
        info["swayId"] = str(node["id"])
    if node.get("name"):
        info["windowTitle"] = node["name"]
    app = node.get("app_id") or (node.get("window_properties") or {}).get("class")
    if app:
        info["windowClass"] = app
    return info


def sample_window_under_cursor() -> dict[str, Any]:
    """Prefer X11 hex window ids; attach compositor metadata as extras only."""
    info: dict[str, Any] = {}

    # Primary: X11/XWayland id (0x01800007 style)
    x11 = window_from_xdotool()
    if x11.get("x11WindowId"):
        info.update(x11)

    desktop = desktop_hint()
    extras: dict[str, Any] = {}
    if "kde" in desktop or "plasma" in desktop or shutil.which("kdotool"):
        extras = window_from_kdotool()
    elif "hypr" in desktop or shutil.which("hyprctl"):
        extras = window_from_hyprland()
    elif "sway" in desktop or shutil.which("swaymsg"):
        extras = window_from_sway()
    else:
        for fn in (window_from_kdotool, window_from_hyprland, window_from_sway):
            extras = fn()
            if extras:
                break

    # Merge metadata without letting UUID/title overwrite the X11 window id.
    for key, val in extras.items():
        if key in {"windowId", "x11WindowId"}:
            continue
        if key == "kdeWindowId" or info.get(key) in (None, ""):
            info[key] = val

    if not info.get("windowId") and extras.get("windowId"):
        # No X11 id available — fall back to compositor id (not a title).
        info["windowId"] = extras["windowId"]

    return attach_relative_coords(info)


_PICKER_HINTS = (
    "xdg-desktop-portal",
    "xdg_desktop_portal",
    "spectacle",
    "kwin_wayland",
    "color picker",
    "picker",
)


def _looks_like_picker(info: dict[str, Any]) -> bool:
    blob = f"{info.get('windowTitle', '')} {info.get('windowClass', '')}".lower()
    return any(h in blob for h in _PICKER_HINTS)


class WindowTracker:
    """Poll compositor for window-under-cursor while the color picker is open."""

    def __init__(self, interval: float = 0.05, history: int = 40) -> None:
        self.interval = interval
        self.history = history
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._samples: list[dict[str, Any]] = []
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="window-tracker", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            sample = sample_window_under_cursor()
            if sample.get("windowId") or sample.get("x11WindowId"):
                with self._lock:
                    self._samples.append(sample)
                    if len(self._samples) > self.history:
                        self._samples = self._samples[-self.history :]
            self._stop.wait(self.interval)

    def best(self) -> dict[str, Any]:
        with self._lock:
            samples = list(self._samples)
        if not samples:
            return {}

        # Prefer recent samples that have a real X11 id and aren't the picker overlay.
        for sample in reversed(samples):
            if sample.get("x11WindowId") and not _looks_like_picker(sample):
                return dict(sample)
        for sample in reversed(samples):
            if not _looks_like_picker(sample):
                return dict(sample)
        return dict(samples[-1])

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        return self.best()


def floats_to_hex(color: tuple[float, float, float]) -> str:
    r, g, b = color
    return f"#{int(round(r * 255)):02X}{int(round(g * 255)):02X}{int(round(b * 255)):02X}"


def hex_to_rgb_tuple(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def with_rgb(result: dict[str, Any]) -> dict[str, Any]:
    hex_color = result.get("hex")
    if not hex_color:
        return result
    r, g, b = hex_to_rgb_tuple(hex_color)
    result["rgb"] = {"r": r, "g": g, "b": b}
    result["rgbText"] = f"{r}, {g}, {b}"
    if result.get("x11WindowId"):
        result["x11WindowId"] = format_x11_id(result["x11WindowId"])
        result["windowId"] = result["x11WindowId"]
    elif result.get("windowId") and str(result["windowId"]).lower().startswith("0x"):
        result["windowId"] = format_x11_id(result["windowId"])
        result["x11WindowId"] = result["windowId"]

    # Normalize screen coordinates for the UI.
    if "x" in result and "y" in result:
        try:
            xi = int(result["x"])
            yi = int(result["y"])
            result["x"] = xi
            result["y"] = yi
            result["xyText"] = f"{xi}, {yi}"
            result["geom"] = f"+{xi}+{yi}"
        except (TypeError, ValueError):
            pass

    attach_relative_coords(result)
    if result.get("relX") is not None and result.get("relY") is not None:
        result["relText"] = f"{result['relX']}, {result['relY']}"
        result["relGeom"] = f"+{result['relX']}+{result['relY']}"
    return result


def grab_wayland_portal() -> dict[str, Any]:
    """Color via xdg-desktop-portal PickColor; window via compositor polling."""
    try:
        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        from gi.repository import GLib
    except ImportError as exc:
        raise RuntimeError(
            "Wayland grab needs python-dbus and PyGObject (gi)"
        ) from exc

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    portal = bus.get_object(
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
    )
    screenshot_iface = dbus.Interface(portal, "org.freedesktop.portal.Screenshot")

    loop = GLib.MainLoop()
    outcome: dict[str, Any] = {}

    tracker = WindowTracker()
    tracker.start()

    def on_response(response: int, results: dict[str, Any]) -> None:
        try:
            if int(response) != 0:
                outcome["error"] = "Color pick cancelled"
                return
            # Portal returns color as (ddd) in 0..1
            color = results.get("color")
            if not color or len(color) < 3:
                outcome["error"] = "Portal returned no color"
                return
            outcome["hex"] = floats_to_hex((float(color[0]), float(color[1]), float(color[2])))
        finally:
            # Brief delay so the click position is still reflected in tracker samples.
            GLib.timeout_add(120, loop.quit)

    try:
        request_path = screenshot_iface.PickColor("", {"handle_token": f"colorgrab{int(time.time())}"})
        request = bus.get_object("org.freedesktop.portal.Desktop", request_path)
        request_iface = dbus.Interface(request, "org.freedesktop.portal.Request")
        request_iface.connect_to_signal("Response", on_response)

        # Safety timeout
        GLib.timeout_add_seconds(90, loop.quit)
        loop.run()
    finally:
        window_info = tracker.stop()

    if outcome.get("error"):
        raise RuntimeError(outcome["error"])
    if not outcome.get("hex"):
        raise RuntimeError("No color from portal — is xdg-desktop-portal running?")

    result: dict[str, Any] = {
        "hex": outcome["hex"],
        "backend": "wayland-portal",
    }
    result.update(window_info)
    if not result.get("windowId") and not result.get("x11WindowId"):
        # Fallback: active/focused window after pick
        result.update(sample_window_under_cursor())
    if result.get("x") is None or result.get("y") is None:
        # Ensure screen coordinates even if window id was taken from an older sample.
        fresh = window_from_xdotool() or window_from_kdotool()
        if fresh.get("x") is not None and result.get("x") is None:
            result["x"] = fresh["x"]
        if fresh.get("y") is not None and result.get("y") is None:
            result["y"] = fresh["y"]
        if not result.get("x11WindowId") and fresh.get("x11WindowId"):
            result["x11WindowId"] = fresh["x11WindowId"]
            result["windowId"] = fresh["x11WindowId"]
    if not result.get("windowId") and not result.get("x11WindowId"):
        result["windowId"] = ""
        result["windowNote"] = "Color ok; no X11 window id under cursor"
    return with_rgb(result)


# --- X11 path ---


def make_crosshair_cursor(dpy):
    """Crosshair cursor; fall back to default pointer if glyph fonts are missing."""
    from Xlib import X

    # python-xlib has no Display.create_font_cursor on some builds — use glyph cursor.
    try:
        font = dpy.open_font("cursor")
        # XC_crosshair = 34, mask glyph is typically source+1
        return font.create_glyph_cursor(
            font,
            34,
            35,
            (0, 0, 0),
            (65535, 65535, 65535),
        )
    except Exception:
        return X.NONE


def grab_x11() -> dict[str, Any]:
    from Xlib import X, display
    from Xlib.error import XError

    dpy = display.Display()
    screen = dpy.screen()
    root = screen.root

    cursor = make_crosshair_cursor(dpy)
    grab_status = root.grab_pointer(
        owner_events=False,
        event_mask=X.ButtonPressMask,
        pointer_mode=X.GrabModeAsync,
        keyboard_mode=X.GrabModeAsync,
        confine_to=root,
        cursor=cursor,
        time=X.CurrentTime,
    )
    if grab_status != X.GrabSuccess:
        raise RuntimeError("Failed to grab pointer — is another grab active?")

    try:
        while True:
            event = dpy.next_event()
            if event.type == X.ButtonPress:
                root_x, root_y = event.root_x, event.root_y
                window = event.child if event.child != X.NONE else root
                # Descend into nested windows
                x, y = root_x, root_y
                while True:
                    try:
                        translated = window.translate_coords(root, x, y)
                    except XError:
                        break
                    child = translated.child
                    if child == X.NONE or child is None:
                        break
                    x, y = translated.x, translated.y
                    window = child
                break
    finally:
        dpy.ungrab_pointer(X.CurrentTime)
        dpy.flush()

    def sample_color() -> str | None:
        try:
            geom = window.get_geometry()
            abs_pos = window.translate_coords(root, 0, 0)
            local_x = root_x - abs_pos.x
            local_y = root_y - abs_pos.y
            local_x = max(0, min(geom.width - 1, local_x))
            local_y = max(0, min(geom.height - 1, local_y))
            image = window.get_image(local_x, local_y, 1, 1, X.ZPixmap, 0xFFFFFFFF)
            data = image.data
            if isinstance(data, bytes) and len(data) >= 4:
                b, g, r = data[0], data[1], data[2]
                return f"#{r:02X}{g:02X}{b:02X}"
        except XError:
            pass
        try:
            image = root.get_image(root_x, root_y, 1, 1, X.ZPixmap, 0xFFFFFFFF)
            data = image.data
            if isinstance(data, bytes) and len(data) >= 4:
                b, g, r = data[0], data[1], data[2]
                return f"#{r:02X}{g:02X}{b:02X}"
        except XError:
            return None
        return None

    def window_title() -> str:
        try:
            name = window.get_wm_name()
            return name or ""
        except XError:
            return ""

    color = sample_color()
    window_id = format_x11_id(window.id)
    result: dict[str, Any] = {
        "hex": color,
        "windowId": window_id,
        "x11WindowId": window_id,
        "x": root_x,
        "y": root_y,
        "backend": "x11",
    }
    title = window_title()
    if title:
        result["windowTitle"] = title

    # Relative to the clicked window from X geometry.
    try:
        geom = window.get_geometry()
        abs_pos = window.translate_coords(root, 0, 0)
        result["windowX"] = int(abs_pos.x)
        result["windowY"] = int(abs_pos.y)
        result["windowWidth"] = int(geom.width)
        result["windowHeight"] = int(geom.height)
        result["relX"] = int(root_x - abs_pos.x)
        result["relY"] = int(root_y - abs_pos.y)
    except XError:
        pass

    # KDE UUID is metadata only — never replace the X11 window id.
    kde = window_from_kdotool()
    if kde.get("kdeWindowId"):
        result["kdeWindowId"] = kde["kdeWindowId"]
    if kde.get("windowClass") and not result.get("windowClass"):
        result["windowClass"] = kde["windowClass"]
    if kde.get("windowTitle") and not result.get("windowTitle"):
        result["windowTitle"] = kde["windowTitle"]

    if not color:
        raise RuntimeError("Could not sample pixel color at click location")
    return with_rgb(result)


def grab() -> dict[str, Any]:
    kind = session_type()
    errors: list[str] = []

    if kind == "wayland":
        try:
            return grab_wayland_portal()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"wayland: {exc}")
            # XWayland fallback if DISPLAY is available
            if os.environ.get("DISPLAY"):
                try:
                    return grab_x11()
                except Exception as x11_exc:  # noqa: BLE001
                    errors.append(f"x11-fallback: {x11_exc}")
            raise RuntimeError("; ".join(errors)) from exc

    if kind == "x11" or os.environ.get("DISPLAY"):
        try:
            return grab_x11()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"x11: {exc}")
            if os.environ.get("WAYLAND_DISPLAY"):
                try:
                    return grab_wayland_portal()
                except Exception as wl_exc:  # noqa: BLE001
                    errors.append(f"wayland-fallback: {wl_exc}")
            raise RuntimeError("; ".join(errors)) from exc

    # Unknown session: try portal then X11
    try:
        return grab_wayland_portal()
    except Exception as exc:
        errors.append(f"wayland: {exc}")
    try:
        return grab_x11()
    except Exception as exc:
        errors.append(f"x11: {exc}")
    raise RuntimeError("; ".join(errors) or "No usable display backend")


def main() -> int:
    try:
        payload = grab()
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}), file=sys.stdout)
        return 1

    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
