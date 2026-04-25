"""
test_board.py -- bring-up sanity check for the roomsense sensor node.

Target hardware (v3):
  ESP32-S3 Super Mini
  GY-BME280 temp/humidity/pressure on I2C0  (SDA=GPIO8, SCL=GPIO9, addr 0x76)
  TCS3200 color sensor                       (OUT=GPIO4, S2=GPIO5, S3=GPIO6)
                                              S0,S1 hardware-strapped (see WIRING)
  PIR motion                                 (digital out -> GPIO2)

Wiring:
  TCS3200 S0  -> GND
  TCS3200 S1  -> 3.3 V         <-- 2% scaling per datasheet (NOT both low!)
  TCS3200 OE  -> GND           (or onboard LED jumper, breakout-dependent)
  TCS3200 VCC -> 3.3 V or 5 V per breakout silk
  GY-BME280 VCC -> 3.3 V or 5 V (module has onboard regulator + level shifters)
  GY-BME280 SDO/CSB are hard-wired on this module; address is 0x76
  PIR Vcc     -> 5 V if module needs it; signal is logic-level either way

Prerequisite (one-time):
  Install robert-hh's BME280 driver onto the device. From the host:

      curl -O https://raw.githubusercontent.com/robert-hh/BME280/master/bme280_float.py
      mpremote connect <port> cp bme280_float.py :bme280.py

  (We rename it to bme280.py on the device so `import bme280` works.)

Run:
  mpremote connect <port> run test_board.py

Output:
  One line per second with T, RH, P, R/G/B/clear light frequencies, and motion.
"""

import time
from machine import Pin, I2C

# -------------------------------------------------------------- pin config
I2C_SDA = 8
I2C_SCL = 9

TCS_OUT = 4
TCS_S2  = 5     # filter select bit 0
TCS_S3  = 6     # filter select bit 1

PIR_PIN = 2

BME280_ADDR = 0x76

# TCS3200 (S2, S3) filter table per datasheet.
FILTER_RED   = (0, 0)
FILTER_BLUE  = (0, 1)
FILTER_CLEAR = (1, 0)
FILTER_GREEN = (1, 1)

# -------------------------------------------------------------- I2C / BME280
i2c = I2C(0, sda=Pin(I2C_SDA), scl=Pin(I2C_SCL), freq=400_000)

bme = None
try:
    import bme280
    try:
        bme = bme280.BME280(i2c=i2c, address=BME280_ADDR)
        print("BME280: found at", hex(BME280_ADDR))
    except OSError as e:
        print("BME280: probe at", hex(BME280_ADDR), "failed:", e)
except ImportError:
    print("BME280: bme280.py not on device. See header comment for install steps.")


# -------------------------------------------------------------- TCS3200
s2 = Pin(TCS_S2, Pin.OUT, value=0)
s3 = Pin(TCS_S3, Pin.OUT, value=0)
out = Pin(TCS_OUT, Pin.IN)

_tcs_edges = 0
def _tcs_isr(_p):
    global _tcs_edges
    _tcs_edges += 1
out.irq(trigger=Pin.IRQ_RISING, handler=_tcs_isr)


def _tcs_count_hz(gate_ms):
    """Gate-count rising edges. Good to ~10 kHz on soft IRQs."""
    global _tcs_edges
    _tcs_edges = 0
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < gate_ms:
        pass
    return _tcs_edges * (1000 // gate_ms)


def tcs_read_filter(filt, gate_ms=100):
    s2.value(filt[0])
    s3.value(filt[1])
    time.sleep_ms(5)                    # let the photodiode bank settle
    return _tcs_count_hz(gate_ms)


def tcs_read_rgbc(gate_ms=100):
    """Sweep R, G, B, clear in order. Returns (R, G, B, C) in Hz."""
    return (
        tcs_read_filter(FILTER_RED,   gate_ms),
        tcs_read_filter(FILTER_GREEN, gate_ms),
        tcs_read_filter(FILTER_BLUE,  gate_ms),
        tcs_read_filter(FILTER_CLEAR, gate_ms),
    )


# -------------------------------------------------------------- PIR
pir = Pin(PIR_PIN, Pin.IN, Pin.PULL_DOWN)


# -------------------------------------------------------------- main loop
found = i2c.scan()
print("Boot. I2C scan:", [hex(a) for a in found])
if BME280_ADDR not in found and 0x77 not in found:
    print("WARN: no BME280 on I2C -- check wiring / power")
print("--- 1 Hz sample loop. Ctrl-C to stop. ---")

try:
    while True:
        t_start = time.ticks_ms()

        # ---- BME280 ----
        if bme is not None:
            try:
                t_str, p_str, h_str = bme.values   # ('23.45C', '1013.25hPa', '45.67%')
            except OSError:
                t_str, p_str, h_str = " --   ", "  --     ", " --   "
        else:
            t_str, p_str, h_str = " --   ", "  --     ", " --   "

        # ---- TCS3200 R/G/B/C ----
        r, g, b, c = tcs_read_rgbc(100)

        # ---- PIR ----
        motion = "MOTION" if pir.value() else "  --  "

        print("T={:>7}  RH={:>7}  P={:>10}  "
              "R={:>4} G={:>4} B={:>4} C={:>4} Hz  PIR={}".format(
              t_str, h_str, p_str, r, g, b, c, motion))

        # Pace loop to ~1 Hz, accounting for the 4 x 105 ms gate sweep above.
        elapsed = time.ticks_diff(time.ticks_ms(), t_start)
        time.sleep_ms(max(0, 1000 - elapsed))
except KeyboardInterrupt:
    print("stopped.")
