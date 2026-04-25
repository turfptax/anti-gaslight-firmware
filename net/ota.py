"""
OTA hook -- delegates to ugit.

ugit (https://github.com/turfptax/ugit) is the canonical OTA mechanism for
this project. It pulls files from a configured GitHub repo into the device
filesystem on each call to pull_all(), using SHA hashes to skip unchanged
files.

Configuration lives in /config.json at device root. ugit reads:
  ssid, password         -- Wi-Fi
  user, repository, branch -- GitHub source
  token                  -- optional, for private repos
  ignore                 -- list of paths to skip

This module is invoked from boot.py BEFORE main.py starts. main.py does NOT
call OTA on every reconnect -- updates happen at boot only, so a bad pull can
be recovered by a power cycle without entering an update-loop.

The `ota_cfg` parameter lets settings.json disable OTA at runtime without
removing ugit -- useful when bench-debugging on a node we don't want to
overwrite. boot.py respects ota_cfg.enabled.
"""


def is_enabled(ota_cfg):
    """Returns True iff settings.json's `ota.enabled` is truthy."""
    if not ota_cfg:
        return False
    return bool(ota_cfg.get("enabled", True))


def check_and_apply_ota(ota_cfg=None):
    """
    Run a ugit pull. Safe to call when ugit is missing -- prints and returns.

    Note: in v1, boot.py calls ugit.pull_all() directly for simplicity. This
    function exists so main.py / a button handler / a remote command could
    request an out-of-band update later (e.g. an MQTT 'update' topic).
    """
    if not is_enabled(ota_cfg):
        print("[ota] disabled in settings; skipping")
        return False

    try:
        import ugit
    except ImportError:
        print("[ota] ugit not installed; skipping")
        return False

    try:
        ugit.pull_all()
        return True
    except Exception as e:
        print("[ota] pull failed:", repr(e))
        return False
