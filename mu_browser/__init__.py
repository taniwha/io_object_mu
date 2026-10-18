# vim:ts=4:et
# <pep8 compliant>

try:
    from .. import register_submodules
except ImportError:
    import register_submodules

submodule_names = (
    "properties",
    "catalog",
    "thumbnails",
    "operators",
    "panels",
)

# Load submodules before register_submodules — __init__ is still running at
# this point, so a bare getattr(module, "properties") would fail.
from . import catalog, operators, panels, properties, thumbnails  # noqa: F401

register_submodules(__name__, submodule_names)

try:
    from .panels import ensure_alc_redraw_handler, _repair_all_nested_action_names
    ensure_alc_redraw_handler()
    _repair_all_nested_action_names()
except Exception:
    pass
try:
    from ..import_mu.name_protect import ensure_name_protect_handler
    ensure_name_protect_handler()
except Exception:
    pass
