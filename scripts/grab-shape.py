#!/usr/bin/env python3
"""Click-drag rectangle / circle region grab over existing windows (X11/XWayland)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import time
from typing import Any


def run_cmd(args: list[str], timeout: float = 2.0) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        return 1, "", str(exc)


def load_native():
    path = os.path.join(os.path.dirname(__file__), "grab-native.py")
    spec = importlib.util.spec_from_file_location("grab_native", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load grab-native.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def enrich_window_at(native, x: int, y: int) -> dict[str, Any]:
    """Best-effort window id / relative coords for a screen point."""
    info: dict[str, Any] = {"x": x, "y": y}
    sample = native.sample_window_under_cursor()
    if sample:
        for key, val in sample.items():
            if key in {"x", "y"}:
                continue
            info[key] = val
    info["x"] = x
    info["y"] = y
    return native.attach_relative_coords(info)


def copy_window_fields(result: dict[str, Any], win: dict[str, Any]) -> None:
    for key in (
        "windowId",
        "x11WindowId",
        "kdeWindowId",
        "windowTitle",
        "windowClass",
        "relX",
        "relY",
        "relText",
        "relGeom",
        "windowX",
        "windowY",
        "windowWidth",
        "windowHeight",
    ):
        if key in win and win[key] not in (None, ""):
            result[key] = win[key]
    if result.get("x11WindowId"):
        result["windowId"] = result["x11WindowId"]


def finalize_rect(native, x: int, y: int, w: int, h: int, backend: str) -> dict[str, Any]:
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    x2, y2 = x + w, y + h
    cx, cy = x + w / 2, y + h / 2
    result: dict[str, Any] = {
        "shape": "rect",
        "backend": backend,
        "x": int(x),
        "y": int(y),
        "width": int(w),
        "height": int(h),
        "x2": int(x2),
        "y2": int(y2),
        "cx": round(cx, 2),
        "cy": round(cy, 2),
        "xyText": f"{int(x)}, {int(y)}",
        "sizeText": f"{int(w)}×{int(h)}",
        "geom": f"{int(w)}x{int(h)}+{int(x)}+{int(y)}",
        "boxText": f"{int(x)},{int(y)} → {int(x2)},{int(y2)}",
    }
    copy_window_fields(result, enrich_window_at(native, int(round(cx)), int(round(cy))))
    return result


def finalize_circle(native, cx: float, cy: float, r: float, backend: str) -> dict[str, Any]:
    r = abs(float(r))
    x = int(round(cx - r))
    y = int(round(cy - r))
    d = int(round(r * 2))
    result: dict[str, Any] = {
        "shape": "circle",
        "backend": backend,
        "cx": round(float(cx), 2),
        "cy": round(float(cy), 2),
        "r": round(float(r), 2),
        "diameter": round(float(r) * 2, 2),
        "x": x,
        "y": y,
        "width": d,
        "height": d,
        "x2": x + d,
        "y2": y + d,
        "centerText": f"{round(float(cx), 2)}, {round(float(cy), 2)}",
        "radiusText": f"{round(float(r), 2)}",
        "sizeText": f"r={round(float(r), 2)}",
        "geom": f"{d}x{d}+{x}+{y}",
        "boxText": f"center {round(float(cx), 2)},{round(float(cy), 2)} r={round(float(r), 2)}",
    }
    win = enrich_window_at(native, int(round(cx)), int(round(cy)))
    copy_window_fields(result, win)
    if result.get("windowX") is not None and result.get("windowY") is not None:
        result["relCx"] = round(float(cx) - float(result["windowX"]), 2)
        result["relCy"] = round(float(cy) - float(result["windowY"]), 2)
        result["relCenterText"] = f"{result['relCx']}, {result['relCy']}"
    return result


def _alloc_color(colormap, rgb_8: tuple[int, int, int]):
    from Xlib import X

    r, g, b = rgb_8
    color = colormap.alloc_color(r * 257, g * 257, b * 257)
    return color.pixel


def grab_two_click_x11(mode: str, native) -> dict[str, Any]:
    """
    Two-click selection using a root pointer grab (same coordinate space as
    color pick). Feedback is a small moving border window — no fullscreen
    overlay, so XWayland cannot remap click coordinates.
    """
    from Xlib import XK, X, display
    from Xlib.ext import shape

    if not os.environ.get("DISPLAY"):
        raise RuntimeError("Shape grab needs an X11/XWayland DISPLAY (same as color pick)")

    dpy = display.Display()
    screen = dpy.screen()
    root = screen.root
    cursor = native.make_crosshair_cursor(dpy)
    cmap = screen.default_colormap
    try:
        mint = _alloc_color(cmap, (61, 255, 168))
        soft = _alloc_color(cmap, (232, 240, 248))
        hud_bg = _alloc_color(cmap, (10, 14, 20))
    except Exception:
        mint = screen.white_pixel
        soft = screen.white_pixel
        hud_bg = screen.black_pixel

    # Tiny HUD label (not fullscreen).
    hud = root.create_window(
        16,
        16,
        520,
        36,
        0,
        screen.root_depth,
        X.InputOutput,
        X.CopyFromParent,
        background_pixel=hud_bg,
        border_pixel=mint,
        override_redirect=1,
        event_mask=X.ExposureMask,
    )
    hud.configure(border_width=1)
    hud_gc = hud.create_gc(foreground=soft)
    try:
        font = dpy.open_font("-*-fixed-medium-r-*-*-13-*-*-*-*-*-*-*")
        hud_gc.change(font=font)
    except Exception:
        pass
    hud.map()

    # Feedback window: reshaped into a hollow rect / circle ring as you move.
    feedback = root.create_window(
        0,
        0,
        1,
        1,
        0,
        screen.root_depth,
        X.InputOutput,
        X.CopyFromParent,
        background_pixel=mint,
        override_redirect=1,
        event_mask=0,
    )
    border = 3

    event_mask = X.ButtonPressMask | X.ButtonReleaseMask | X.PointerMotionMask
    status = root.grab_pointer(
        owner_events=False,
        event_mask=event_mask,
        pointer_mode=X.GrabModeAsync,
        keyboard_mode=X.GrabModeAsync,
        confine_to=X.NONE,
        cursor=cursor,
        time=X.CurrentTime,
    )
    if status != X.GrabSuccess:
        try:
            hud.destroy()
            feedback.destroy()
        except Exception:
            pass
        raise RuntimeError("Failed to grab pointer — is another grab active?")

    try:
        root.grab_keyboard(False, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)
        kb_grabbed = True
    except Exception:
        kb_grabbed = False

    esc = dpy.keysym_to_keycode(XK.string_to_keysym("Escape"))

    anchored = False
    x0 = y0 = x1 = y1 = 0
    outcome: dict[str, Any] = {}
    min_size = 4
    started_at = time.time()
    ignore_until = started_at + 0.35
    press_xy = {"xy": None}
    feedback_mapped = False

    def root_xy(event) -> tuple[int, int]:
        return int(event.root_x), int(event.root_y)

    def hud_text() -> str:
        if not anchored:
            return (
                "Click first corner · Esc/right-click cancel"
                if mode == "rect"
                else "Click circle center · Esc/right-click cancel"
            )
        if mode == "rect":
            w, h = abs(x1 - x0), abs(y1 - y0)
            return f"Rect {w}x{h} @ {min(x0, x1)},{min(y0, y1)} · click to finish"
        r = int(round(math.hypot(x1 - x0, y1 - y0)))
        return f"Circle r={r} @ {x0},{y0} · click edge to finish"

    def paint_hud():
        geom = hud.get_geometry()
        hud.clear_area(0, 0, geom.width, geom.height)
        try:
            hud.draw_text(hud_gc, 10, 24, hud_text())
        except Exception:
            pass
        dpy.flush()

    def update_feedback():
        nonlocal feedback_mapped
        if not anchored:
            if feedback_mapped:
                feedback.unmap()
                feedback_mapped = False
            return

        if mode == "rect":
            left, right = sorted((x0, x1))
            top, bottom = sorted((y0, y1))
            w, h = max(1, right - left), max(1, bottom - top)
            feedback.configure(x=left, y=top, width=w, height=h)
            # Hollow ring via SHAPE so desktop stays visible inside.
            pix = feedback.create_pixmap(w, h, 1)
            on = pix.create_gc(foreground=1)
            off = pix.create_gc(foreground=0)
            pix.fill_rectangle(off, 0, 0, w, h)
            pix.fill_rectangle(on, 0, 0, w, h)
            if w > border * 2 and h > border * 2:
                pix.fill_rectangle(off, border, border, w - border * 2, h - border * 2)
            feedback.shape_mask(shape.SO.Set, shape.SK.Bounding, 0, 0, pix)
            try:
                pix.free()
            except Exception:
                pass
        else:
            r = max(1, int(round(math.hypot(x1 - x0, y1 - y0))))
            left, top = x0 - r, y0 - r
            size = r * 2
            feedback.configure(x=left, y=top, width=max(1, size), height=max(1, size))
            pix = feedback.create_pixmap(max(1, size), max(1, size), 1)
            on = pix.create_gc(foreground=1)
            off = pix.create_gc(foreground=0)
            pix.fill_rectangle(off, 0, 0, size, size)
            pix.fill_arc(on, 0, 0, size, size, 0, 360 * 64)
            inner = max(0, r - border)
            if inner > 0:
                pix.fill_arc(
                    off,
                    r - inner,
                    r - inner,
                    inner * 2,
                    inner * 2,
                    0,
                    360 * 64,
                )
            feedback.shape_mask(shape.SO.Set, shape.SK.Bounding, 0, 0, pix)
            try:
                pix.free()
            except Exception:
                pass

        if not feedback_mapped:
            feedback.map()
            feedback_mapped = True
        feedback.raise_window()
        dpy.flush()

    def handle_click(px: int, py: int) -> bool:
        nonlocal anchored, x0, y0, x1, y1, outcome
        if not anchored:
            anchored = True
            x0 = x1 = px
            y0 = y1 = py
            paint_hud()
            update_feedback()
            return False

        x1, y1 = px, py
        if mode == "rect":
            if abs(x1 - x0) < min_size and abs(y1 - y0) < min_size:
                return False
            outcome = {
                "x": x0,
                "y": y0,
                "w": x1 - x0,
                "h": y1 - y0,
                "backend": "x11-two-click",
            }
            return True

        if math.hypot(x1 - x0, y1 - y0) < min_size:
            return False
        outcome = {
            "cx": x0,
            "cy": y0,
            "r": math.hypot(x1 - x0, y1 - y0),
            "backend": "x11-two-click",
        }
        return True

    try:
        paint_hud()
        print(
            "Two-click select · root coords · Esc / right-click cancel",
            file=sys.stderr,
        )
        while True:
            event = dpy.next_event()

            if event.type == X.Expose:
                paint_hud()
                continue

            if event.type == X.KeyPress and esc and event.detail == esc:
                raise RuntimeError("Selection cancelled")

            if event.type == X.ButtonPress and event.detail == 3:
                raise RuntimeError("Selection cancelled")

            if event.type == X.MotionNotify:
                if not anchored:
                    continue
                x1, y1 = root_xy(event)
                paint_hud()
                update_feedback()
                continue

            if event.type in (X.ButtonPress, X.ButtonRelease) and event.detail == 1:
                if time.time() < ignore_until:
                    continue
                if event.type == X.ButtonPress:
                    press_xy["xy"] = root_xy(event)
                    continue
                if press_xy["xy"] is None:
                    continue
                # Use press position (aim point); fall back to release if needed.
                px, py = press_xy["xy"]
                press_xy["xy"] = None
                if handle_click(px, py):
                    break
    finally:
        dpy.ungrab_pointer(X.CurrentTime)
        if kb_grabbed:
            try:
                dpy.ungrab_keyboard(X.CurrentTime)
            except Exception:
                pass
        for win in (feedback, hud):
            try:
                win.unmap()
                win.destroy()
            except Exception:
                pass
        dpy.flush()

    return outcome


def grab_rect(native) -> dict[str, Any]:
    picked = grab_two_click_x11("rect", native)
    return finalize_rect(
        native, picked["x"], picked["y"], picked["w"], picked["h"], picked["backend"]
    )


def grab_circle(native) -> dict[str, Any]:
    picked = grab_two_click_x11("circle", native)
    return finalize_circle(native, picked["cx"], picked["cy"], picked["r"], picked["backend"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Grab rectangle or circle region coordinates")
    parser.add_argument("--mode", choices=("rect", "circle"), required=True)
    args = parser.parse_args()

    try:
        native = load_native()
        if args.mode == "rect":
            payload = grab_rect(native)
        else:
            payload = grab_circle(native)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}))
        return 1

    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
