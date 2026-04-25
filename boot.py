"""
boot.py -- runs once at power-on, before main.py.

Responsibilities, in order:
  1. Hand off to ugit for Wi-Fi connect + OTA pull. ugit reads /config.json
     for SSID, password, GitHub user/repo/branch, and ignore list.
  2. If ugit fails (no network, GitHub down, malformed config), log and continue
     -- main.py still needs to run so the node can collect data and at minimum
     blink an offline LED next time we add one.

Anything in this file is part of the OTA boundary. ugit auto-protects
/boot.py, /main.py, /ugit.py, and /config.json from being overwritten by a
bad pull -- a corrupted update should not brick the device.
"""

import time


def _safe_ota():
    try:
        import ugit
    except ImportError:
        print("[boot] ugit not installed; skipping OTA. Install with:")
        print("       mpremote mip install github:turfptax/ugit")
        return

    try:
        print("[boot] ugit: checking for updates...")
        ugit.pull_all()
        print("[boot] ugit: done.")
    except Exception as e:
        # Don't let OTA failure stop the application from running.
        print("[boot] ugit: update failed -- continuing with current firmware.")
        print("[boot] ugit error:", repr(e))


_safe_ota()

# Brief settling pause so the network stack stabilizes before main.py opens
# the MQTT socket. ugit leaves Wi-Fi connected on success.
time.sleep_ms(500)
