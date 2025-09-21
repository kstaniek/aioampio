"""Codec package.

Auto-register the built-in Ampio codec so users don't need to list it in config.
"""

from . import ampio as _ampio  # noqa: F401  (side-effect: registers Ampio decoders)
