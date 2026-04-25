"""
TCS3200 driver -- gate-counted edge measurement.

The TCS3200 emits a square wave on OUT whose frequency is proportional to
the light intensity under the (S2,S3)-selected color filter. We count rising
edges in an IRQ over a known gate window and report Hz.

Why gate-counted IRQs:
  ESP32-S3 MicroPython exposes esp32.PCNT in 1.23+, but the API is unstable
  across builds. IRQ counting is portable across S3/C3/classic and accurate
  to ~10 kHz for soft IRQs -- well above the ~1 kHz typical indoor ambient
  reading at 20% (or 2%) frequency scaling.

S0/S1 (frequency scaling) are assumed hardware-strapped per the project
SPEC. We do not drive them. If you wire S0/S1 to GPIOs later, set the
SCALING_* constants and add corresponding Pin writes in __init__.

Verified on hardware bring-up 2026-04-24; see firmware/micropython/test_board.py
for the standalone version this was promoted from.
"""

import time
from machine import Pin


# (S2, S3) filter select -- per datasheet "Photodiode Type Selection".
FILTER_RED   = (0, 0)
FILTER_BLUE  = (0, 1)
FILTER_CLEAR = (1, 0)
FILTER_GREEN = (1, 1)


class TCS3200:
    def __init__(self, pins, gate_ms=100, settle_ms=5):
        """
        pins: {
            "s2":  GPIO num,    # filter select bit 0
            "s3":  GPIO num,    # filter select bit 1
            "out": GPIO num,    # frequency input (IRQ source)
            "oe":  optional GPIO num for active-low output enable;
                    if omitted, OE is assumed tied to GND on the breakout.
        }
        gate_ms:   per-channel measurement window. 100 ms gives 10 Hz
                   resolution and a ~400 ms RGBC sweep.
        settle_ms: post-filter-switch delay before counting. The photodiode
                   bank needs a few ms to stabilize after S2/S3 changes.
        """
        self._gate_ms = gate_ms
        self._settle_ms = settle_ms

        self._s2 = Pin(pins["s2"], Pin.OUT, value=0)
        self._s3 = Pin(pins["s3"], Pin.OUT, value=0)
        self._out = Pin(pins["out"], Pin.IN)

        if "oe" in pins:
            # Active-low: 0 = enabled.
            self._oe = Pin(pins["oe"], Pin.OUT, value=0)
        else:
            self._oe = None

        self._edges = 0
        self._out.irq(trigger=Pin.IRQ_RISING, handler=self._isr)

    def _isr(self, _pin):
        # Soft IRQ on ESP32 MicroPython -- can allocate, but we keep this
        # tight to minimize jitter.
        self._edges += 1

    def _count_hz(self, gate_ms):
        self._edges = 0
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < gate_ms:
            pass
        # Hz = edges * (1000 / gate_ms)
        return self._edges * (1000 // gate_ms)

    def _select(self, filt):
        self._s2.value(filt[0])
        self._s3.value(filt[1])
        time.sleep_ms(self._settle_ms)

    def read_filter(self, filt):
        """Read one filter. filt is one of FILTER_RED / GREEN / BLUE / CLEAR."""
        self._select(filt)
        return self._count_hz(self._gate_ms)

    def read_all(self):
        """Sweep R, G, B, clear in order. Returns (R, G, B, C) in Hz."""
        return (
            self.read_filter(FILTER_RED),
            self.read_filter(FILTER_GREEN),
            self.read_filter(FILTER_BLUE),
            self.read_filter(FILTER_CLEAR),
        )
