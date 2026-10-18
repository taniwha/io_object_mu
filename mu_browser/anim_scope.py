# vim:ts=4:et
# <pep8 compliant>
"""MU Animation panel scope — which mu_import_id to show (testable, no UI).

Blender often leaves a stale active object when the user clicks a collection,
and often leaves a stale active layer collection when the user picks an object
in the 3D view. A single-frame snapshot therefore cannot decide correctly.

We track what changed since the last resolve:
- only layer collection changed → drive from collection
- only / also object changed → drive from object
"""


# Last-seen pointers + which input should win ("collection" | "object").
_last_alc_ptr = None
_last_obj_ptr = None
_last_drive = None


def reset_scope_drive_state():
    """Clear change-tracking (tests / addon reload)."""
    global _last_alc_ptr, _last_obj_ptr, _last_drive
    _last_alc_ptr = None
    _last_obj_ptr = None
    _last_drive = None


def import_id_from_object_chain(obj):
    """Walk obj and Blender parents until mu_import_id is found."""
    if obj is None:
        return ""
    seen = set()
    current = obj
    while current is not None:
        try:
            ptr = current.as_pointer()
        except Exception:
            ptr = id(current)
        if ptr in seen:
            break
        seen.add(ptr)
        try:
            value = current.get("mu_import_id")
            if value:
                return str(value)
        except Exception:
            pass
        current = getattr(current, "parent", None)
    return ""


def obj_in_collection_tree(obj, collection):
    """True when obj is linked to collection or any nested child collection."""
    if obj is None or collection is None:
        return False
    try:
        if obj.name in collection.objects:
            return True
    except Exception:
        pass
    try:
        for child in collection.children:
            if obj_in_collection_tree(obj, child):
                return True
    except Exception:
        pass
    return False


def obj_belongs_to_collection_tree(obj, collection):
    """True when obj or any Blender parent is linked under the collection tree."""
    if obj is None or collection is None:
        return False
    seen = set()
    current = obj
    while current is not None:
        try:
            ptr = current.as_pointer()
        except Exception:
            ptr = id(current)
        if ptr in seen:
            break
        seen.add(ptr)
        if obj_in_collection_tree(current, collection):
            return True
        current = getattr(current, "parent", None)
    return False


def collection_is_empty_shell(collection):
    """True when collection has no objects in itself or any nested child."""
    if collection is None:
        return True
    try:
        if list(collection.objects):
            return False
    except Exception:
        pass
    try:
        for child in collection.children:
            if not collection_is_empty_shell(child):
                return False
    except Exception:
        pass
    return True


def collect_import_ids_in_collection_tree(collection):
    """Distinct mu_import_id values under a collection tree."""
    ids = set()
    seen_objs = set()

    def visit_obj(o):
        if o is None:
            return
        try:
            ptr = o.as_pointer()
        except Exception:
            ptr = id(o)
        if ptr in seen_objs:
            return
        seen_objs.add(ptr)
        iid = import_id_from_object_chain(o)
        if iid:
            ids.add(iid)
        try:
            children = list(o.children)
        except Exception:
            children = []
        for child in children:
            visit_obj(child)

    def visit_col(col):
        if col is None:
            return
        try:
            objects = list(col.objects)
        except Exception:
            objects = []
        for o in objects:
            visit_obj(o)
        try:
            children = list(col.children)
        except Exception:
            children = []
        for child in children:
            visit_col(child)

    visit_col(collection)
    return ids


def _pointer_of(thing):
    if thing is None:
        return None
    try:
        return thing.as_pointer()
    except Exception:
        return id(thing)


def _update_drive(alc, obj):
    """Record whether the user last changed the collection or the object."""
    global _last_alc_ptr, _last_obj_ptr, _last_drive
    alc_ptr = _pointer_of(alc)
    obj_ptr = _pointer_of(obj)
    alc_changed = alc_ptr != _last_alc_ptr
    obj_changed = obj_ptr != _last_obj_ptr

    if alc_changed and not obj_changed:
        _last_drive = "collection"
    elif obj_changed:
        # Object click, or object click that also synced the layer collection.
        _last_drive = "object"
    elif _last_drive is None:
        _last_drive = "object" if obj is not None else "collection"

    _last_alc_ptr = alc_ptr
    _last_obj_ptr = obj_ptr
    return _last_drive


def _resolve_from_collection(alc_col, obj, obj_import_id):
    ids_in_alc = collect_import_ids_in_collection_tree(alc_col)
    belongs = obj_belongs_to_collection_tree(obj, alc_col)

    if (
        len(ids_in_alc) == 0
        and collection_is_empty_shell(alc_col)
        and not belongs
    ):
        return ""

    if len(ids_in_alc) == 1:
        return next(iter(ids_in_alc))

    # Scene / mixed: only show when the object is in this branch.
    if belongs and obj_import_id:
        return obj_import_id
    return ""


def _resolve_from_object(alc_col, obj_import_id):
    if obj_import_id:
        return obj_import_id
    if alc_col is None:
        return ""
    ids_in_alc = collect_import_ids_in_collection_tree(alc_col)
    if len(ids_in_alc) == 1:
        return next(iter(ids_in_alc))
    return ""


def resolve_mu_import_id(context):
    """Resolve mu_import_id from active layer collection + object selection."""
    obj = getattr(context, "object", None)
    try:
        alc = context.view_layer.active_layer_collection
        alc_col = alc.collection if alc is not None else None
    except Exception:
        alc = None
        alc_col = None

    obj_import_id = import_id_from_object_chain(obj) if obj is not None else ""
    drive = _update_drive(alc, obj)

    if drive == "collection" and alc_col is not None:
        return _resolve_from_collection(alc_col, obj, obj_import_id)

    # Object-driven (or no collection): prefer the active object.
    got = _resolve_from_object(alc_col, obj_import_id)
    if got:
        return got
    try:
        for selected in context.selected_objects:
            import_id = import_id_from_object_chain(selected)
            if import_id:
                return import_id
    except Exception:
        pass
    return ""
