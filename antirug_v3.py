"""Compatibility wrapper for services.antirug_v3."""

from services import antirug_v3 as _impl
from services.antirug_v3 import *  # noqa: F401,F403

# Explicitly re-export underscore helper used by legacy tests.
_get_rug_prob = _impl._get_rug_prob
