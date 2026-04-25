"""
Anti-Gaslight Environmental Sensor -- v1 firmware entry point.

Runs on MicroPython (ESP32-S3 Super Mini in dev). Orchestrates sensor reads,
network connectivity, and MQTT publishing per SPEC.md §6.

Boot order:
  1. boot.py runs ugit OTA pull (ugit owns Wi-Fi creds in /config.json).
  2. main.py (this file) takes over: load app config, verify Wi-Fi, connect
     MQTT, run the publish scheduler.

Sensor cadences come from settings.json -> cadences_s. See
config/settings.example.json for the full schema.
"""

import json
import time

from drivers.bme280 import BME280
from drivers.tcs3200 import TCS3200
from drivers.pir import PIR
from net.wifi import load_settings, ensure_connected, mac4
from net.mqtt import MQTTPublisher


SETTINGS_PATH = "config/settings.json"
TOPIC_PREFIX  = "anti-gaslight"


# --------------------------------------------------------------- node identity
def node_id(settings):
    """<room>-<mac4>, e.g. 'office-3a7f'. Stable across reboots."""
    room = settings.get("room", "unassigned")
    return "{}-{}".format(room, mac4())


def topic_for(nid, metric):
    return "{}/{}/{}".format(TOPIC_PREFIX, nid, metric)


# --------------------------------------------------------------- payload shape
def _iso_now():
    """UTC ISO-8601 timestamp. Assumes NTP-synced clock; falls back to ticks."""
    t = time.gmtime()
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(*t[:6])


def publish_reading(pub, nid, metric, value, unit, sensor):
    payload = {
        "node_id": nid,
        "ts": _iso_now(),
        "metric": metric,
        "value": value,
        "unit": unit,
        "sensor": sensor,
    }
    pub.publish(topic_for(nid, metric), json.dumps(payload))


# --------------------------------------------------------------- main
def main():
    print("[main] loading", SETTINGS_PATH)
    try:
        settings = load_settings(SETTINGS_PATH)
    except OSError:
        print("[main] FATAL:", SETTINGS_PATH, "missing.")
        print("[main] copy config/settings.example.json to settings.json and edit.")
        return

    if not ensure_connected():
        print("[main] FATAL: Wi-Fi not available; cannot start MQTT.")
        return

    nid = node_id(settings)
    print("[main] node_id =", nid)

    # ---- sensors ----
    bme = BME280(settings["pins"]["i2c"])
    tcs = TCS3200(settings["pins"]["tcs3200"])
    pir = PIR(settings["pins"]["pir"])

    # ---- mqtt ----
    pub = MQTTPublisher(settings["mqtt"], client_id=nid)
    pub.connect()
    pub.publish(topic_for(nid, "status"), "online", retain=True, qos=1)

    pir.on_change(lambda state: publish_reading(
        pub, nid, "motion", state, "bool", "EKMC1601111"
    ))

    # ---- cadences ----
    cad = settings.get("cadences_s", {})
    bme_period_s = cad.get("bme280", 30)
    tcs_period_s = cad.get("tcs3200", 10)
    pir_hb_s     = cad.get("pir_heartbeat", 60)

    last_bme = 0
    last_tcs = 0
    last_pir_hb = 0

    print("[main] entering scheduler loop")
    while True:
        now = time.time()

        if now - last_bme >= bme_period_s:
            try:
                t, rh, p = bme.read()
                publish_reading(pub, nid, "temperature", t,  "degC", "BME280")
                publish_reading(pub, nid, "humidity",    rh, "%rh",  "BME280")
                publish_reading(pub, nid, "pressure",    p,  "hPa",  "BME280")
            except OSError as e:
                print("[main] BME280 read failed:", e)
            last_bme = now

        if now - last_tcs >= tcs_period_s:
            r, g, b, clear = tcs.read_all()
            publish_reading(pub, nid, "light/r",     r,     "Hz", "TCS3200")
            publish_reading(pub, nid, "light/g",     g,     "Hz", "TCS3200")
            publish_reading(pub, nid, "light/b",     b,     "Hz", "TCS3200")
            publish_reading(pub, nid, "light/clear", clear, "Hz", "TCS3200")
            last_tcs = now

        if now - last_pir_hb >= pir_hb_s:
            publish_reading(pub, nid, "heartbeat", pir.state(), "bool", "EKMC1601111")
            last_pir_hb = now

        pub.loop()
        time.sleep_ms(50)


if __name__ == "__main__":
    main()
