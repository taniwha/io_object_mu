# vim:ts=4:et
# <pep8 compliant>
"""Parse UIList display titles ``clip (Action)`` back to the Action name.

No bpy — used by the MU panel, name protection, and tests.
"""
import re

_WEDGE = "\u2227"
_NNN_RE = re.compile(r"^(.*)(\.\d{3})$")
_BLEND_EXT = (".obj", ".pose", ".data")
_WEDGE_NNN_RE = re.compile(
    re.escape(_WEDGE) + r"(\.\d{3})(\.(?:obj|pose|data))?$")
_OBJ_NNN_RE = re.compile(r"(\.(?:obj|pose|data))(\.\d{3})$")


def peel_clip_wrapper(text, clip):
    """Peel one ``clip (inner)[ trail]`` layer. Returns (text, peeled)."""
    text = (text or "").strip()
    clip = (clip or "").strip()
    prefix = clip + " ("
    if not clip or not text.startswith(prefix):
        return text, False
    depth = 1
    i = len(prefix)
    while i < len(text) and depth:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    if depth != 0:
        # Unclosed ``dish (dish (Rescalar.obj`` — still peel the prefix.
        inner = text[len(prefix):].strip()
        if inner.endswith(")"):
            inner = inner[:-1].strip()
        if inner:
            return inner, True
        return text, False
    inner = text[len(prefix):i - 1].strip()
    trail = text[i:].strip()
    if trail:
        inner = ("%s %s" % (inner, trail)).strip()
    return inner, True


def parse_f2_identity(new, clip_name, action_name=""):
    """Turn a displayed ``dish (Rescalar.obj) a`` / nested wraps into the Action name."""
    new = (new or "").strip()
    clip = (clip_name or "").strip()
    fallback = (action_name or "").strip()
    if not new:
        return fallback
    if not clip:
        m = re.match(r"^(\S+) \(", new)
        if m:
            prefix = m.group(1)
            rest = new[len(prefix) + 2:]
            if rest.startswith(prefix + " (") or rest.startswith(prefix + "("):
                clip = prefix
    if clip:
        for _ in range(12):
            nxt, ok = peel_clip_wrapper(new, clip)
            if not ok or nxt == new:
                break
            new = nxt
    return new or fallback


def blender_name_tail(name):
    """Return plugin/Blender suffix: ``∧.001.obj``, ``∧``, ``.001``, ``.obj.007``."""
    name = name or ""
    wedge_i = name.rfind(_WEDGE)
    if wedge_i >= 0:
        return name[wedge_i:]
    m = _OBJ_NNN_RE.search(name)
    if m:
        return m.group(1) + m.group(2)
    m = _NNN_RE.match(name)
    if m:
        return m.group(2)
    for ext in _BLEND_EXT:
        if name.endswith(ext):
            return ext
    return ""


def blender_name_core(name):
    """User-editable prefix — everything before ``∧`` / trailing ``.obj`` / ``.NNN``."""
    name = name or ""
    tail = blender_name_tail(name)
    if not tail:
        return name
    if tail.startswith(_WEDGE):
        return name[: name.rfind(_WEDGE)]
    if name.endswith(tail):
        return name[: -len(tail)]
    return name


def blender_name_has_nnn(name):
    """True when a Blender ``.NNN`` uniquifier is already present."""
    name = name or ""
    if _NNN_RE.match(name):
        return True
    if _WEDGE_NNN_RE.search(name):
        return True
    if _OBJ_NNN_RE.search(name):
        return True
    return False


def merge_blender_protected_rename(old_name, user_input):
    """Apply a UI edit to the core only; keep ``∧`` / ``.NNN`` / ``.obj`` tail."""
    old = (old_name or "").strip()
    user = (user_input or "").strip()
    if not user:
        return old
    if not old:
        return user
    old_tail = blender_name_tail(old)
    user_core = blender_name_core(user)
    if old_tail and user.endswith(old_tail):
        user_core = user[: -len(old_tail)]
    elif old_tail and user_core.endswith(old_tail):
        user_core = user_core[: -len(old_tail)]
    user_core = (user_core or "").strip()
    if not user_core:
        return old
    return user_core + old_tail


def unity_stem(name):
    """Blender ``Foo∧.001`` → Unity transform ``Foo``."""
    name = name or ""
    ind = name.rfind(_WEDGE)
    if ind >= 0:
        return name[:ind]
    m = _NNN_RE.match(name)
    return m.group(1) if m else name


def rewrite_path_segments(path, old_name, new_name):
    """Replace full ``/`` segments that match the old Blender or Unity name."""
    path = str(path or "")
    if not path or not old_name:
        return path
    olds = {old_name, unity_stem(old_name)}
    olds.discard("")
    new_seg = unity_stem(new_name) or new_name
    parts = path.split("/")
    changed = False
    for i, part in enumerate(parts):
        if part in olds:
            parts[i] = new_seg
            changed = True
    return "/".join(parts) if changed else path


def rewrite_action_datablock_name(action_name, old_name, new_name):
    if not action_name or not old_name:
        return None
    if action_name == old_name:
        return new_name
    if action_name.startswith(old_name + "."):
        return new_name + action_name[len(old_name):]
    return None
