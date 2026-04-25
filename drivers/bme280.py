"""
BME280 driver -- thin wrapper over robert-hh/BME280.

The upstream library does the Q-format compensation math. This wrapper
exposes the (temp_C, humidity_pct, pressure_hPa) tuple the rest of the
firmware expects, hides the I2C bus setup, and tolerates a missing sensor.

Install the upstream lib once per device, into /lib/:
    curl -O https://raw.githubusercontent.com/robert-hh/BME280/master/bme280_float.py
    mpremote connect <port> mkdir :lib
    mpremote connect <port> cp bme280_float.py :lib/bme280.py

/lib is on MicroPython's default sys.path, so `import bme280` resolves there.
Critically, /lib is also one of the paths ugit auto-protects -- a future OTA
pull will not wipe the upstream library.

The local filename clash with our own driver is the reason for the
import-aliased name below.
"""

from machine import Pin, I2C

try:
    import bme280 as upstream
except ImportError:
    upstream = None


class BME280:
    """Wraps an upstream bme280.BME280 instance behind a stable interface."""

    DEFAULT_ADDR_PRIMARY   = 0x76
    DEFAULT_ADDR_SECONDARY = 0x77

    def __init__(self, i2c_cfg, addr=None):
        """
        i2c_cfg: {"scl": int, "sda": int, "freq": int, "bus": int (default 0)}
        addr:    explicit I2C address; if None, auto-probes 0x76 then 0x77.
        """
        if upstream is None:
            raise RuntimeError(
                "bme280 module not on device. Run:\n"
                "  curl -O https://raw.githubusercontent.com/robert-hh/BME280/master/bme280_float.py\n"
                "  mpremote cp bme280_float.py :bme280.py"
            )

        self._i2c = I2C(
            i2c_cfg.get("bus", 0),
            scl=Pin(i2c_cfg["scl"]),
            sda=Pin(i2c_cfg["sda"]),
            freq=i2c_cfg.get("freq", 400_000),
        )

        candidates = [addr] if addr else [self.DEFAULT_ADDR_PRIMARY,
                                          self.DEFAULT_ADDR_SECONDARY]
        last_err = None
        self._device = None
        for a in candidates:
            try:
                self._device = upstream.BME280(i2c=self._i2c, address=a)
                self._addr = a
                break
            except OSError as e:
                last_err = e
        if self._device is None:
            raise OSError("BME280 not found at 0x76 or 0x77: {}".format(last_err))

    def i2c(self):
        """Expose the underlying bus so other I2C devices can share it."""
        return self._i2c

    def read(self):
        """
        Returns (temp_C, humidity_pct_rh, pressure_hPa) as floats.

        robert-hh's float build returns the values directly in those units.
        """
        # `.read_compensated_data()` returns (T_C, P_hPa, H_pct) on the float build
        t, p, h = self._device.read_compensated_data()
        return (t, h, p)
