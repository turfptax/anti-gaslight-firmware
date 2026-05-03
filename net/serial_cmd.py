"""
Non-blocking USB-CDC line reader.

The S3 Super Mini's REPL lives on USB-CDC. While main.py is running, bytes
arriving on that interface land in sys.stdin. We poll it without blocking
each main-loop tick, accumulate into a line buffer, and yield a complete
line when CR or LF is seen.

This coexists with the REPL: hitting Ctrl-C still raises KeyboardInterrupt
in main.py, which lets you drop back to a prompt. We never disable the
keyboard interrupt -- recovery via Ctrl-C is a feature, not a bug.

Usage:
    from net.serial_cmd import poll_line
    line = poll_line()              # returns str or None each call
"""

import sys

try:
    import uselect as select
except ImportError:
    import select


_poll = select.poll()
_poll.register(sys.stdin, select.POLLIN)
_buffer = ""


def poll_line():
    """
    Drain any bytes available right now. Returns a complete line (str,
    stripped) when CR or LF arrives. Otherwise returns None.
    """
    global _buffer
    while _poll.poll(0):                # 0 ms timeout = non-blocking
        ch = sys.stdin.read(1)
        if not ch:
            break
        if ch in ("\n", "\r"):
            line = _buffer.strip()
            _buffer = ""
            if line:
                return line
            # else: empty line, keep draining
        else:
            _buffer += ch
            # Hard cap to avoid pathological input. 256 chars is generous
            # for our line protocol.
            if len(_buffer) > 256:
                _buffer = ""
    return None
