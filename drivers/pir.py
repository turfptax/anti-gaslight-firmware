"""
PIR driver -- IRQ-driven state change with debounce.

The motion module (Panasonic EKMC1601111 in v1, generic HC-SR501-class on
the bench) outputs a logic-level pulse on detection. This driver:

  - Debounces the line in a soft IRQ (50 ms minimum between accepted edges).
  - Calls a user-supplied on_change callback with the new boolean state.
  - Exposes state() for periodic heartbeat publishes.

Soft IRQs on ESP32 MicroPython can allocate, so we can call back directly
into Python from the handler. If we ever migrate to a hard IRQ build, the
callback would need to be deferred (e.g. micropython.schedule).
"""

import time
from machine import Pin


class PIR:
    DEBOUNCE_MS = 50

    def __init__(self, pins):
        """
        pins: {"out": GPIO num}
        """
        self._pin = Pin(pins["out"], Pin.IN, Pin.PULL_DOWN)
        self._state = bool(self._pin.value())
        self._last_change_ms = 0
        self._on_change_cb = None

        self._pin.irq(
            trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING,
            handler=self._isr,
        )

    def _isr(self, pin):
        now = time.ticks_ms()
        if time.ticks_diff(now, self._last_change_ms) < self.DEBOUNCE_MS:
            return
        new_state = bool(pin.value())
        if new_state == self._state:
            return
        self._last_change_ms = now
        self._state = new_state
        if self._on_change_cb:
            try:
                self._on_change_cb(new_state)
            except Exception as e:
                # An ISR-context exception is fatal; swallow and log so the
                # publish loop keeps running.
                print("[pir] callback error:", repr(e))

    def state(self):
        return self._state

    def on_change(self, cb):
        """Register cb(state_bool) for rising/falling edges."""
        self._on_change_cb = cb
