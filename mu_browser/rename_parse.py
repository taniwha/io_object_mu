# vim:ts=4:et
# <pep8 compliant>
"""Backward-compatible re-export — implementation lives in ``utils.rename_parse``."""
from ..utils.rename_parse import (  # noqa: F401
    blender_name_core,
    blender_name_has_nnn,
    blender_name_tail,
    merge_blender_protected_rename,
    parse_f2_identity,
    peel_clip_wrapper,
    rewrite_action_datablock_name,
    rewrite_path_segments,
    unity_stem,
)
