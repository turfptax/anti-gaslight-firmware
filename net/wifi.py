"""
Wi-Fi helpers.

ugit owns the canonical Wi-Fi credentials in /config.json (alongside the
GitHub repo info it needs for OTA). This module:
  - Loads our own application config from config/settings.json.
  - Verifies the STA interface is connected; reconnects from /config.json if
    boot.py's ugit.pull_all() left it down (e.g. OTA disabled / failed).

We do NOT duplicate WiFi creds in settings.json -- single source of truth.
"""

import json
import time

try:
    import network
except ImportError:
    network = None      # allows host-side import for unit tests

UGIT_CONFIG_PATH = "/config.json"


def load_settings(path):
    """Load application settings.json. Raises OSError if missing."""
    with open(path, "r") as fh:
        return json.load(fh)


def save_settings(path, settings):
    with open(path, "w") as fh:
        json.dump(settings, fh)


def _load_ugit_config():
    try:
        with open(UGIT_CONFIG_PATH, "r") as fh:
            return json.load(fh)
    except OSError:
        return {}


def ensure_connected(timeout_s=15):
    """
    Verify Wi-Fi is up; if not, reconnect using credentials from /config.json.
    Returns True on connected, False on timeout.
    """
    if network is None:
        return False

    sta = network.WLAN(network.STA_IF)
    if sta.isconnected():
        return True

    cfg = _load_ugit_config()
    ssid = cfg.get("ssid")
    password = cfg.get("password")
    if not ssid:
        print("[wifi] /config.json missing 'ssid' -- cannot reconnect")
        return False

    sta.active(True)
    print("[wifi] connecting to", ssid, "...")
    sta.connect(ssid, password)

    t0 = time.ticks_ms()
    while not sta.isconnected():
        if time.ticks_diff(time.ticks_ms(), t0) > timeout_s * 1000:
            print("[wifi] timeout after {}s".format(timeout_s))
            return False
        time.sleep_ms(200)

    print("[wifi] connected:", sta.ifconfig())
    return True


def mac4():
    """Last 4 hex chars of the STA MAC, used in node_id."""
    if network is None:
        return "0000"
    sta = network.WLAN(network.STA_IF)
    mac = sta.config("mac")
    return "".join("{:02x}".format(b) for b in mac[-2:])
