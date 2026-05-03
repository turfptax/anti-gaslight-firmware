"""
Anti-Gaslight Environmental Sensor -- v1 firmware entry point.

Runs on MicroPython (ESP32-S3 Super Mini). Orchestrates sensor reads, network
connectivity, and MQTT publishing per SPEC.md §6. Adds bidirectional control:
  - MQTT command topic (primary, from the Pi)
  - USB-CDC serial line protocol (backup, from a directly-connected host)

Boot order:
  1. boot.py runs ugit OTA pull (ugit owns Wi-Fi creds in /config.json).
  2. main.py: load app config, verify Wi-Fi, connect MQTT, subscribe to cmd
     topic, run the publish scheduler (which also polls serial).
"""

import json
import time

from machine import Pin, PWM

from drivers.bme280 import BME280
from drivers.tcs3200 import TCS3200
from drivers.pir import PIR
from net.wifi import load_settings, ensure_connected, mac4
from net.mqtt import MQTTPublisher
from net.serial_cmd import poll_line
import commands


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
    """UTC ISO-8601 timestamp. Assumes NTP-synced clock."""
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


# --------------------------------------------------------------- buzzer
def make_play_tone(buzzer_pin):
    """
    Returns a callable(freq_hz, duration_ms) -> bool. If buzzer_pin is None,
    returns a no-op that responds False so commands.dispatch can report
    'no buzzer configured' to the caller.
    """
    if buzzer_pin is None:
        def _no_buzzer(freq, ms):
            return False
        return _no_buzzer

    pwm = PWM(Pin(buzzer_pin))
    pwm.duty(0)

    def _play(freq, ms):
        try:
            pwm.freq(int(freq))
            pwm.duty(512)               # ~50% duty for max volume on a piezo
            time.sleep_ms(int(ms))
            pwm.duty(0)
            return True
        except Exception as e:
            print("[buzzer] play failed:", repr(e))
            pwm.duty(0)
            return False
    return _play


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
    play_tone = make_play_tone(settings.get("buzzer_pin"))

    # ---- mqtt ----
    pub = MQTTPublisher(settings["mqtt"], client_id=nid)
    pub.connect()
    pub.publish(topic_for(nid, "status"), "online", retain=True, qos=1)

    pir.on_change(lambda state: publish_reading(
        pub, nid, "motion", state, "bool", "EKMC1601111"
    ))

    # ---- command channels ----
    cmd_topic       = topic_for(nid, "cmd")
    cmd_resp_topic  = topic_for(nid, "cmd/response")

    def read_all():
        """Force-read every sensor synchronously. Used by the read_all command."""
        t, h, p = bme.read()
        r, g, b, c = tcs.read_all()
        return {
            "temperature_c": t,
            "humidity_pct": h,
            "pressure_hpa": p,
            "light_hz": {"r": r, "g": g, "b": b, "clear": c},
            "motion": pir.state(),
            "ts": _iso_now(),
        }

    def respond_mqtt(resp_dict):
        try:
            pub.publish(cmd_resp_topic, json.dumps(resp_dict))
        except Exception as e:
            print("[cmd] mqtt response failed:", repr(e))

    def respond_serial(resp_dict):
        # JSON line so a controller can parse easily; humans can still read it.
        print(json.dumps(resp_dict))

    def on_mqtt_message(topic, payload):
        # Both come in as bytes.
        try:
            cmd = json.loads(payload)
        except ValueError:
            cmd = {"cmd": payload.decode("utf-8", "replace").strip()}
        commands.dispatch(cmd, {
            "respond": respond_mqtt,
            "read_all": read_all,
            "play_tone": play_tone,
            "nid": nid,
        })

    pub.set_callback(on_mqtt_message)
    pub.subscribe(cmd_topic, qos=0)

    serial_ctx = {
        "respond": respond_serial,
        "read_all": read_all,
        "play_tone": play_tone,
        "nid": nid,
    }

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

        # ---- scheduled publishes ----
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

        # ---- command channels ----
        pub.loop()                      # services MQTT subscribe -> on_mqtt_message
        line = poll_line()              # non-blocking USB-CDC read
        if line is not None:
            commands.dispatch(line, serial_ctx)

        time.sleep_ms(50)


if __name__ == "__main__":
    main()
