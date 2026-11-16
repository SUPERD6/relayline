__version__ = "0.7.0"

from . import winproc as _winproc  # noqa: E402

_winproc.install()   # Windows, no console of our own: children start without popping a terminal window
