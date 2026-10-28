#!/usr/bin/env python3
"""foundry-iphone-mirror MCP server (Python 3 standard library only).

Exposes the iphone-mirror CLI as typed MCP tools so any MCP client (Claude Code,
Claude Desktop, other agents) can drive a real iPhone through macOS iPhone
Mirroring. iphone_screenshot returns the PNG inline, so the model sees the phone
without a separate file read.

THIN WRAPPER: this server holds no permissions. Every action shells out to
bin/iphone-mirror, which launches the TCC-granted helper app per action.

Transport: MCP over stdio, newline-delimited JSON-RPC 2.0.

Canonical loop (never tap blind):
    iphone_screenshot()   look (records the geometry iphone_tap relies on)
    iphone_tap(px, py)    act on a pixel you saw in that screenshot
    iphone_screenshot()   verify the screen changed
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from typing import Any, Callable

SERVER_NAME = "iphone"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL = "2025-06-18"

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.environ.get("IPHONE_MIRROR_CLI") or os.path.join(os.path.dirname(HERE), "bin", "iphone-mirror")


def _state_dir() -> str:
    """Same rule as bin/iphone-mirror: the helper app cannot receive environment
    variables, so IPHONE_MIRROR_STATE only applies to the in-process test worker."""
    default = os.path.expanduser("~/Library/Caches/foundry-iphone-mirror")
    if os.environ.get("IPHONE_MIRROR_WORKER_DIRECT"):
        return os.environ.get("IPHONE_MIRROR_STATE") or default
    return default


# Every tool that acts on the phone carries this, because the model often calls
# these tools without loading the iphone-mirror skill first.
GATE = (" Rules: run iphone_doctor first and stop on any [FAIL]; act on the phone only for a task the user "
        "asked for (their go-ahead), and never buy, send, delete or change account settings unless they named "
        "that exact action.")


def run_cli(*args: str, timeout: int = 60) -> tuple[int, str]:
    """Run the CLI; return (returncode, combined output)."""
    try:
        p = subprocess.run([CLI, *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, f"iphone-mirror CLI not found at {CLI} (set IPHONE_MIRROR_CLI)"
    except PermissionError:
        return 126, f"iphone-mirror CLI at {CLI} is not executable (chmod +x it)"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s: iphone-mirror {' '.join(args)}"
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    return p.returncode, out


def text_result(rc: int, out: str) -> dict:
    msg = out if rc == 0 else f"[rc={rc}] {out or 'failed'}"
    return {"content": [{"type": "text", "text": msg}], "isError": rc != 0}


# ---- tools -----------------------------------------------------------------

def _int(args: dict, key: str) -> str:
    v = args.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
        raise ValueError(f"'{key}' must be an integer pixel coordinate, got {v!r}")
    return str(int(v))


def t_doctor(_: dict) -> dict:
    return text_result(*run_cli("doctor", timeout=120))


def t_open(_: dict) -> dict:
    return text_result(*run_cli("open"))


def t_info(_: dict) -> dict:
    return text_result(*run_cli("info"))


def t_screenshot(_: dict) -> dict:
    out_path = os.path.join(_state_dir(), "shots", "mcp_shot.png")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    try:
        os.remove(out_path)
    except FileNotFoundError:
        pass
    rc, out = run_cli("shot", out_path)
    if rc != 0 or not os.path.exists(out_path):
        return text_result(rc or 1, out or "screenshot failed")
    with open(out_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    return {
        "content": [
            {"type": "text", "text": out + "\nTap targets are pixel coords in THIS image (top-left origin)."},
            {"type": "image", "data": data, "mimeType": "image/png"},
        ],
        "isError": False,
    }


def t_tap(a: dict) -> dict:
    return text_result(*run_cli("tap", _int(a, "px"), _int(a, "py")))


def t_tapxy(a: dict) -> dict:
    return text_result(*run_cli("tapxy", _int(a, "gx"), _int(a, "gy")))


def t_swipe(a: dict) -> dict:
    return text_result(*run_cli("swipe", _int(a, "px1"), _int(a, "py1"), _int(a, "px2"), _int(a, "py2")))


def t_type(a: dict) -> dict:
    text = a.get("text")
    if not isinstance(text, str) or not text:
        raise ValueError("'text' must be a non-empty string")
    return text_result(*run_cli("type", text))


def t_key(a: dict) -> dict:
    name = a.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("'name' must be a key name such as return, esc, tab, space")
    return text_result(*run_cli("key", name))


def t_home(_: dict) -> dict:
    return text_result(*run_cli("home"))


def _schema(props: dict[str, str] | None = None, kind: str = "integer") -> dict:
    props = props or {}
    return {
        "type": "object",
        "properties": {k: {"type": kind, "description": d} for k, d in props.items()},
        "required": list(props),
        "additionalProperties": False,
    }


TOOLS: dict[str, tuple[str, dict, Callable[[dict], dict]]] = {
    "iphone_doctor": (
        "Preflight a real iPhone setup; read-only, touches nothing. Checks macOS version, iPhone Mirroring "
        "installed and running, cliclick, the helper app, and all three permissions the helper app needs "
        "(Accessibility, Screen Recording, and Automation to control System Events), tested THROUGH the "
        "helper app. Run this FIRST, before any other iphone_* tool. If any line is [FAIL], stop and tell the "
        "user the exact fix from that line; granting a permission is a step only the user can do in System "
        "Settings, never try to click it yourself. Load the foundry-iphone-mirror:iphone-mirror skill for the "
        "full screenshot, act, verify loop.",
        _schema(), t_doctor),
    "iphone_open": (
        "Launch and focus iPhone Mirroring. If the mirror shows a connect, passcode or 'iPhone in Use' "
        "screen, the user must act on the physical phone: report it, do not keep tapping." + GATE,
        _schema(), t_open),
    "iphone_info": (
        "Return the iPhone Mirroring window geometry in screen points (x y width height). Debug only; it does "
        "not raise the window or touch the phone. Note: this resets the pixel mapping, so take a fresh "
        "screenshot before the next tap.",
        _schema(), t_info),
    "iphone_screenshot": (
        "Screenshot the iPhone Mirroring window and return the PNG inline. Pick tap targets by their pixel "
        "position in THIS image (top-left origin). It also records the geometry that iphone_tap and "
        "iphone_swipe use, so screenshot before acting and again after every action to verify. It brings the "
        "Mirroring window to the front." + GATE,
        _schema(), t_screenshot),
    "iphone_tap": (
        "Tap at a pixel coordinate from the LAST iphone_screenshot. Verify with another screenshot." + GATE,
        _schema({"px": "x pixel in the last screenshot", "py": "y pixel in the last screenshot"}), t_tap),
    "iphone_swipe": (
        "Drag from one screenshot pixel to another (scroll a list, move a slider). Pixels from the last "
        "iphone_screenshot. To scroll content up, drag from a lower y to a higher-up y." + GATE,
        _schema({"px1": "start x", "py1": "start y", "px2": "end x", "py2": "end y"}), t_swipe),
    "iphone_type": (
        "Type literal text into the focused field. Tap the field first and confirm the cursor or keyboard "
        "in a screenshot. Keystrokes show on the mirror, so avoid typing secrets." + GATE,
        _schema({"text": "the text to type"}, kind="string"), t_type),
    "iphone_key": (
        "Press one named key: return, esc, tab, space, delete, arrow-up, arrow-down, arrow-left, arrow-right."
        + GATE,
        _schema({"name": "key name"}, kind="string"), t_key),
    "iphone_home": (
        "Perform the swipe-up home gesture to return to the home screen." + GATE,
        _schema(), t_home),
    "iphone_tapxy": (
        "Tap at an ABSOLUTE global screen point (screen points, not screenshot pixels). Rarely needed; "
        "prefer iphone_tap." + GATE,
        _schema({"gx": "global x in screen points", "gy": "global y in screen points"}), t_tapxy),
}


# ---- JSON-RPC plumbing -----------------------------------------------------

def handle(msg: dict) -> dict | None:
    """Handle one JSON-RPC message; return the response, or None for notifications."""
    mid = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params") or {}
    is_notification = "id" not in msg

    def ok(result: Any) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    if is_notification:
        return None
    if method == "initialize":
        return ok({
            "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": "Drive a real iPhone via macOS iPhone Mirroring. Always iphone_doctor first, then "
                            "loop: iphone_screenshot, act on pixels from that shot, iphone_screenshot to verify.",
        })
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [
            {"name": n, "description": d, "inputSchema": s} for n, (d, s, _) in TOOLS.items()
        ]})
    if method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            return err(-32602, f"unknown tool: {name}")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return err(-32602, "arguments must be an object")
        try:
            return ok(TOOLS[name][2](args))
        except ValueError as e:
            return ok({"content": [{"type": "text", "text": f"invalid arguments: {e}"}], "isError": True})
    return err(-32601, f"method not found: {method}")


def serve(stdin=sys.stdin, stdout=sys.stdout) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            resp: dict | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {e}"}}
        else:
            if isinstance(msg, list):  # batch (older protocol revisions)
                out = [r for r in (handle(m) for m in msg if isinstance(m, dict)) if r is not None]
                resp = out or None  # type: ignore[assignment]
            elif isinstance(msg, dict):
                resp = handle(msg)
            else:
                resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        if resp is not None:
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
