# ColorGrab

Sample any on-screen pixel and grab the window id in the same pick. Shows HEX, RGB, HSL, window id, and X11 id when available. Recent colors stay in local storage.

## Run

```bash
npm install
npm run dev
```

Open the printed local URL (default `http://localhost:5173`).

Choose a mode, then click the main pick button:

- **Point** — color + X11 window id + screen/window coordinates
- **Rectangle** — click first corner, move (live preview), click opposite corner
- **Circle** — click center, move (live preview), click edge (Esc/right-click cancels)

### Wayland

Point mode uses the FreeDesktop **PickColor** portal for the color, and polls your compositor for the window under the cursor:

- **KDE Plasma** — `kdotool` (UUID + title/class)
- **Hyprland** — `hyprctl` (address + title/class)
- **Sway** — `swaymsg` (id + title/app_id)

Needs `xdg-desktop-portal` (and the KDE/GNOME portal package for your desktop), plus `python-dbus` and PyGObject.

### X11

Uses a crosshair click via `python-xlib` for color + X11 window id. On Plasma/XWayland it also fills the KDE window UUID when `kdotool` is present.

**Browser eyedropper** is color-only (no window id). The color well is a manual fallback.
