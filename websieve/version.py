"""Package version resolved from installed distribution metadata."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("websieve")
except PackageNotFoundError:
    # A source checkout is useful before installation. The artifact check
    # exercises the installed wheel, where metadata must always be present.
    __version__ = "0+unknown"
