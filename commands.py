"""
Command dispatcher -- shared between MQTT and serial transports.

Both transports normalize input into the same shape:
  - MQTT messages arrive as JSON, parsed into a dict by the caller.
  - Serial lines arrive as plain text; if the line parses as JSON we use it
    as a dict, otherwise we treat the whole line as the command name.

The caller supplies a `respond` callback that knows how to ship a response
dict over its transport (publish to a topic, or print to stdout). Keeping
that knowledge out of this module means we can add a third transport
(BLE, HTTP) later without touching the dispatch logic.

All commands ack synchronously where possible. Reboot and update ack first,
sleep briefly to let the ack flush, then reset -- so the controller sees
confirmation before the device disappears.
"""

import json
import time
import machine


def _parse_serial(line):
    """Serial input: try JSON first, fall back to bare command name."""
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            return json.loads(line)
        except ValueError:
            return {"cmd": line}     # malformed JSON -> treat literally
    return {"cmd": line.lower()}


def dispatch(raw, ctx):
    """
    raw: dict (parsed JSON from MQTT) or str (raw line from serial).
    ctx: {
        "respond":   callable(dict)    -- send a response over the transport,
        "read_all":  callable() -> dict -- force-read all sensors,
        "play_tone": callable(freq, ms) -> bool,
        "nid":       str               -- node_id, for status/identity replies,
    }
    """
    respond = ctx["respond"]

    if isinstance(raw, str):
        cmd = _parse_serial(raw)
        if cmd is None:
            return
    elif isinstance(raw, dict):
        cmd = raw
    else:
        respond({"ok": False, "error": "bad command type"})
        return

    name = (cmd.get("cmd") or "").lower()

    if name in ("reboot", "reset"):
        respond({"ok": True, "action": "reboot"})
        time.sleep_ms(500)             # let the ack flush over MQTT/USB
        machine.reset()

    elif name == "update":
        respond({"ok": True, "action": "update", "note": "pulling and resetting"})
        time.sleep_ms(500)
        try:
            import ugit
            ugit.pull_all()
        except Exception as e:
            print("[cmd] update failed:", repr(e))
        machine.reset()

    elif name in ("read_all", "read"):
        try:
            readings = ctx["read_all"]()
            respond({"ok": True, "readings": readings})
        except Exception as e:
            respond({"ok": False, "error": "read_all failed: {}".format(e)})

    elif name == "play_tone":
        freq = int(cmd.get("freq", 1000))
        ms   = int(cmd.get("duration_ms", 200))
        ok = ctx["play_tone"](freq, ms)
        respond({"ok": ok, "freq": freq, "duration_ms": ms,
                 "note": None if ok else "no buzzer_pin configured"})

    elif name in ("status", "ping"):
        respond({"ok": True, "status": "running", "node_id": ctx["nid"]})

    elif name in ("help", "?"):
        respond({"ok": True, "cmds": [
            "reboot", "update", "read_all",
            "play_tone (freq, duration_ms)",
            "status", "help",
        ]})

    else:
        respond({"ok": False, "error": "unknown cmd", "name": name})
