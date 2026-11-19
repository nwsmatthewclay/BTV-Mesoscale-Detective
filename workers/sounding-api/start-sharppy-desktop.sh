#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

mkdir -p /tmp/.X11-unix /tmp/bufkit-cache
chmod 1777 /tmp/.X11-unix

# A virtual X server lets the unmodified Qt/NSHARP desktop run headlessly.
Xvfb "$DISPLAY" -screen 0 1680x1050x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
sleep 2

openbox-session >/tmp/openbox.log 2>&1 &
OPENBOX_PID=$!

# VNC listens only on loopback; Cloudflare Worker proxies the browser's
# authenticated WebSocket to noVNC on port 6080.
x11vnc -display "$DISPLAY" -forever -shared -localhost -nopw -rfbport 5900 -quiet &
VNC_PID=$!
websockify --web=/usr/share/novnc/ 6080 127.0.0.1:5900 >/tmp/websockify.log 2>&1 &
NOVNC_PID=$!

# Launch the upstream SHARPpy desktop application, not a reimplementation.
micromamba run -n btv-sharppy-api sharppy >/tmp/sharppy-gui.log 2>&1 &
SHARPPY_PID=$!

cleanup() {
  kill "$SHARPPY_PID" "$NOVNC_PID" "$VNC_PID" "$OPENBOX_PID" "$XVFB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Keep the native FastAPI service available on port 8000 alongside the GUI.
exec micromamba run -n btv-sharppy-api uvicorn mesoscale.sharppy_service:app --host 0.0.0.0 --port 8000
