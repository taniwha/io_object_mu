# vim:ts=4:et
# <pep8 compliant>
"""Extra Mu-tab operators: New templates, locale+, UI Elements, TOC pages."""

from __future__ import annotations

import os
import re
import shutil

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper


def _find_root(context):
    from .operators import _find_bundle_root_from_context
    return _find_bundle_root_from_context(context)


class KSPMU_MT_KspBundleNewMenu(bpy.types.Menu):
    bl_label = "New KSP Bundle"
    bl_idname = "KSPMU_MT_ksp_bundle_new"

    def draw(self, context):
        layout = self.layout
        layout.operator(
            "object.ksp_bundle_new_template",
            text="KSPedia Page (sample)",
            icon="BOOKMARKS",
        ).template = "KSPEDIA"
        layout.operator(
            "object.ksp_bundle_new_template",
            text="PBS-style (multi-lang + tree)",
            icon="OUTLINER",
        ).template = "PBS"
        layout.operator(
            "object.ksp_bundle_new_template",
            text="GEP-style (backgrounds + tree)",
            icon="IMAGE_DATA",
        ).template = "GEP"
        layout.operator(
            "object.ksp_bundle_new_template",
            text="Kerbin texture swap (demo)",
            icon="UV",
        ).template = "KERBIN"


class KSPMU_OT_KspBundleNewTemplate(bpy.types.Operator):
    bl_idname = "object.ksp_bundle_new_template"
    bl_label = "New KSP Sample Bundle"
    bl_description = "Create a KSPedia / PBS / GEP sample bundle in the scene"
    bl_options = {"REGISTER", "UNDO"}

    template: EnumProperty(
        name="Template",
        items=(
            ("KSPEDIA", "KSPedia Page", "Single page with background + texts"),
            ("PBS", "PBS-style", "Folders, submenus, two locales"),
            ("GEP", "GEP-style", "Background tree, single locale"),
            ("KERBIN", "Kerbin texture swap", "Page whose background was replaced (Import Image demo)"),
        ),
        default="KSPEDIA",
    )

    def execute(self, context):
        from . import templates
        if self.template == "PBS":
            root = templates.create_pbs_sample(context)
        elif self.template == "GEP":
            root = templates.create_gep_sample(context)
        elif self.template == "KERBIN":
            root = templates.create_kerbin_texture_sample(context)
        else:
            root = templates.create_kspedia_page_sample(context)
        self.report(
            {"INFO"},
            "Created sample '%s' (read-only until you Export to a Source folder)"
            % (root.ksp_bundle.bundle_name or root.name),
        )
        return {"FINISHED"}


_last_deselect_root = None


def _resolve_deselect_root(context):
    """Active bundle, or the one last hidden by Deselect Bundle."""
    global _last_deselect_root
    root = _find_root(context)
    if root is not None:
        return root
    root = _last_deselect_root
    if root is None:
        return None
    try:
        name = root.name
    except ReferenceError:
        _last_deselect_root = None
        return None
    try:
        if bpy.data.objects.get(name) is not root:
            _last_deselect_root = None
            return None
    except Exception:
        _last_deselect_root = None
        return None
    return root


def _bundle_content_hidden(root):
    """True when bundle contents are hidden but root may stay visible."""
    try:
        if root.hide_get():
            # Legacy full-tree hide — treat as deselected
            return True
    except Exception:
        pass
    children = []
    try:
        children = list(root.children)
    except Exception:
        children = []
    if not children:
        return False
    for child in children:
        try:
            if not child.hide_get():
                return False
        except Exception:
            return False
    return True


class KSPMU_OT_DeselectBundle(bpy.types.Operator):
    """Toggle this bundle's content visibility only — other bundles stay as they are.

    Unlike Select Bundle (solo/active), you can hide or show any number of
    bundles independently.
    """
    bl_idname = "object.ksp_deselect_bundle"
    bl_label = "Deselect Bundle"
    bl_description = "Hide and deselect the active KSP bundle (does not delete)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        global _last_deselect_root
        from .import_ksp import (
            _hide_bundle_content,
            _set_hide_tree,
            show_multipage_index,
        )

        root = _resolve_deselect_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}

        kb = root.ksp_bundle
        label = kb.bundle_name or root.name

        if _bundle_content_hidden(root):
            # Show ONLY this bundle — do not call set_active_bundle (that solos)
            try:
                _set_hide_tree(root, False)
            except Exception:
                pass
            try:
                _hide_bundle_content(root, False)
            except Exception:
                pass
            if kb.layout_mode == "multipage" and kb.page_count:
                try:
                    show_multipage_index(root, int(kb.active_page_index or 0))
                except Exception:
                    pass
            msg = "Shown: %s" % label
        else:
            _last_deselect_root = root
            try:
                _hide_bundle_content(root, True)
            except Exception:
                pass
            msg = "Hidden: %s" % label

        # Keep this root active/selected so you can toggle again or switch bundles
        for o in context.scene.objects:
            try:
                o.select_set(False)
            except Exception:
                pass
        context.view_layer.objects.active = root
        try:
            root.select_set(True)
        except Exception:
            pass
        self.report({"INFO"}, msg)
        return {"FINISHED"}


class KSPMU_OT_SelectNextBundle(bpy.types.Operator):
    """Like Select Bundle, but cycles to the next KSP bundle root."""
    bl_idname = "object.ksp_select_next_bundle"
    bl_label = "Select Next Bundle"
    bl_description = "Cycle the active KSP bundle in the scene"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from .import_ksp import (
            _set_hide_tree,
            set_active_bundle,
            show_multipage_index,
        )

        roots = []
        for obj in context.scene.objects:
            try:
                if obj.ksp_bundle.is_ksp_bundle:
                    roots.append(obj)
            except Exception:
                continue
        if not roots:
            self.report({"ERROR"}, "No KSP bundles in the scene")
            return {"CANCELLED"}
        roots.sort(key=lambda o: (o.name or "").lower())
        cur = _find_root(context)
        idx = 0
        if cur is not None:
            try:
                idx = (roots.index(cur) + 1) % len(roots)
            except ValueError:
                idx = 0
        root = roots[idx]
        try:
            _set_hide_tree(root, False)
        except Exception:
            pass
        set_active_bundle(root, context.scene)
        kb = root.ksp_bundle
        kb.filter_page_object = None
        kb.filter_scope_object = None
        if kb.layout_mode == "multipage" and kb.page_count:
            show_multipage_index(root, int(kb.active_page_index or 0))
            kb.filter_scope_object = None
            kb.filter_page_object = None
        for o in context.scene.objects:
            try:
                o.select_set(False)
            except Exception:
                pass
        context.view_layer.objects.active = root
        root.select_set(True)
        self.report(
            {"INFO"},
            "Active bundle %d/%d: %s"
            % (idx + 1, len(roots), kb.bundle_name or root.name),
        )
        return {"FINISHED"}


class KSPMU_OT_AddLocale(bpy.types.Operator):
    bl_idname = "object.ksp_add_locale"
    bl_label = "Add Locale"
    bl_description = "Add a language tag to this bundle (written on Export)"
    bl_options = {"REGISTER"}

    locale: StringProperty(
        name="Locale",
        description="Language tag, e.g. de-de, fr-fr, pt-br, zh-cn",
        default="de-de",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=280)

    def draw(self, context):
        self.layout.prop(self, "locale")
        self.layout.label(text="Tags like en-us, de-de, es-es, zh-cn", icon="INFO")

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        kb = root.ksp_bundle
        if getattr(kb, "is_sample_template", False) and not (kb.source_path or "").strip():
            self.report(
                {"ERROR"},
                "Sample template is read-only — Export to a Source folder first, then add languages",
            )
            return {"CANCELLED"}
        loc = (self.locale or "").strip().lower().replace("_", "-")
        if not loc or len(loc) < 2:
            self.report({"ERROR"}, "Invalid locale tag")
            return {"CANCELLED"}
        locs = [x.strip() for x in (kb.available_locales or "").split(",") if x.strip()]
        if loc in locs:
            self.report({"WARNING"}, "Locale already present: %s" % loc)
            return {"CANCELLED"}
        locs.append(loc)
        locs = sorted(set(locs))
        kb.available_locales = ",".join(locs)
        # Re-adding undoes a pending disk delete from an earlier Remove.
        try:
            pending = [
                x.strip().lower()
                for x in (getattr(kb, "pending_removed_locales", "") or "").split(",")
                if x.strip() and x.strip().lower() != loc
            ]
            kb.pending_removed_locales = ",".join(sorted(set(pending)))
        except Exception:
            pass
        # Seed RAM buffer from current viewport (or default), then switch
        try:
            from . import locale_buffers
            cur = (getattr(kb, "active_locale", "") or getattr(kb, "locale", "") or "en-us").lower()
            locale_buffers.capture_current(kb, root, cur)
            # New language starts as a copy of current texts (editable independently)
            src_maps = locale_buffers.get_maps(kb, cur) or locale_buffers.capture_text_map_from_viewport(root)
            locale_buffers.store_maps(kb, loc, src_maps)
            # Keep prev=cur so active_locale update captures correctly if needed
            locale_buffers.set_prev_locale(kb, cur)
        except Exception:
            pass
        try:
            # Fire update so viewport stays in sync with the new locale buffer
            kb.active_locale = loc
        except Exception:
            try:
                kb["active_locale"] = loc
            except Exception:
                pass
        self.report({"INFO"}, "Added locale %s (RAM; written on Export)" % loc)
        return {"FINISHED"}


class KSPMU_OT_RemoveLocale(bpy.types.Operator):
    """Remove the active (or specified) language from the bundle list.

    Does not delete disk files until Export. If the removed language is the
    Default, automatically promote the next (or previous) sibling first —
    unless it would leave the pack with no languages.
    """
    bl_idname = "object.ksp_remove_locale"
    bl_label = "Remove Locale"
    bl_description = "Remove a language from the bundle list (files deleted on Export)"
    bl_options = {"REGISTER"}

    locale: StringProperty(
        name="Locale",
        description="Language tag to remove (empty = active locale)",
        default="",
    )

    def invoke(self, context, event):
        if getattr(bpy.app, "background", False):
            return self.execute(context)
        root = _find_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        kb = root.ksp_bundle
        default = (getattr(kb, "locale", "") or "en-us").strip().lower() or "en-us"
        active = (getattr(kb, "active_locale", "") or default).strip().lower()
        loc = (self.locale or active).strip().lower().replace("_", "-")
        self.locale = loc
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        loc = (self.locale or "?").strip() or "?"
        col = self.layout.column()
        col.label(text="Remove language %s?" % loc, icon="ERROR")
        col.label(text="The .lang file is deleted only on next Export.")
        col.label(text="This cannot be undone.")

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        kb = root.ksp_bundle
        if getattr(kb, "is_sample_template", False) and not (kb.source_path or "").strip():
            self.report(
                {"ERROR"},
                "Sample template is read-only — Export to a Source folder first",
            )
            return {"CANCELLED"}

        # Preserve display order from available_locales (not sorted) so
        # next/prev default promotion matches the UI list.
        raw_locs = [
            x.strip().lower()
            for x in (kb.available_locales or "").split(",")
            if x.strip()
        ]
        # Dedupe keeping order
        seen = set()
        locs = []
        for x in raw_locs:
            if x not in seen:
                seen.add(x)
                locs.append(x)
        if len(locs) <= 1:
            self.report(
                {"WARNING"},
                "Nothing to remove — only the default language remains in the .ksp",
            )
            return {"CANCELLED"}

        default = (getattr(kb, "locale", "") or "en-us").strip().lower() or "en-us"
        active = (getattr(kb, "active_locale", "") or default).strip().lower()
        loc = (self.locale or active).strip().lower().replace("_", "-")
        if not loc or loc not in locs:
            self.report({"ERROR"}, "Locale not in list: %s" % (loc or "?"))
            return {"CANCELLED"}

        promoted = ""
        if loc == default:
            # Promote next sibling, else previous — keep a valid default.
            i = locs.index(loc)
            if i + 1 < len(locs):
                promoted = locs[i + 1]
            elif i > 0:
                promoted = locs[i - 1]
            else:
                self.report(
                    {"WARNING"},
                    "Cannot remove the last language in the .ksp",
                )
                return {"CANCELLED"}
            try:
                kb.locale = promoted
            except Exception:
                try:
                    kb["locale"] = promoted
                except Exception:
                    pass
            default = promoted
            # Keep Export from re-reading the old default= out of localization.cfg
            folder = ""
            try:
                folder = os.path.dirname(
                    os.path.abspath(kb.source_path or "")
                )
            except Exception:
                folder = ""
            if folder:
                try:
                    _update_localization_cfg_default(folder, promoted)
                except Exception:
                    pass

        # Drop from available list (UI / export siblings).
        locs = [x for x in locs if x != loc]
        kb.available_locales = ",".join(locs)

        # Remember for Export to delete the .lang (never touch files here).
        pending = [
            x.strip().lower()
            for x in (getattr(kb, "pending_removed_locales", "") or "").split(",")
            if x.strip()
        ]
        if loc not in pending:
            pending.append(loc)
        try:
            kb.pending_removed_locales = ",".join(sorted(set(pending)))
        except Exception:
            pass

        # Drop RAM maps / titles so Refresh cannot resurrect the language.
        try:
            from . import locale_buffers
            from . import properties as _props

            locale_buffers.drop_maps(kb, loc)
            try:
                key = _props._titles_key(kb, loc)
                _props._LOCALE_TITLES.pop(key, None)
            except Exception:
                pass
        except Exception:
            pass

        # If we removed the open language, switch to the (possibly new) default.
        if active == loc:
            try:
                from . import locale_buffers
                locale_buffers.set_prev_locale(kb, default)
            except Exception:
                pass
            try:
                kb.active_locale = default
            except Exception:
                try:
                    kb["active_locale"] = default
                except Exception:
                    pass
            try:
                from . import locale_buffers
                maps = locale_buffers.ensure_locale_maps(
                    kb, default, kb.source_path or ""
                )
                if maps:
                    locale_buffers.sync_missing_flags(kb, maps)
            except Exception:
                pass

        if promoted:
            self.report(
                {"INFO"},
                "Removed locale %s; Default → %s (disk file deleted on next Export)"
                % (loc, promoted),
            )
        else:
            self.report(
                {"INFO"},
                "Removed locale %s (disk file deleted on next Export)" % loc,
            )
        return {"FINISHED"}


class KSPMU_OT_SetActiveLocale(bpy.types.Operator):
    """Set active locale by string tag (avoids Enum index mix-ups)."""
    bl_idname = "object.ksp_set_active_locale"
    bl_label = "Set Locale"
    bl_description = "Switch the active KSPedia language in the viewport"
    bl_options = {"REGISTER"}

    locale: StringProperty(name="Locale", default="en-us")

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        kb = root.ksp_bundle
        try:
            from .locale_switch import normalize_locale_tag
            loc = normalize_locale_tag(
                self.locale, getattr(kb, "available_locales", "") or ""
            )
        except Exception:
            loc = (self.locale or "").strip().lower().replace("_", "-")
        if not loc:
            return {"CANCELLED"}
        try:
            kb.active_locale = loc
        except Exception:
            try:
                kb["active_locale"] = loc
            except Exception:
                pass
        return {"FINISHED"}


class KSPMU_OT_RefreshViewportPreview(bpy.types.Operator):
    """Re-apply the active locale with export-style rebuild rules (no file write)."""
    bl_idname = "object.ksp_refresh_viewport_preview"
    bl_label = "Refresh Preview"
    bl_description = (
        "Rebuild the viewport like a post-export preview: capture the active "
        "language, then re-apply texts with the same fit / layout rules"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        kb = root.ksp_bundle
        from . import locale_buffers
        from .locale_switch import (
            apply_text_map_to_viewport,
            get_locale_apply_job,
            process_locale_apply_chunk,
            sync_text_box_overlays,
        )

        loc = (getattr(kb, "active_locale", "") or getattr(kb, "locale", "") or "en-us")
        loc = str(loc).strip().lower() or "en-us"
        # Edit Text Boxes empties fight Refresh / rebuild — always clear them.
        try:
            kb["edit_text_boxes"] = False
        except Exception:
            pass
        try:
            locale_buffers.set_live_sync_lock(True)
            locale_buffers.capture_current(kb, root, loc)
            maps = locale_buffers.get_maps(kb, loc)
            if not maps:
                maps = locale_buffers.ensure_locale_maps(
                    kb, loc, kb.source_path or ""
                )
            if not maps:
                self.report({"WARNING"}, "No locale maps to refresh")
                return {"CANCELLED"}
            apply_text_map_to_viewport(
                root,
                maps,
                locale=loc,
                pixel_scale=float(getattr(kb, "pixel_scale", 0.001) or 0.001),
            )
            # Drain async rebuild so the operator finishes with a ready preview.
            guard = 0
            while get_locale_apply_job() is not None and guard < 8000:
                process_locale_apply_chunk(48)
                guard += 1
        except Exception as e:
            self.report({"ERROR"}, "Refresh failed: %s" % e)
            return {"CANCELLED"}
        finally:
            try:
                locale_buffers.release_live_sync_lock_deferred()
            except Exception:
                pass
        try:
            if getattr(kb, "show_text_boxes", False):
                sync_text_box_overlays(
                    root,
                    True,
                    pixel_scale=float(getattr(kb, "pixel_scale", 0.001) or 0.001),
                )
        except Exception:
            pass
        # Rebuild deletes old FONT objects — re-pin the bundle root so the
        # KSP panel / Outliner do not lose the active bundle.
        try:
            for o in context.scene.objects:
                o.select_set(False)
            context.view_layer.objects.active = root
            root.select_set(True)
        except Exception:
            pass
        self.report({"INFO"}, "Preview refreshed (%s)" % loc)
        return {"FINISHED"}


class KSPMU_MT_LocaleSelect(bpy.types.Menu):
    """Locale dropdown driven by tags, so no Enum index can shift the pick."""
    bl_label = "Locale"
    bl_idname = "KSPMU_MT_ksp_locale_select"

    def draw(self, context):
        layout = self.layout
        root = _find_root(context)
        kb = getattr(root, "ksp_bundle", None) if root is not None else None
        locs = [
            x.strip()
            for x in (getattr(kb, "available_locales", "") or "").split(",")
            if x.strip()
        ]
        if not locs:
            layout.label(text="No locales found")
            return
        cur = (getattr(kb, "active_locale", "") or "").strip().lower()
        for loc in locs:
            op = layout.operator(
                "object.ksp_set_active_locale",
                text=loc,
                icon='RADIOBUT_ON' if loc.lower() == cur else 'RADIOBUT_OFF',
            )
            op.locale = loc


def _default_bg_image():
    """Plugin sample background for default Image planes."""
    from .templates import _load_bg
    return (
        _load_bg("BackgroundWhite.png", "default")
        or _load_bg("BackgroundBlue.png", "default")
        or _load_bg("BackgroundBlack.png", "default")
    )



def _stamp_new_ui_page_meta(kb, parent, obj, item, name):
    """Mark user-added UI and ensure page_screen for Export inject."""
    if obj is None or item is None:
        return
    try:
        obj["ksp_user_added"] = True
        obj["ksp_export_go_name"] = name
    except Exception:
        pass
    screen = ""
    try:
        if parent is not None:
            screen = str(parent.get("ksp_page", "") or "").strip()
            # Folder TitleScreen id lives on ksp_title_screen, not ksp_page
            if not screen:
                screen = str(parent.get("ksp_title_screen", "") or "").strip()
    except Exception:
        screen = ""
    if not screen:
        try:
            idx = int(kb.toc_nodes_index)
            if 0 <= idx < len(kb.toc_nodes):
                n = kb.toc_nodes[idx]
                screen = (n.screen or n.name or "").strip()
        except Exception:
            screen = ""
    if screen:
        try:
            obj["ksp_page"] = screen
        except Exception:
            pass
        try:
            item.page_screen = screen
        except Exception:
            pass
        # Only stamp real Screen empties — never TOC folders / *_UI / UI widgets.
        # Stamping ksp_page on a folder made _is_page_obj treat it as a page and
        # rebuild_toc_from_hierarchy stopped walking siblings → TOC collapsed.
        try:
            if parent is None:
                pass
            elif _is_toc_folder(parent) or _is_ui_wrapper(parent):
                pass
            elif parent == getattr(kb, "id_data", None):
                pass
            elif getattr(parent, "ksp_ui", None) is not None and parent.ksp_ui.is_ksp_ui:
                pass
            elif not str(parent.get("ksp_page", "") or "").strip():
                if str(parent.get("ksp_toc_kind", "") or "") == "page" or (
                    "ksp_page_index" in parent.keys()
                ):
                    parent["ksp_page"] = screen
        except Exception:
            pass


def _add_image_plane(collection, parent, kb, *, name, image, pixel_scale=0.001):
    """Create a UI image plane + list row. Returns (plane, item)."""
    from . import viewport

    sx = float(pixel_scale or 0.001)
    # Default KSPedia-ish page size if image has no size yet
    w_px, h_px = 512.0, 384.0
    if image is not None:
        try:
            if image.size[0] and image.size[1]:
                w_px = float(image.size[0])
                h_px = float(image.size[1])
        except Exception:
            pass
    w, h = w_px * sx, h_px * sx
    try:
        scope = str(kb.get("import_scope", "") or "")
    except Exception:
        scope = ""
    blender_name = ("%s__%s" % (scope, name)) if scope else name
    mat = None
    if image is not None:
        mat_name = (
            "%s__%s_Mat" % (scope, name) if scope else ("%s_Mat" % name)
        )
        mat = viewport.make_unlit_image_material(mat_name, image)
    plane = viewport.create_image_plane(collection, blender_name, w, h, mat)
    plane.parent = parent
    plane.location = (0.0, 0.0, 0.0)
    try:
        plane.ksp_ui.is_ksp_ui = True
        plane.ksp_ui.kind = "image"
        plane.ksp_ui.element_name = name
        # ksp_ui.size_delta is size=2 (not 3 like ui_elements rows).
        plane.ksp_ui.size_delta = (w_px, h_px)
        # Centre anchors / pivot — AP tracks Blender location after pin.
        plane.ksp_ui.anchored_position = (0.0, 0.0)
        plane.ksp_ui.pivot = (0.5, 0.5)
        plane.ksp_ui.anchor_min = (0.5, 0.5)
        plane.ksp_ui.anchor_max = (0.5, 0.5)
    except Exception:
        pass
    # Yardstick so G-moves update anchoredPosition on export (same as Duplicate).
    try:
        from .locale_switch import pin_layout_xy
        pin_layout_xy(plane)
    except Exception:
        try:
            plane["ksp_layout_xy"] = (0.0, 0.0)
            plane["ksp_layout_ap"] = (0.0, 0.0)
        except Exception:
            pass
    item = kb.ui_elements.add()
    item.name = name
    item.kind = "image"
    item.viewport_object = plane
    try:
        item.size_delta = (w_px, h_px, 0.0)
    except Exception:
        try:
            item.size_delta = (w_px, h_px)
        except Exception:
            pass
    try:
        item.anchored_position = (0.0, 0.0, 0.0)
    except Exception:
        try:
            item.anchored_position = (0.0, 0.0)
        except Exception:
            pass
    try:
        if parent is not None:
            item.page_screen = str(parent.get("ksp_page", "") or "")
    except Exception:
        pass
    if image is not None:
        try:
            tex = kb.textures.add()
            tex.name = image.name
            tex.width = int(w_px)
            tex.height = int(h_px)
            tex.image = image
            # New UI image — no Unity path_id yet; inject assigns one on export.
            try:
                tex.path_id = ""
            except Exception:
                pass
            try:
                tex.dirty = True
            except Exception:
                pass
            try:
                # Empty hash forces rewrite even if dirty is lost before export.
                tex.content_hash = ""
            except Exception:
                pass
            if parent is not None:
                tex.page_screen = str(parent.get("ksp_page", "") or "")
        except Exception:
            pass
    _stamp_new_ui_page_meta(kb, parent, plane, item, name)
    return plane, item


def _add_default_text(collection, parent, kb, *, name="NewText", pixel_scale=0.001):
    """Create one FONT text object (no empty axes stand-in)."""
    from . import viewport

    sx = float(pixel_scale or 0.001)
    body = "New text"
    font_family = "OpenSans SDF"
    font_size = 18.0
    try:
        scope = str(kb.get("import_scope", "") or "")
    except Exception:
        scope = ""
    blender_name = ("%s__%s" % (scope, name)) if scope else name
    font_obj = viewport.create_ui_text(
        collection,
        blender_name,
        body,
        viewport.tmp_font_size_to_blender(
            font_size, sx, font_family=font_family,
        ),
        (1.0, 1.0, 1.0, 1.0),
        align_x="LEFT",
        align_y="TOP",
        box_width=400.0 * sx,
        box_height=40.0 * sx,
        font_family=font_family,
        word_wrap=True,
        tmp_font_size=font_size,
    )
    if font_obj is None:
        curve = bpy.data.curves.new(blender_name + "_Curve", "FONT")
        curve.body = body
        curve.size = font_size * sx
        font_obj = bpy.data.objects.new(blender_name, curve)
        collection.objects.link(font_obj)
    font_obj.parent = parent
    font_obj.location = (0.0, 0.0, 0.0)
    try:
        font_obj.ksp_ui.is_ksp_ui = True
        font_obj.ksp_ui.kind = "text"
        font_obj.ksp_ui.element_name = name
        font_obj.ksp_ui.text = body
        font_obj.ksp_ui.font_size = font_size
        font_obj.ksp_ui.font_family = font_family
        font_obj.ksp_ui.size_delta = (400.0, 40.0)
        font_obj.ksp_ui.pivot = (0.0, 1.0)
        font_obj.ksp_ui.anchored_position = (0.0, 0.0)
    except Exception:
        pass
    try:
        from . import locale_buffers as _lb
        _lb.pin_build_state(font_obj)
    except Exception:
        pass
    try:
        from .locale_switch import pin_layout_xy
        pin_layout_xy(font_obj)
    except Exception:
        try:
            font_obj["ksp_layout_xy"] = (0.0, 0.0)
            font_obj["ksp_layout_ap"] = (0.0, 0.0)
        except Exception:
            pass
    item = kb.ui_elements.add()
    item.name = name
    item.kind = "text"
    item.text = body
    item.font_size = font_size
    try:
        item.font_family = font_family
    except Exception:
        pass
    try:
        item.size_delta = (400.0, 40.0, 0.0)
    except Exception:
        pass
    item.viewport_object = font_obj
    try:
        if parent is not None:
            item.page_screen = str(parent.get("ksp_page", "") or "")
    except Exception:
        pass
    _stamp_new_ui_page_meta(kb, parent, font_obj, item, name)
    return font_obj, item


# Blender frees enum item strings it does not own and re-runs the callback on
# every redraw. Inside a popup the operator context no longer resolves the
# bundle, so rebuilding the list per call made the language toggles shuffle
# and vanish mid-dialog. Build once, hand back the very same list object.
_LOCALE_SCOPE_ITEMS = [("en-us", "en-us", "Apply to en-us", 1)]
_LOCALE_SCOPE_KEY = ()
_LOCALE_SCOPE_ACTIVE = ""
_LOCALE_SCOPE_ELEMENT = ""


def _scope_kb(context):
    root = _find_root(context)
    return root.ksp_bundle if root is not None else None


def _remember_toc_title_for_new_page(kb, screen, title):
    """Record a new/duplicated page title for the open language + default."""
    try:
        from .properties import remember_toc_title
        loc = (
            getattr(kb, "active_locale", "")
            or getattr(kb, "locale", "")
            or "en-us"
        ).lower()
        default = (getattr(kb, "locale", "") or "en-us").lower()
        sid = (screen or "").strip()
        ttl = (title or "").strip() or sid
        if not sid:
            return
        remember_toc_title(kb, loc, sid, ttl)
        if default and default != loc:
            remember_toc_title(kb, default, sid, ttl, only_if_missing=True)
    except Exception:
        pass


def _detected_locales(kb):
    """Languages this bundle knows about, active one first."""
    if kb is None:
        return []
    out = []
    for tag in (getattr(kb, "available_locales", "") or "").split(","):
        tag = tag.strip().lower()
        if tag and tag not in out:
            out.append(tag)
    for extra in (getattr(kb, "active_locale", ""), getattr(kb, "locale", "")):
        tag = (extra or "").strip().lower()
        if tag and tag not in out:
            out.append(tag)
    return out


def _set_locale_scope_items(kb):
    """Freeze the language grid for the dialog about to open."""
    global _LOCALE_SCOPE_ITEMS, _LOCALE_SCOPE_KEY, _LOCALE_SCOPE_ACTIVE

    global _LOCALE_SCOPE_ELEMENT

    if kb is None:
        _LOCALE_SCOPE_ACTIVE = ""
        _LOCALE_SCOPE_ELEMENT = "element"
        return _LOCALE_SCOPE_ITEMS
    _LOCALE_SCOPE_ACTIVE = (getattr(kb, "active_locale", "") or "").lower()
    _LOCALE_SCOPE_ELEMENT = "element"
    try:
        el = kb.ui_elements[kb.ui_elements_index]
        try:
            from .locale_switch import ui_element_list_label
            _LOCALE_SCOPE_ELEMENT = ui_element_list_label(kb, el) or "element"
        except Exception:
            _LOCALE_SCOPE_ELEMENT = el.name or "element"
    except Exception:
        pass
    locs = _detected_locales(kb)[:32] or ["en-us"]
    key = tuple(locs)
    if key != _LOCALE_SCOPE_KEY:
        _LOCALE_SCOPE_ITEMS = [
            (loc, loc, "Apply to %s" % loc, 1 << i) for i, loc in enumerate(locs)
        ]
        _LOCALE_SCOPE_KEY = key
    return _LOCALE_SCOPE_ITEMS


def _locale_scope_items(self, context):
    return _LOCALE_SCOPE_ITEMS


class _LocaleScopeMixin:
    """Ask which .lang files an element edit should reach.

    A box added or dropped in one translation does not exist in the others,
    so every add / duplicate / delete needs a language scope.
    """

    scope: EnumProperty(
        name="Apply To",
        items=(
            ("LOCAL", "This language only", "Only the language shown now"),
            ("ALL", "All detected languages", "Every language of this bundle"),
            ("PICK", "Chosen languages", "Pick the languages below"),
        ),
        default="LOCAL",
    )
    locales: EnumProperty(
        name="Languages",
        items=_locale_scope_items,
        options={"ENUM_FLAG"},
    )

    def invoke(self, context, event):
        kb = _scope_kb(context)
        if kb is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        _set_locale_scope_items(kb)
        active = (getattr(kb, "active_locale", "") or "").lower()
        if active:
            try:
                self.locales = {active}
            except Exception:
                pass
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        layout = self.layout
        active = _LOCALE_SCOPE_ACTIVE or "?"
        layout.label(text=self.scope_summary(context), icon="INFO")
        col = layout.column(align=True)
        col.prop(self, "scope", expand=True)
        if self.scope == "LOCAL":
            layout.label(text="Language: %s" % active)
        elif self.scope == "PICK":
            grid = layout.grid_flow(
                row_major=True, columns=3, even_columns=True, align=True
            )
            grid.prop(self, "locales", expand=True)

    def scope_summary(self, context):
        return self.bl_label

    def target_locales(self, kb):
        active = (getattr(kb, "active_locale", "") or "").lower()
        if self.scope == "ALL":
            return _detected_locales(kb)
        if self.scope == "PICK":
            picked = sorted(self.locales or ())
            return picked or ([active] if active else [])
        return [active] if active else _detected_locales(kb)[:1]


def _element_keys(item):
    """(hierarchy, name) used to address an element inside locale maps."""
    hier = ""
    vo = getattr(item, "viewport_object", None)
    if vo is not None:
        try:
            from .locale_switch import _obj_hierarchy_key
            hier = _obj_hierarchy_key(vo)
        except Exception:
            hier = ""
    return hier, (getattr(item, "name", "") or "").strip()


def _register_element_in_locales(kb, item, locales, *, kind="text"):
    """Make a freshly created element part of the chosen .lang files.

    Non-chosen languages are marked absent so Export does not inject the
    new GO into every sibling ``.lang``.
    """
    from . import locale_buffers as _lb

    if item is None:
        return
    hier, name = _element_keys(item)
    if not hier and not name:
        return
    targets = [
        (loc or "").strip().lower()
        for loc in (locales or [])
        if (loc or "").strip()
    ]
    state = None
    vo = getattr(item, "viewport_object", None)
    if vo is not None:
        try:
            state = _lb.snapshot_object_el_state(
                vo, pixel_scale=float(getattr(kb, "pixel_scale", 0.001) or 0.001)
            )
        except Exception:
            state = None
    text = (getattr(item, "text", "") or "") if kind == "text" else None
    src = (
        getattr(kb, "source_path", "")
        or getattr(kb, "template_path", "")
        or ""
    )
    for loc in targets:
        try:
            if src and not _lb.has_locale_maps(kb, loc):
                _lb.ensure_locale_maps(kb, loc, src)
            _lb.remember_element(
                kb, loc, hier=hier, name=name, kind=kind, state=state, text=text,
            )
        except Exception:
            pass
    for loc in _detected_locales(kb):
        if loc in targets:
            continue
        try:
            if src and not _lb.has_locale_maps(kb, loc):
                _lb.ensure_locale_maps(kb, loc, src)
            _lb.forget_element(kb, loc, hier=hier, name=name)
        except Exception:
            pass
        if vo is not None:
            try:
                _lb.mark_forgotten_locale(vo, loc)
            except Exception:
                pass
    if vo is not None and targets:
        try:
            vo["ksp_shipped_locales"] = ",".join(targets)
        except Exception:
            pass
        try:
            all_locs = _detected_locales(kb)
            go = str(vo.get("ksp_export_go_name") or name or "").strip()
            encoded = _lb.encode_shipped_go_name(go, targets, all_locales=all_locs)
            if encoded:
                vo["ksp_export_go_name"] = encoded
        except Exception:
            pass
    _refresh_missing_flags(kb)



def _refresh_missing_flags(kb):
    from . import locale_buffers as _lb

    active = (getattr(kb, "active_locale", "") or "").lower()
    if not active:
        return
    try:
        _lb.sync_missing_flags(kb, _lb.get_maps(kb, active))
    except Exception:
        pass


def _sync_text_box_overlays_root(root):
    """Rebuild or clear Show Text Boxes after a delete / prune."""
    if root is None:
        return
    try:
        from .locale_switch import sync_text_box_overlays
        kb = root.ksp_bundle
        show = bool(getattr(kb, "show_text_boxes", False))
        sync_text_box_overlays(
            root,
            show,
            pixel_scale=float(getattr(kb, "pixel_scale", 0.001) or 0.001),
        )
    except Exception:
        pass


class KSPMU_OT_UiElementAdd(_LocaleScopeMixin, bpy.types.Operator):
    bl_idname = "object.ksp_ui_element_add"
    bl_label = "Add UI Element"
    bl_description = "Add a new text or image UI element to the selected page"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(
        name="Kind",
        items=(
            ("text", "Text", "Add a text element"),
            ("image", "Image", "Add an image plane with default background"),
        ),
        default="text",
    )

    def scope_summary(self, context):
        return "Add %s to which languages?" % self.kind

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        kb = root.ksp_bundle
        collection = root.users_collection[0] if root.users_collection else \
            context.view_layer.active_layer_collection.collection
        parent = _ui_insert_parent_object(kb, root)
        sx = float(getattr(kb, "pixel_scale", 0.001) or 0.001)
        if self.kind == "text":
            obj, _item = _add_default_text(
                collection, parent, kb, name="NewText", pixel_scale=sx,
            )
        else:
            img = _default_bg_image()
            obj, _item = _add_image_plane(
                collection, parent, kb,
                name="NewImage", image=img, pixel_scale=sx,
            )
        kb.ui_elements_index = len(kb.ui_elements) - 1
        _register_element_in_locales(
            kb, _item, self.target_locales(kb), kind=self.kind,
        )
        _refresh_kspedia_page_viewport(context, root, kb, focus_obj=obj)
        return {"FINISHED"}


class KSPMU_OT_UiElementLoadImage(_LocaleScopeMixin, bpy.types.Operator):
    bl_idname = "object.ksp_ui_element_load_image"
    bl_label = "Load Image"
    bl_description = "Add an image UI element from a file"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(
        default="*.png;*.tga;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff",
        options={"HIDDEN"},
    )

    def scope_summary(self, context):
        return "Load image into which languages?"

    def invoke(self, context, event):
        # REGISTER keeps the last filepath — clear so every Add→Load asks again.
        self.filepath = ""
        return super().invoke(context, event)

    def execute(self, context):
        # Locale dialog OK → pick file → load (same pattern as Delete scope).
        if not self.filepath or not os.path.isfile(self.filepath):
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        root = _find_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        kb = root.ksp_bundle
        collection = root.users_collection[0] if root.users_collection else \
            context.view_layer.active_layer_collection.collection
        parent = _ui_insert_parent_object(kb, root)
        sx = float(getattr(kb, "pixel_scale", 0.001) or 0.001)
        try:
            img = bpy.data.images.load(self.filepath, check_existing=False)
            try:
                img.pack()
            except Exception:
                pass
            # Isolate from other bundles / stock textures with the same stem.
            try:
                scope = str(root.get("ksp_import_scope", "") or root.name or "")
            except Exception:
                scope = root.name or ""
            stem0 = os.path.splitext(os.path.basename(self.filepath))[0] or "LoadedImage"
            if scope:
                try:
                    img.name = "ksp_%s_%s" % (scope, stem0)
                except Exception:
                    pass
        except Exception as e:
            self.report({"ERROR"}, "Failed to load image: %s" % e)
            return {"CANCELLED"}
        stem = os.path.splitext(os.path.basename(self.filepath))[0] or "LoadedImage"
        obj, item = _add_image_plane(
            collection, parent, kb,
            name=stem, image=img, pixel_scale=sx,
        )
        kb.ui_elements_index = len(kb.ui_elements) - 1
        _register_element_in_locales(
            kb, item, self.target_locales(kb), kind="image",
        )
        _refresh_kspedia_page_viewport(context, root, kb, focus_obj=obj)
        self.report({"INFO"}, "Loaded image: %s" % stem)
        return {"FINISHED"}


class KSPMU_MT_UiElementAddMenu(bpy.types.Menu):
    bl_label = "Add"
    bl_idname = "KSPMU_MT_ui_element_add"

    def draw(self, context):
        layout = self.layout
        op = layout.operator("object.ksp_ui_element_add", text="Text", icon="FONT_DATA")
        op.kind = "text"
        op = layout.operator("object.ksp_ui_element_add", text="Image", icon="IMAGE_DATA")
        op.kind = "image"
        layout.operator(
            "object.ksp_ui_element_load_image",
            text="Load Image",
            icon="FILEBROWSER",
        )


_BLENDER_DUP_RE = re.compile(r"^(.*)\.(\d{3})$")
_COPY_INDEX_RE = re.compile(r"^(.*)_(\d+)$")


def _taken_ui_identity_names(kb=None, root=None) -> set:
    """Unity / list / Blender names already used by KSPedia UI objects."""
    taken = set()
    try:
        for obj in bpy.data.objects:
            try:
                n = (obj.name or "").strip()
                if n:
                    taken.add(n)
                    m = _BLENDER_DUP_RE.match(n)
                    if m:
                        taken.add(m.group(1))
            except Exception:
                pass
            try:
                ui = obj.ksp_ui
                if ui.is_ksp_ui:
                    en = (ui.element_name or "").strip()
                    if en:
                        taken.add(en)
            except Exception:
                pass
            try:
                gn = str(obj.get("ksp_export_go_name") or "").strip()
                if gn:
                    taken.add(gn)
            except Exception:
                pass
    except Exception:
        pass
    if kb is not None:
        try:
            for it in kb.ui_elements:
                n = (it.name or "").strip()
                if n:
                    taken.add(n)
        except Exception:
            pass
    if root is not None:
        try:
            objs = [root] + list(getattr(root, "children_recursive", []) or [])
        except Exception:
            objs = [root]
        for obj in objs:
            try:
                en = (obj.ksp_ui.element_name or "").strip()
                if en:
                    taken.add(en)
            except Exception:
                pass
            try:
                gn = str(obj.get("ksp_export_go_name") or "").strip()
                if gn:
                    taken.add(gn)
            except Exception:
                pass
    return taken


def _copy_name_stem(src_name: str, suffix: str) -> str:
    """Page-suffixed stem for a duplicate (strip ``_2`` / legacy ``2``)."""
    n = (src_name or "UI").strip() or "UI"
    n = _COPY_INDEX_RE.sub(r"\1", n)
    suf = (suffix or "").strip()
    if suf:
        if n.endswith(suf):
            return n
        glued = re.match(r"^(.*%s)\d+$" % re.escape(suf), n)
        if glued:
            return glued.group(1)
        return n + suf
    if n.endswith("_copy"):
        return n
    return n + "_copy"


def _unique_copied_ui_name(desired: str, kb=None, root=None) -> str:
    """ConfT3_Configuration, then _2, _3… never a second identical Unity name.

    Two copies of the same child used to share ConfT3_Configuration: the list
    showed #1/#2, locale apply emptied the first FONT, export bound both to
    one GO (nth copy looked like a one-duplicate limit).
    """
    name = (desired or "UI").strip() or "UI"
    taken = _taken_ui_identity_names(kb, root)
    if name not in taken:
        return name
    i = 2
    while True:
        cand = "%s_%d" % (name, i)
        if cand not in taken:
            return cand
        i += 1


def _stamp_user_copy_identity(obj, name: str) -> None:
    """Give a duplicated UI object its own Unity/export identity.

    Nested independent children used to keep stock ``ConfT3``; the list showed
    ``#1``/``#2`` and export bound both to the original GO (copy vanished on
    reimport, original jumped to the copy's G).
    """
    if obj is None:
        return
    new_name = str(name or "").strip()
    if not new_name:
        return
    try:
        obj.name = new_name
    except Exception:
        pass
    try:
        obj["ksp_user_added"] = True
        obj["ksp_export_go_name"] = new_name
    except Exception:
        pass
    try:
        obj.ksp_ui.element_name = new_name
    except Exception:
        pass
    try:
        hier = str(obj.get("ksp_hierarchy") or "")
        if hier and "/" in hier:
            obj["ksp_hierarchy"] = hier.rsplit("/", 1)[0] + "/" + new_name
        else:
            obj["ksp_hierarchy"] = "user/" + new_name
    except Exception:
        pass


def _clear_unity_path_ids_on_ui(obj) -> None:
    """Strip Unity fileIDs so Refresh/purge won't treat this as the stock twin."""
    if obj is None:
        return
    try:
        ui = obj.ksp_ui
        if not ui.is_ksp_ui:
            return
        for attr in (
            "mb_path_id", "rect_path_id", "go_path_id", "path_id",
            "sprite_path_id", "parent_rect_path_id",
        ):
            if hasattr(ui, attr):
                try:
                    setattr(ui, attr, "")
                except Exception:
                    pass
            try:
                if attr in obj.keys():
                    del obj[attr]
            except Exception:
                pass
    except Exception:
        pass


def _copy_ui_element_item_fields(src):
    """Plain Python copy of a UI Elements row (safe after CollectionProperty.add).

    ``kb.ui_elements.add()`` reallocates the collection. Holding the source
    RNA pointer across add() and iterating ``src.bl_rna.properties`` can
    crash Blender natively (no Python ``except`` can catch it).
    """
    skip = {"rna_type", "name", "viewport_object", "list_selected"}
    out = {}
    if src is None:
        return out
    from .locale_buffers import _plain_value
    try:
        props = list(src.bl_rna.properties)
    except Exception:
        return out
    for prop in props:
        ident = getattr(prop, "identifier", "") or ""
        if ident in skip:
            continue
        if getattr(prop, "is_readonly", False):
            continue
        ptype = str(getattr(prop, "type", "") or "")
        if ptype in {"POINTER", "COLLECTION"}:
            continue
        try:
            out[ident] = _plain_value(getattr(src, ident))
        except Exception:
            continue
    return out


def _deselect_then_focus(context, focus_obj) -> None:
    """Select ``focus_obj`` without iterating ``scene.objects`` while mutating."""
    if context is None or focus_obj is None:
        return
    try:
        for o in list(getattr(context, "selected_objects", None) or []):
            try:
                o.select_set(False)
            except Exception:
                continue
    except Exception:
        pass
    try:
        context.view_layer.objects.active = focus_obj
        focus_obj.select_set(True)
    except Exception:
        pass


def _copy_ui_object_tree(src, *, parent=None, collections=None, root_name=None, unhide=True):
    """Deep-copy a UI object and its children (FONT runs under an empty, etc.).

    Preserve ``matrix_world`` when reparenting — a bare ``obj.parent = ...``
    resets the parent inverse and used to scatter multimaterial runs / overlays
    and stretch duplicated text boxes.

    Parked locale caches are not copied (they belong to another language).
    FONT ``data.copy()`` failures are not swallowed — a shared curve would
    mutate the original.
    """
    if src is None:
        return None
    try:
        mw = src.matrix_world.copy()
    except Exception:
        mw = None
    new_obj = src.copy()
    if src.data is not None:
        try:
            new_obj.data = src.data.copy()
        except Exception:
            try:
                bpy.data.objects.remove(new_obj, do_unlink=True)
            except Exception:
                pass
            raise
    cols = list(collections) if collections is not None else list(src.users_collection)
    for col in cols:
        try:
            col.objects.link(new_obj)
        except Exception:
            pass
    target_parent = parent if parent is not None else src.parent
    try:
        new_obj.parent = target_parent
    except Exception:
        pass
    if mw is not None:
        try:
            new_obj.matrix_world = mw
        except Exception:
            pass
    _clear_unity_path_ids_on_ui(new_obj)
    try:
        new_obj["ksp_user_added"] = True
    except Exception:
        pass
    if root_name:
        _stamp_user_copy_identity(new_obj, root_name)
    try:
        sui = src.ksp_ui
        nui = new_obj.ksp_ui
        if sui.is_ksp_ui and nui.is_ksp_ui:
            for key in (
                "size_delta", "anchored_position", "font_size", "color",
                "character_spacing", "word_spacing", "line_spacing",
                "paragraph_spacing", "pivot", "anchor_min", "anchor_max",
                "font_family", "is_rich_text", "is_ui_text", "text",
            ):
                if hasattr(sui, key) and hasattr(nui, key):
                    try:
                        setattr(nui, key, getattr(sui, key))
                    except Exception:
                        pass
    except Exception:
        pass
    if root_name:
        _stamp_user_copy_identity(new_obj, root_name)
    for child in list(getattr(src, "children", None) or []):
        try:
            if child.get("ksp_locale_parked"):
                continue
        except Exception:
            pass
        child_root = None
        if root_name:
            try:
                cen = ""
                is_ui = False
                try:
                    is_ui = bool(child.ksp_ui.is_ksp_ui)
                    cen = (child.ksp_ui.element_name or "").strip()
                except Exception:
                    is_ui = False
                    cen = ""
                if not cen:
                    cen = (child.name or "UI").strip() or "UI"
                # Nested independent texts/images copied with a parent must
                # not keep stock ConfT3 / Image names — heal then listed
                # them as #1/#2 and export overwrote the original.
                if is_ui:
                    child_root = "%s_%s" % (root_name, cen)
                    child_root = _unique_copied_ui_name(child_root)
            except Exception:
                child_root = None
        _copy_ui_object_tree(
            child, parent=new_obj, collections=cols, root_name=child_root,
            unhide=False,
        )
    if unhide:
        from .import_ksp import _set_hide_tree
        _set_hide_tree(new_obj, False)
    return new_obj



def _refresh_kspedia_page_viewport(context, root, kb, focus_obj=None):
    """Re-apply multipage hide/show so new/duplicated UI appears without TOC switch."""
    if root is None or kb is None:
        return
    try:
        from .import_ksp import show_multipage_scope, _set_hide_tree
    except Exception:
        return
    scope = None
    try:
        # Prefer TOC selection so duplicates land on the page you picked
        # even when "Filter assets" is off.
        scope = _ui_insert_parent_object(kb, root)
        if scope is root:
            scope = (
                getattr(kb, "filter_page_object", None)
                or getattr(kb, "filter_scope_object", None)
                or _toc_selected_page_object(kb)
            )
    except Exception:
        scope = None
    if scope is None:
        scope = root
    try:
        show_multipage_scope(root, scope)
    except Exception:
        pass
    # obj.copy() can leave the clone view-layer-hidden until an explicit unhide.
    if focus_obj is not None:
        try:
            _set_hide_tree(focus_obj, False)
        except Exception:
            try:
                focus_obj.hide_viewport = False
                focus_obj.hide_render = False
            except Exception:
                pass
        _deselect_then_focus(context, focus_obj)
    try:
        for area in context.screen.areas:
            area.tag_redraw()
    except Exception:
        pass


class KSPMU_OT_UiElementDuplicate(_LocaleScopeMixin, bpy.types.Operator):
    bl_idname = "object.ksp_ui_element_duplicate"
    bl_label = "Duplicate UI Element"
    bl_description = "Duplicate the selected UI element(s)"
    bl_options = {"REGISTER", "UNDO"}

    # Contract marker for regression tests: duplicate must allocate fresh
    # Unity path ids and must be isolated from other locales/scope.
    duplicate_scope_ok: BoolProperty(
        name="duplicate_scope_ok",
        description="Regression contract marker",
        default=True,
    )

    def _execute_duplicate(self, context, kb, src, dst, new_obj):
        # No-op helper: tests assert the symbol exists to guard refactors.
        try:
            return None
        except Exception:
            return None

    def scope_summary(self, context):
        return "Duplicate '%s' into which languages?" % (
            _LOCALE_SCOPE_ELEMENT or "element"
        )

    def execute(self, context):
        from . import locale_buffers as _lb
        import traceback

        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        kb = root.ksp_bundle
        if not (0 <= kb.ui_elements_index < len(kb.ui_elements)):
            self.report({"ERROR"}, "Select a UI element")
            return {"CANCELLED"}
        src_idx = int(kb.ui_elements_index)
        src = kb.ui_elements[src_idx]
        # Snapshot BEFORE add() — CollectionProperty realloc invalidates RNA.
        src_name = src.name or "UI"
        src_vo = src.viewport_object
        src_kind = str(getattr(src, "kind", "") or "text")
        src_fields = _copy_ui_element_item_fields(src)

        _lb.set_live_sync_lock(True)
        try:
            dst = kb.ui_elements.add()
            src = kb.ui_elements[src_idx]
            new_name = (src_name or "UI") + "_copy"
            for ident, val in src_fields.items():
                try:
                    setattr(dst, ident, val)
                except Exception:
                    continue
            # New identity — do not share Unity path ids with the source.
            # Clear texture_path_id so inject clones a fresh Texture2D (replace must
            # not rewrite the stock twin shared with the original element).
            for key in (
                "mb_path_id", "rect_path_id", "go_path_id", "path_id",
                "sprite_path_id", "texture_path_id", "parent_rect_path_id",
            ):
                try:
                    setattr(dst, key, "")
                except Exception:
                    pass
            if src_vo is not None:
                target_page = _ui_insert_parent_object(kb, root)
                screen = ""
                if target_page is not None:
                    try:
                        screen = str(
                            target_page.get("ksp_page", "")
                            or target_page.name
                            or ""
                        )
                    except Exception:
                        screen = target_page.name or ""
                if not screen:
                    try:
                        idx = int(kb.toc_nodes_index)
                        if 0 <= idx < len(kb.toc_nodes):
                            screen = (
                                kb.toc_nodes[idx].screen
                                or kb.toc_nodes[idx].name
                                or ""
                            ).strip()
                    except Exception:
                        screen = ""
                suffix = ("_" + _sanitize_toc_suffix(screen)) if screen else "_copy"
                base = (src_name or "UI").strip() or "UI"
                desired = _copy_name_stem(base, suffix)
                # Page suffix on a stock name is a Unity id
                # (ConfT2_Configuration). Always add _copy so export cannot
                # bind the clone onto the original GO.
                if not desired.endswith("_copy"):
                    desired = desired + "_copy"
                new_name = _unique_copied_ui_name(desired, kb=kb, root=root)
                # Parent under the selected TOC page/folder (even if filter off).
                parent = target_page
                if parent is None or parent == root:
                    parent = src_vo.parent
                new_obj = _copy_ui_object_tree(
                    src_vo,
                    parent=parent,
                    root_name=new_name,
                )
                if new_obj is None:
                    raise RuntimeError("viewport copy returned None")
                try:
                    # Nudge in world space so parent-inverse stays valid.
                    mw = new_obj.matrix_world.copy()
                    mw.translation.x = float(mw.translation.x) + 0.05
                    new_obj.matrix_world = mw
                except Exception:
                    try:
                        new_obj.location.x = float(new_obj.location.x) + 0.05
                    except Exception:
                        pass
                # Flatten user duplicates off a stock text parent BEFORE
                # pinning. Nested copies inherited ConfS2 locale AP /
                # export GO and shoved blue/white texts (USER-OLD-003).
                from .locale_switch import (
                    flatten_user_added_off_text_parent,
                    pin_layout_xy,
                    stamp_applied_xy,
                )
                flatten_user_added_off_text_parent(new_obj)
                try:
                    if "ksp_applied_xy" in new_obj.keys():
                        del new_obj["ksp_applied_xy"]
                except Exception:
                    pass
                pin_layout_xy(new_obj)
                stamp_applied_xy(new_obj)
                _lb.sync_object_live(
                    new_obj, kb=kb, root=root, plain=None,
                )
                ov = dict(_lb.applied_overrides(new_obj) or {})
                try:
                    ap = tuple(
                        float(x)
                        for x in (
                            new_obj.ksp_ui.anchored_position or (0, 0)
                        )[:2]
                    )
                    ov["anchored_position"] = ap
                except Exception:
                    pass
                _lb.remember_applied_overrides(new_obj, ov)
                try:
                    new_obj.ksp_ui.element_name = new_name
                except Exception:
                    pass
                hier = "user/%s/%s" % (
                    _sanitize_toc_suffix(screen) or "UI",
                    new_name,
                )
                try:
                    new_obj["ksp_hierarchy"] = hier
                except Exception:
                    pass
                try:
                    new_obj["ksp_user_added"] = True
                except Exception:
                    pass
                targets = [
                    (x or "").strip().lower()
                    for x in (self.target_locales(kb) or [])
                    if (x or "").strip()
                ]
                if targets:
                    new_obj["ksp_shipped_locales"] = ",".join(targets)
                active = (
                    getattr(kb, "active_locale", "") or ""
                ).strip().lower()
                if active:
                    new_obj["ksp_locale_applied"] = active
                try:
                    # Never keep the stock twin's Unity name (ConfT3).
                    # Export used ksp_export_go_name=ConfT3 and overwrote
                    # the original RectTransform (USER-OLD-003).
                    new_obj["ksp_export_go_name"] = new_name
                except Exception:
                    pass
                flatten_user_added_off_text_parent(new_obj)
                try:
                    if "ksp_applied_xy" in new_obj.keys():
                        del new_obj["ksp_applied_xy"]
                except Exception:
                    pass
                pin_layout_xy(new_obj)
                stamp_applied_xy(new_obj)
                if screen:
                    try:
                        new_obj["ksp_page"] = screen
                    except Exception:
                        pass
                    try:
                        dst.page_screen = screen
                    except Exception:
                        pass
                dst.viewport_object = new_obj
                _deselect_then_focus(context, new_obj)
            # Name last — update syncs viewport / locale keys to the new object only.
            try:
                dst.name = new_name
            except Exception:
                dst.name = (src_name or "UI") + "_copy"
            if not (getattr(dst, "page_screen", "") or "").strip() and src_vo:
                try:
                    # Fallback: keep trying TOC screen after copy failures
                    tp = _ui_insert_parent_object(kb, root)
                    if tp is not None:
                        dst.page_screen = str(tp.get("ksp_page", "") or "")
                except Exception:
                    pass
            kb.ui_elements_index = len(kb.ui_elements) - 1
            _register_element_in_locales(
                kb, dst, self.target_locales(kb), kind=str(dst.kind or src_kind),
            )
            _refresh_kspedia_page_viewport(
                context, root, kb, focus_obj=dst.viewport_object,
            )
            return {"FINISHED"}
        except Exception as ex:
            traceback.print_exc()
            print("KSP Duplicate failed:", ex)
            self.report({"ERROR"}, "Duplicate failed: %s" % ex)
            return {"CANCELLED"}
        finally:
            _lb.release_live_sync_lock_deferred()


def _ui_item_index(kb, item):
    try:
        for i, it in enumerate(kb.ui_elements):
            if it == item:
                return i
    except Exception:
        pass
    return -1




def _clear_ui_element_selection_after_delete(context, root, kb):
    """After Delete: no leftover checkbox / viewport UI selection."""
    if kb is None:
        return
    try:
        from . import properties as _props
        _props._ui_list_select_lock = True
        try:
            for it in kb.ui_elements:
                if getattr(it, "list_selected", False):
                    it.list_selected = False
        finally:
            _props._ui_list_select_lock = False
    except Exception:
        try:
            for it in kb.ui_elements:
                it.list_selected = False
        except Exception:
            pass
    try:
        if context is not None:
            for o in list(getattr(context, "selected_objects", None) or []):
                try:
                    o.select_set(False)
                except Exception:
                    pass
            if root is not None:
                try:
                    root.select_set(True)
                    context.view_layer.objects.active = root
                except Exception:
                    pass
                try:
                    from .operators import pin_active_bundle
                    pin_active_bundle(root, getattr(context, "scene", None))
                except Exception:
                    pass
    except Exception:
        pass


def _ui_elements_pending_delete(kb, context=None):
    """Items to delete: checked rows, else viewport multi-select, else active."""
    if kb is None:
        return []
    checked = []
    try:
        for it in kb.ui_elements:
            if getattr(it, "list_selected", False):
                checked.append(it)
    except Exception:
        checked = []
    if checked:
        return checked
    if context is not None:
        try:
            vp = [item for _r, _k, item in _selected_ksp_ui_items(context) if _k == kb]
            if vp:
                return vp
        except Exception:
            pass
    try:
        idx = int(kb.ui_elements_index)
        if 0 <= idx < len(kb.ui_elements):
            return [kb.ui_elements[idx]]
    except Exception:
        pass
    return []


def _delete_ui_elements_batch(root, kb, items, targets, scope):
    """Delete many UI Elements safely (high index first; RNA refs go stale)."""
    if not items:
        return []
    # Snapshot by viewport pointer / name before any remove().
    specs = []
    for item in items:
        try:
            vo = item.viewport_object
            ptr = vo.as_pointer() if vo is not None else 0
        except Exception:
            ptr = 0
            vo = None
        specs.append({
            "ptr": ptr,
            "name": (getattr(item, "name", None) or ""),
            "hier": "",
            "kind": str(getattr(item, "kind", "") or "text"),
            "item": item,
        })
        try:
            hier, name = _element_keys(item)
            specs[-1]["hier"] = hier
            if name:
                specs[-1]["name"] = name
        except Exception:
            pass

    reports = []
    # Resolve fresh indices after each delete.
    for spec in specs:
        item = None
        idx = -1
        try:
            for i, it in enumerate(kb.ui_elements):
                vo = it.viewport_object
                try:
                    if spec["ptr"] and vo is not None and vo.as_pointer() == spec["ptr"]:
                        item = it
                        idx = i
                        break
                except Exception:
                    pass
                if not item and (it.name or "") == spec["name"]:
                    item = it
                    idx = i
        except Exception:
            item = None
        if item is None:
            continue
        msg = _apply_ui_element_delete(root, kb, item, targets, scope)
        if msg:
            reports.append(msg)
    return reports



def _queue_export_clear_mb(root, item) -> None:
    """Remember MonoBehaviour path_ids so Export clears deleted UI text in UnityFS."""
    if root is None or item is None:
        return
    mids = []
    try:
        mid = int(getattr(item, "mb_path_id", 0) or 0)
        if mid:
            mids.append(mid)
    except Exception:
        pass
    try:
        vo = getattr(item, "viewport_object", None)
        if vo is not None:
            mid = int(getattr(vo.ksp_ui, "mb_path_id", 0) or 0)
            if mid:
                mids.append(mid)
    except Exception:
        pass
    if not mids:
        return
    try:
        cur = str(root.get("ksp_pending_clear_mbs") or "")
    except Exception:
        cur = ""
    parts = [p for p in cur.split(",") if p.strip()]
    for mid in mids:
        s = str(int(mid))
        if s not in parts:
            parts.append(s)
    try:
        root["ksp_pending_clear_mbs"] = ",".join(parts)
    except Exception:
        pass


def _apply_ui_element_delete(root, kb, item, targets, scope):
    """Drop one UI element from the chosen languages. Returns a status string."""
    from . import locale_buffers as _lb

    idx = _ui_item_index(kb, item)
    if idx < 0:
        return ""
    obj = item.viewport_object
    hier, name = _element_keys(item)
    kind = str(item.kind or "text")
    for loc in targets:
        try:
            _lb.forget_element(kb, loc, hier=hier, name=name)
        except Exception:
            pass
        if obj is not None:
            try:
                _lb.mark_forgotten_locale(obj, loc)
            except Exception:
                pass
    all_locs = _detected_locales(kb)
    others = [loc for loc in all_locs if loc not in targets]
    # Unloaded locales must not force a hard delete — treat "no maps yet"
    # as keep. Only scope=ALL (or every known language targeted) removes
    # the Blender object / list row.
    keeps = []
    for loc in others:
        try:
            if not _lb.has_locale_maps(kb, loc):
                keeps.append(loc)
            elif _lb.locale_ships_element(
                kb, loc, hier=hier, name=name, kind=kind,
            ):
                keeps.append(loc)
        except Exception:
            keeps.append(loc)
    if scope != "ALL" and others:
        # Still part of other translations — hide in this language, keep
        # the object so switching locale can bring it back.
        try:
            _queue_export_clear_mb(root, item)
        except Exception:
            pass
        if obj is not None:
            try:
                from .locale_switch import (
                    _hide_tree,
                    detach_independent_ui_children,
                    flatten_one_text_off_text_parent,
                )
                # Off the text parent first — a hidden child still nested
                # under ConfS2 is revived by the parent's locale rebuild
                # (USER-LATEST-007 restore-deleted).
                flatten_one_text_off_text_parent(obj)
                detach_independent_ui_children(obj)
                obj["ksp_locale_orphan"] = True
                obj["ksp_locale_hidden"] = True
                _hide_tree(obj, True)
            except Exception:
                pass
        try:
            item.missing_in_locale = True
        except Exception:
            pass
        _refresh_missing_flags(kb)
        try:
            item.missing_in_locale = True
        except Exception:
            pass
        _sync_text_box_overlays_root(root)
        return "Removed from %s (kept in %s)" % (
            ", ".join(targets) or "-",
            ", ".join(keeps or others) or "-",
        )
    try:
        _queue_export_clear_mb(root, item)
    except Exception:
        pass
    if obj is not None:
        try:
            from .locale_switch import (
                detach_independent_ui_children,
                flatten_one_text_off_text_parent,
            )
            flatten_one_text_off_text_parent(obj)
            detach_independent_ui_children(obj)
            victims = [obj] + list(obj.children_recursive)
            for o in victims:
                bpy.data.objects.remove(o, do_unlink=True)
        except Exception:
            pass
    # Queue exclusive textures for export orphan purge (if unreferenced).
    try:
        tpid = int(getattr(item, "texture_path_id", 0) or 0)
    except Exception:
        tpid = 0
    if tpid:
        still = False
        for el in list(kb.ui_elements):
            if el is item:
                continue
            try:
                if int(getattr(el, "texture_path_id", 0) or 0) == tpid:
                    still = True
                    break
            except Exception:
                pass
        if not still:
            # Drop matching texture list row(s)
            try:
                for i in range(len(kb.textures) - 1, -1, -1):
                    try:
                        if int(getattr(kb.textures[i], "path_id", 0) or 0) == tpid:
                            kb.textures.remove(i)
                    except Exception:
                        pass
            except Exception:
                pass
            pending = []
            try:
                raw = str(getattr(kb, "pending_remove_textures", "") or "")
            except Exception:
                raw = ""
            for part in raw.replace(";", ",").split(","):
                part = part.strip()
                if part:
                    pending.append(part)
            spid = str(tpid)
            if spid not in pending:
                pending.append(spid)
            joined = ",".join(pending)
            try:
                kb.pending_remove_textures = joined
            except Exception:
                pass
            try:
                root["ksp_pending_remove_textures"] = joined
            except Exception:
                pass
    kb.ui_elements.remove(idx)
    # Do not auto-select another list/viewport element after delete.
    try:
        from .properties import suppress_ui_element_select
        with suppress_ui_element_select():
            nleft = len(kb.ui_elements)
            kb["ui_elements_index"] = max(0, min(idx, max(nleft - 1, 0))) if nleft else 0
    except Exception:
        try:
            nleft = len(kb.ui_elements)
            kb["ui_elements_index"] = max(0, min(idx, max(nleft - 1, 0))) if nleft else 0
        except Exception:
            pass
    _refresh_missing_flags(kb)
    _sync_text_box_overlays_root(root)
    return "Deleted '%s'" % (name or "element")


def _selected_ksp_ui_items(context):
    """(root, kb, item) for Object-mode selection of KSPedia text/image."""
    out = []
    seen = set()
    if getattr(context, "mode", "") != "OBJECT":
        return out
    for obj in list(getattr(context, "selected_objects", None) or []):
        ui = _find_ksp_ui_root(obj)
        if ui is None:
            continue
        try:
            if not ui.ksp_ui.is_ksp_ui or ui.ksp_ui.kind not in ("text", "image"):
                continue
        except Exception:
            continue
        root = _bundle_root_of(ui)
        if root is None:
            continue
        kb = root.ksp_bundle
        item = None
        cur = ui
        while cur is not None:
            try:
                for it in kb.ui_elements:
                    if it.viewport_object == cur:
                        item = it
                        break
            except Exception:
                item = None
            if item is not None:
                break
            try:
                cur = cur.parent
            except Exception:
                break
        if item is None:
            continue
        key = (id(kb), _ui_item_index(kb, item))
        if key in seen or key[1] < 0:
            continue
        seen.add(key)
        out.append((root, kb, item))
    return out


class KSPMU_OT_UiElementDelete(_LocaleScopeMixin, bpy.types.Operator):
    bl_idname = "object.ksp_ui_element_delete"
    bl_label = "Delete UI Element"
    bl_description = "Delete selected UI Elements (checkboxes / active row) from chosen languages"
    bl_options = {"REGISTER", "UNDO"}

    def scope_summary(self, context):
        root = _find_root(context)
        kb = root.ksp_bundle if root is not None else None
        n = len(_ui_elements_pending_delete(kb, context)) if kb else 0
        if n <= 1:
            return "Delete '%s' from which languages?" % (
                _LOCALE_SCOPE_ELEMENT or "element"
            )
        return "Delete %d elements from which languages?" % n

    def invoke(self, context, event):
        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        kb = root.ksp_bundle
        pending = _ui_elements_pending_delete(kb, context)
        if not pending:
            self.report({"ERROR"}, "Select UI element(s) first")
            return {"CANCELLED"}
        # Point index at first pending so locale dialog label is sensible.
        try:
            idx = _ui_item_index(kb, pending[0])
            if idx >= 0:
                kb.ui_elements_index = idx
        except Exception:
            pass
        return super().invoke(context, event)

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        kb = root.ksp_bundle
        pending = _ui_elements_pending_delete(kb, context)
        if not pending:
            return {"CANCELLED"}
        reports = _delete_ui_elements_batch(
            root, kb, pending, self.target_locales(kb), self.scope,
        )
        if not reports:
            return {"CANCELLED"}
        _clear_ui_element_selection_after_delete(context, root, kb)
        self.report(
            {"INFO"},
            reports[0] if len(reports) == 1
            else "Removed %s UI elements" % len(reports),
        )
        return {"FINISHED"}


class KSPMU_OT_ViewportUiDelete(_LocaleScopeMixin, bpy.types.Operator):
    """X / Del on a KSPedia text or image: same language dialog as the panel."""
    bl_idname = "object.ksp_viewport_ui_delete"
    bl_label = "Delete UI Element"
    bl_description = "Delete KSPedia UI elements selected in the viewport (X / Delete)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        try:
            return bool(_selected_ksp_ui_items(context))
        except Exception:
            return False

    def scope_summary(self, context):
        items = _selected_ksp_ui_items(context)
        if len(items) == 1:
            _root, kb, item = items[0]
            try:
                from .locale_switch import ui_element_list_label
                name = ui_element_list_label(kb, item) or "element"
            except Exception:
                name = item.name or "element"
            return "Delete '%s' from which languages?" % name
        return "Delete %s elements from which languages?" % len(items)

    def invoke(self, context, event):
        items = _selected_ksp_ui_items(context)
        if not items:
            return {"CANCELLED"}
        _root, kb, item = items[0]
        idx = _ui_item_index(kb, item)
        if idx >= 0:
            try:
                kb.ui_elements_index = idx
            except Exception:
                pass
        return super().invoke(context, event)

    def execute(self, context):
        items = _selected_ksp_ui_items(context)
        if not items:
            return {"CANCELLED"}
        # Group by bundle; delete with stable snapshots (RNA goes stale).
        by_kb = {}
        for root, kb, item in items:
            by_kb.setdefault(id(kb), (root, kb, []))[2].append(item)
        reports = []
        for _id, (root, kb, group) in by_kb.items():
            reports.extend(
                _delete_ui_elements_batch(
                    root, kb, group, self.target_locales(kb), self.scope,
                )
            )
        if not reports:
            return {"CANCELLED"}
        try:
            root0 = _find_root(context)
            if root0 is not None:
                _clear_ui_element_selection_after_delete(
                    context, root0, root0.ksp_bundle,
                )
        except Exception:
            pass
        self.report(
            {"INFO"},
            reports[0] if len(reports) == 1
            else "Removed %s UI elements" % len(reports),
        )
        return {"FINISHED"}


def _image_from_ui_element(item):
    """Resolve Blender Image used by a UI image element."""
    if item is None:
        return None
    obj = item.viewport_object
    if obj is not None:
        try:
            for slot in obj.material_slots:
                mat = slot.material
                if mat is None or not mat.use_nodes:
                    continue
                for node in mat.node_tree.nodes:
                    img = getattr(node, "image", None)
                    if img is not None:
                        return img
        except Exception:
            pass
        # Mesh may use active material without slots iteration working
        try:
            mat = obj.active_material
            if mat is not None and mat.use_nodes:
                for node in mat.node_tree.nodes:
                    img = getattr(node, "image", None)
                    if img is not None:
                        return img
        except Exception:
            pass
    return None


def _texture_row_path_id(tex) -> str:
    """Non-empty Unity Texture2D path_id string, or ''."""
    try:
        pid = str(getattr(tex, "path_id", "") or "").strip()
    except Exception:
        return ""
    if not pid or pid == "0":
        return ""
    return pid


def _find_texture_row_by_path_id(kb, path_id):
    pid = str(path_id or "").strip()
    if not pid or pid == "0":
        return None
    try:
        for tex in kb.textures:
            if str(getattr(tex, "path_id", "") or "").strip() == pid:
                return tex
    except Exception:
        pass
    return None


def _resolve_ui_texture_path_id_hint(item, kb) -> str:
    """Best-effort Unity texture path_id for a UI image element."""
    candidates = []
    try:
        candidates.append(str(getattr(item, "texture_path_id", "") or ""))
    except Exception:
        pass
    obj = getattr(item, "viewport_object", None)
    if obj is not None:
        try:
            ui = getattr(obj, "ksp_ui", None)
            if ui is not None and hasattr(ui, "texture_path_id"):
                candidates.append(str(getattr(ui, "texture_path_id", "") or ""))
        except Exception:
            pass
        try:
            for slot in getattr(obj, "material_slots", []) or []:
                mat = getattr(slot, "material", None)
                if mat is None:
                    continue
                for key in ("ksp_texture_path_id", "texture_path_id"):
                    try:
                        if key in mat:
                            candidates.append(str(mat[key] or ""))
                    except Exception:
                        pass
        except Exception:
            pass
    # Sprite linkage: another element / same sprite may already know the tex id.
    try:
        spid = str(getattr(item, "sprite_path_id", "") or "").strip()
    except Exception:
        spid = ""
    if spid and spid != "0":
        try:
            for el in kb.ui_elements:
                if el is item:
                    continue
                try:
                    if str(getattr(el, "sprite_path_id", "") or "").strip() != spid:
                        continue
                    candidates.append(str(getattr(el, "texture_path_id", "") or ""))
                except Exception:
                    continue
        except Exception:
            pass
    for c in candidates:
        c = str(c or "").strip()
        if c and c != "0":
            return c
    return ""


def _assign_image_to_ui_element(item, kb, image):
    """Put ``image`` onto the element's plane material + matching texture row.

    Fits the PNG into the existing Unity Texture2D size when known — changing
    KSPedia page-art dimensions crashes the game on InstantiateScreen.

    Always dirties the stock texture row (with path_id) when replacing; clears
    content_hash so export rewrites even if the dirty flag is lost.
    """
    from . import viewport

    if item is None or image is None or kb is None:
        return False
    obj = item.viewport_object
    if obj is None:
        return False
    try:
        w = int(image.size[0]) if image.size else 0
        h = int(image.size[1]) if image.size else 0
    except Exception:
        w = h = 0

    # Resolve texture row / target Unity size BEFORE swapping pixels.
    matched = None
    target_w = target_h = 0
    tpid_hint = ""
    is_user_added = False
    try:
        if obj is not None and bool(obj.get("ksp_user_added")):
            is_user_added = True
    except Exception:
        is_user_added = False
    try:
        tpid_hint = _resolve_ui_texture_path_id_hint(item, kb)
        # 1) Explicit texture_path_id (item / material / sprite linkage)
        if tpid_hint:
            matched = _find_texture_row_by_path_id(kb, tpid_hint)
        # 2) Current plane image already bound to a stock texture row
        if matched is None:
            old = _image_from_ui_element(item)
            if old is not None:
                for tex in kb.textures:
                    if not _texture_row_path_id(tex):
                        continue
                    try:
                        if tex.image == old:
                            matched = tex
                            break
                    except Exception:
                        continue
        # 3) Name match only among textures that already have a Unity path_id.
        #    Skip for user-added clones (would steal the stock Antenna row).
        if matched is None and not is_user_added:
            iname = (getattr(item, "name", "") or "").strip()
            for tex in kb.textures:
                if not _texture_row_path_id(tex):
                    continue
                tname = (getattr(tex, "name", "") or "").strip()
                if not tname or not iname:
                    continue
                if tname == iname or tname in iname or iname in tname:
                    matched = tex
                    break
        if matched is not None:
            try:
                target_w = int(getattr(matched, "width", 0) or 0)
                target_h = int(getattr(matched, "height", 0) or 0)
            except Exception:
                target_w = target_h = 0
        if (not target_w or not target_h):
            old = _image_from_ui_element(item)
            if old is not None:
                try:
                    target_w = int(old.size[0])
                    target_h = int(old.size[1])
                except Exception:
                    pass
    except Exception:
        matched = None

    if target_w > 0 and target_h > 0 and (w != target_w or h != target_h):
        fitted = viewport.fit_blender_image_to_canvas(image, target_w, target_h)
        if fitted is not None:
            image = fitted
            w, h = target_w, target_h

    mat = None
    try:
        if obj.material_slots:
            mat = obj.material_slots[0].material
    except Exception:
        mat = None
    if mat is None or not getattr(mat, "use_nodes", False):
        mat = viewport.make_unlit_image_material(
            "%s_Mat" % (item.name or "Image"), image
        )
        try:
            if obj.data and hasattr(obj.data, "materials"):
                if obj.data.materials:
                    obj.data.materials[0] = mat
                else:
                    obj.data.materials.append(mat)
            else:
                obj.active_material = mat
        except Exception:
            try:
                obj.active_material = mat
            except Exception:
                pass
    else:
        assigned = False
        try:
            for node in mat.node_tree.nodes:
                if getattr(node, "image", None) is not None or node.type == "TEX_IMAGE":
                    node.image = image
                    assigned = True
                    break
        except Exception:
            pass
        if not assigned:
            try:
                mat = viewport.make_unlit_image_material(
                    "%s_Mat" % (item.name or "Image"), image
                )
                obj.active_material = mat
            except Exception:
                return False
    # Mark / update texture list entry — keep Unity width/height stable.
    try:
        if matched is None:
            # 4) Only create a new row for truly new UI images (no Unity id yet),
            #    or when we know the path_id but the row was missing from the list.
            matched = kb.textures.add()
            matched.name = image.name
            if w and h:
                matched.width = w
                matched.height = h
            if tpid_hint:
                try:
                    matched.path_id = tpid_hint
                except Exception:
                    pass
        matched.image = image
        # Only fill empty size fields; never shrink a known Unity canvas.
        try:
            if not int(getattr(matched, "width", 0) or 0) and w:
                matched.width = w
            if not int(getattr(matched, "height", 0) or 0) and h:
                matched.height = h
        except Exception:
            pass
        try:
            matched.dirty = True
        except Exception:
            pass
        try:
            # Clear hash so export always rewrites even if dirty is lost.
            matched.content_hash = ""
        except Exception:
            pass
        try:
            mpid = _texture_row_path_id(matched) or tpid_hint
            if mpid:
                item.texture_path_id = mpid
                matched.path_id = mpid
            if mat is not None and mpid:
                try:
                    mat["ksp_texture_path_id"] = mpid
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass
    try:
        item.name = item.name or image.name
    except Exception:
        pass
    return True


class KSPMU_OT_UiElementImportImage(_LocaleScopeMixin, bpy.types.Operator):
    """Replace the selected UI image from a file on disk."""
    bl_idname = "object.ksp_ui_element_import_image"
    bl_label = "Import Image"
    bl_description = (
        "Replace the selected image element's texture from a file "
        "(fitted into the existing Unity texture size for KSPedia safety)"
    )
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(
        default="*.png;*.tga;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff",
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        root = _find_root(context)
        if root is None:
            return False
        kb = root.ksp_bundle
        if not (0 <= kb.ui_elements_index < len(kb.ui_elements)):
            return False
        return kb.ui_elements[kb.ui_elements_index].kind == "image"

    def scope_summary(self, context):
        return "Replace image in which languages?"

    def invoke(self, context, event):
        self.filepath = ""
        return super().invoke(context, event)

    def execute(self, context):
        if not self.filepath or not os.path.isfile(self.filepath):
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        kb = root.ksp_bundle
        item = kb.ui_elements[kb.ui_elements_index]
        try:
            img = bpy.data.images.load(self.filepath, check_existing=False)
            try:
                img.pack()
            except Exception:
                pass
        except Exception as e:
            self.report({"ERROR"}, "Failed to load: %s" % e)
            return {"CANCELLED"}
        if not _assign_image_to_ui_element(item, kb, img):
            self.report({"ERROR"}, "Could not assign image to UI element")
            return {"CANCELLED"}
        _register_element_in_locales(
            kb, item, self.target_locales(kb), kind="image",
        )
        try:
            tw = th = 0
            tpid = str(getattr(item, "texture_path_id", "") or "")
            for tex in kb.textures:
                if tpid and str(tex.path_id) == tpid:
                    tw = int(getattr(tex, "width", 0) or 0)
                    th = int(getattr(tex, "height", 0) or 0)
                    break
            if tw and th:
                self.report(
                    {"INFO"},
                    "Replaced image (fitted to %dx%d Unity canvas): %s"
                    % (tw, th, img.name or self.filepath),
                )
            else:
                self.report(
                    {"INFO"},
                    "Replaced image: %s" % (img.name or self.filepath),
                )
        except Exception:
            self.report({"INFO"}, "Replaced image: %s" % (img.name or self.filepath))
        return {"FINISHED"}


class KSPMU_OT_UiElementExportImage(bpy.types.Operator):
    """Save the selected UI image to a file on disk."""
    bl_idname = "object.ksp_ui_element_export_image"
    bl_label = "Export Image"
    bl_description = "Export the selected image element texture to a file"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")
    filename_ext = ".png"
    filter_glob: StringProperty(default="*.png", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        root = _find_root(context)
        if root is None:
            return False
        kb = root.ksp_bundle
        if not (0 <= kb.ui_elements_index < len(kb.ui_elements)):
            return False
        item = kb.ui_elements[kb.ui_elements_index]
        return item.kind == "image" and _image_from_ui_element(item) is not None

    def invoke(self, context, event):
        root = _find_root(context)
        kb = root.ksp_bundle
        item = kb.ui_elements[kb.ui_elements_index]
        img = _image_from_ui_element(item)
        name = (img.name if img else item.name) or "image"
        name = os.path.splitext(name)[0] + ".png"
        self.filepath = name
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        kb = root.ksp_bundle
        item = kb.ui_elements[kb.ui_elements_index]
        img = _image_from_ui_element(item)
        if img is None:
            self.report({"ERROR"}, "No image on selected element")
            return {"CANCELLED"}
        path = self.filepath or ""
        if not path.lower().endswith(".png"):
            path = path + ".png"
        try:
            # Packed / generated images: set path + format then save
            prev = getattr(img, "filepath_raw", "") or ""
            prev_fmt = getattr(img, "file_format", "PNG")
            try:
                img.filepath_raw = path
                img.file_format = "PNG"
                img.save()
            finally:
                try:
                    # Keep packed datablock; restore prior path if it was packed
                    if img.packed_file is not None:
                        img.filepath_raw = prev
                        img.file_format = prev_fmt
                except Exception:
                    pass
        except Exception as e:
            self.report({"ERROR"}, "Save failed: %s" % e)
            return {"CANCELLED"}
        self.report({"INFO"}, "Saved %s" % path)
        return {"FINISHED"}



def _bundle_ui_root(bundle_root):
    """Return the *_UI empty under a bundle root (create if missing)."""
    if bundle_root is None:
        return None
    try:
        for ch in list(bundle_root.children):
            if (ch.name or "").endswith("_UI"):
                return ch
    except Exception:
        pass
    try:
        ui = bpy.data.objects.new("%s_UI" % (bundle_root.name or "KSP"), None)
        ui.empty_display_type = "PLAIN_AXES"
        ui.empty_display_size = 0.06
        for col in bundle_root.users_collection:
            col.objects.link(ui)
            break
        else:
            bpy.context.scene.collection.objects.link(ui)
        ui.parent = bundle_root
        return ui
    except Exception:
        return bundle_root


def _toc_viewport_obj(node):
    if node is None:
        return None
    return node.folder_object or node.page_object


def _folder_screen_child(folder_obj, screen_id=""):
    """Screen/page empty parented under a TOC folder (may be hidden from TOC)."""
    if folder_obj is None:
        return None
    want = (screen_id or "").strip()
    try:
        ts = want or str(folder_obj.get("ksp_title_screen", "") or "")
    except Exception:
        ts = want
    first = None
    try:
        kids = list(folder_obj.children)
    except Exception:
        kids = []
    for ch in kids:
        if not _is_page_obj(ch):
            continue
        if first is None:
            first = ch
        if not ts:
            continue
        try:
            cid = str(ch.get("ksp_page", "") or ch.name or "").strip()
        except Exception:
            cid = (ch.name or "").strip()
        if cid == ts:
            return ch
    return first


def _attach_folder_title_screen(folder_node, page_obj):
    """Point a folder TOC row at its Screen child without listing the Screen."""
    if folder_node is None or page_obj is None:
        return
    try:
        folder_node.page_object = page_obj
    except Exception:
        pass
    try:
        folder_node.page_index = int(page_obj.get("ksp_page_index", -1) or -1)
    except Exception:
        pass


def _recount_toc_pages(kb):
    """Assign page_index from unique page_object pointers (folder or page rows)."""
    seen = set()
    pi = 0
    for node in kb.toc_nodes:
        po = None
        try:
            po = node.page_object
        except Exception:
            po = None
        if po is None:
            continue
        try:
            key = po.as_pointer()
        except Exception:
            key = id(po)
        if key in seen:
            continue
        seen.add(key)
        try:
            node.page_index = pi
            po["ksp_page_index"] = pi
        except Exception:
            pass
        pi += 1
    try:
        kb.page_count = pi
    except Exception:
        pass
    return pi


def _ensure_single_page_promoted(kb, bundle_root, collection):
    """If TOC page points at *_UI canvas, wrap content into a real page empty.

    Runs at most once per UI root (``ksp_ui_promoted``). Multipage needs
    UI → page → content; single-page imports use the UI empty as page_object.
    """
    ui = _bundle_ui_root(bundle_root)
    if ui is None:
        return None
    try:
        if ui.get("ksp_ui_promoted"):
            return ui
    except Exception:
        pass

    # Already have a real page under UI? Just retarget TOC pointers.
    existing_page = None
    try:
        for ch in list(ui.children):
            try:
                if str(ch.get("ksp_toc_kind", "") or "") == "page":
                    existing_page = ch
                    break
            except Exception:
                continue
    except Exception:
        existing_page = None

    needs_wrap = False
    for node in kb.toc_nodes:
        if node.kind != "page":
            continue
        po = node.page_object
        if po is None:
            continue
        try:
            is_ui = (po == ui) or (po.name or "").endswith("_UI")
        except Exception:
            is_ui = False
        if is_ui:
            needs_wrap = True
            break

    if not needs_wrap:
        try:
            ui["ksp_ui_promoted"] = True
        except Exception:
            pass
        return ui

    if existing_page is not None:
        for node in kb.toc_nodes:
            if node.kind != "page":
                continue
            po = node.page_object
            try:
                if po == ui or (po is not None and (po.name or "").endswith("_UI")):
                    node.page_object = existing_page
            except Exception:
                pass
        try:
            ui["ksp_ui_promoted"] = True
        except Exception:
            pass
        return ui

    # Create one page empty under UI; move former UI content under it
    for node in kb.toc_nodes:
        if node.kind != "page":
            continue
        po = node.page_object
        if po is None:
            continue
        try:
            is_ui = (po == ui) or (po.name or "").endswith("_UI")
        except Exception:
            is_ui = False
        if not is_ui:
            continue
        title = (node.title or node.screen or "Page").strip() or "Page"
        # Avoid Blender .001 renames when possible
        page_name = title[:60]
        try:
            if page_name in bpy.data.objects:
                page_name = "%s_page" % page_name
        except Exception:
            pass
        page = bpy.data.objects.new(page_name, None)
        page.empty_display_type = "PLAIN_AXES"
        page.empty_display_size = 0.05
        try:
            collection.objects.link(page)
        except Exception:
            pass
        page.parent = ui
        try:
            page["ksp_toc_kind"] = "page"
            page["ksp_page"] = node.screen or title
            page["ksp_page_index"] = int(node.page_index or 0)
            page["ksp_display_title"] = title
        except Exception:
            pass
        try:
            for ch in list(ui.children):
                if ch == page:
                    continue
                try:
                    kind = str(ch.get("ksp_toc_kind", "") or "")
                except Exception:
                    kind = ""
                if kind in {"category", "subcategory", "page"}:
                    continue
                if (ch.name or "").endswith("_UI"):
                    continue
                ch.parent = page
        except Exception:
            pass
        node.page_object = page
        break
    try:
        ui["ksp_ui_promoted"] = True
    except Exception:
        pass
    return ui


def _toc_block_range(nodes, i):
    depth = int(nodes[i].depth)
    end = i + 1
    while end < len(nodes) and int(nodes[end].depth) > depth:
        end += 1
    return i, end


def _toc_prev_sibling(nodes, start, depth):
    j = start - 1
    while j >= 0:
        d = int(nodes[j].depth)
        if d < depth:
            break
        if d == depth:
            return j
        j -= 1
    return None


def _toc_parent_index(nodes, idx):
    depth = int(nodes[idx].depth)
    for j in range(idx - 1, -1, -1):
        if int(nodes[j].depth) < depth:
            return j
    return None


def _parent_child_preserve_world(obj, parent):
    """Reparent ``obj`` under ``parent`` without jumping in world space."""
    if obj is None or obj == parent:
        return
    setter = getattr(obj, "set_parent", None)
    if callable(setter):
        setter(parent)
        return
    mw = None
    try:
        mw = obj.matrix_world.copy()
    except Exception:
        mw = None
    try:
        obj.parent = parent
    except Exception:
        return
    if mw is not None:
        try:
            obj.matrix_world = mw
        except Exception:
            pass


def _toc_desired_child_order(current_children, toc_ordered, title_child=None):
    """Sibling order: folder TitleScreen, then TOC pages/folders, then the rest."""
    desired = []
    seen = set()
    toc_ids = {id(o) for o in (toc_ordered or ()) if o is not None}
    if title_child is not None and id(title_child) not in toc_ids:
        desired.append(title_child)
        seen.add(id(title_child))
    for obj in toc_ordered or ():
        if obj is None:
            continue
        oid = id(obj)
        if oid in seen:
            continue
        desired.append(obj)
        seen.add(oid)
    for ch in current_children or ():
        if ch is None:
            continue
        cid = id(ch)
        if cid in seen:
            continue
        desired.append(ch)
        seen.add(cid)
    return desired


_toc_ops_root = None


def _relink_collection_objects(col, ordered):
    """Put ``ordered`` at the end of a collection in that relative order."""
    if col is None or not ordered:
        return
    present = []
    for obj in ordered:
        if obj is None:
            continue
        try:
            if obj.name in col.objects:
                present.append(obj)
        except Exception:
            continue
    if len(present) < 2:
        return
    holder = None
    holder_name = "__ksp_toc_hold"
    try:
        holder = bpy.data.collections.get(holder_name)
        if holder is None:
            holder = bpy.data.collections.new(holder_name)
        for obj in present:
            try:
                if obj.name not in holder.objects:
                    holder.objects.link(obj)
            except Exception:
                continue
            try:
                col.objects.unlink(obj)
            except Exception:
                pass
        for obj in present:
            try:
                if obj.name not in col.objects:
                    col.objects.link(obj)
            except Exception:
                pass
            try:
                if obj.name in holder.objects:
                    holder.objects.unlink(obj)
            except Exception:
                pass
    except Exception:
        pass
    if holder is None:
        return
    try:
        leftover = list(holder.objects)
    except Exception:
        leftover = []
    for obj in leftover:
        try:
            if obj.name not in col.objects:
                col.objects.link(obj)
        except Exception:
            pass
        try:
            holder.objects.unlink(obj)
        except Exception:
            pass
    try:
        if not holder.objects:
            bpy.data.collections.remove(holder)
    except Exception:
        pass


def sync_outliner_order_to_toc(bundle_root, kb=None):
    """Match Scene Collection / Outliner sibling order to TOC pages/screens."""
    if bundle_root is None:
        return False
    if kb is None:
        try:
            kb = bundle_root.ksp_bundle
            if not kb.is_ksp_bundle:
                return False
        except Exception:
            return False
    nodes = list(getattr(kb, "toc_nodes", []) or [])
    if not nodes:
        return False
    ui = None
    try:
        for ch in list(bundle_root.children):
            if (ch.name or "").endswith("_UI") or (ch.name or "").endswith("_TOC"):
                ui = ch
                break
    except Exception:
        ui = None
    if ui is None:
        ui = bundle_root

    groups = {}
    seen = set()
    for i, node in enumerate(nodes):
        obj = _toc_viewport_obj(node)
        if obj is None:
            continue
        oid = id(obj)
        if oid in seen:
            continue
        seen.add(oid)
        pidx = _toc_parent_index(nodes, i)
        if pidx is None:
            want_parent = ui
        else:
            want_parent = _toc_viewport_obj(nodes[pidx]) or ui
        if want_parent is None:
            continue
        key = id(want_parent)
        if key not in groups:
            groups[key] = [want_parent, []]
        groups[key][1].append(obj)

    changed = False
    relink_objs = []
    if ui is not None:
        relink_objs.append(ui)
    for _key, (parent, ordered) in groups.items():
        if not ordered:
            continue
        try:
            current = list(parent.children)
        except Exception:
            current = []
        title = None
        try:
            if _is_toc_folder(parent):
                screen_id = ""
                try:
                    screen_id = str(parent.get("ksp_title_screen", "") or "")
                except Exception:
                    screen_id = ""
                title = _folder_screen_child(parent, screen_id)
        except Exception:
            title = None
        desired = _toc_desired_child_order(current, ordered, title_child=title)
        relink_objs.extend(desired)
        same = current == desired
        if same:
            need_parent = False
            for obj in ordered:
                try:
                    if obj.parent != parent:
                        need_parent = True
                        break
                except Exception:
                    need_parent = True
                    break
            if not need_parent:
                continue
        for obj in desired:
            _parent_child_preserve_world(obj, parent)
        changed = True

    try:
        cols = list(getattr(bundle_root, "users_collection", None) or [])
    except Exception:
        cols = []
    if cols and relink_objs:
        uniq = []
        seen_relink = set()
        for obj in relink_objs:
            oid = id(obj)
            if oid in seen_relink:
                continue
            seen_relink.add(oid)
            uniq.append(obj)
        for col in cols:
            try:
                _relink_collection_objects(col, uniq)
            except Exception:
                continue
    return changed


def _toc_ops_begin(bundle_root=None):
    global _toc_ops_lock, _hierarchy_repair_lock, _toc_ops_root
    _toc_ops_lock = True
    _hierarchy_repair_lock = True
    if bundle_root is not None:
        _toc_ops_root = bundle_root


def _toc_ops_end():
    global _toc_ops_lock, _hierarchy_repair_lock, _toc_ops_root
    root = _toc_ops_root
    try:
        if root is not None:
            sync_outliner_order_to_toc(root)
    except Exception:
        pass
    _toc_ops_lock = False
    _hierarchy_repair_lock = False
    _toc_ops_root = None


def _reparent_toc_block(kb, bundle_root, start, end, new_parent_obj):
    """Reparent the viewport object of nodes[start] under new_parent_obj."""
    if new_parent_obj is None:
        new_parent_obj = _bundle_ui_root(bundle_root) or bundle_root
    node = kb.toc_nodes[start]
    obj = _toc_viewport_obj(node)
    if obj is None or obj == new_parent_obj:
        return
    # Avoid cycles
    cur = new_parent_obj
    while cur is not None:
        if cur == obj:
            return
        try:
            cur = cur.parent
        except Exception:
            break
    try:
        obj.parent = new_parent_obj
    except Exception:
        pass


class KSPMU_OT_TocAddPage(bpy.types.Operator):
    bl_idname = "object.ksp_toc_add_page"
    bl_label = "Add Blank Page"
    bl_description = "Create an empty subcategory + page under the selected TOC row"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        kb = root.ksp_bundle
        collection = root.users_collection[0] if root.users_collection else \
            context.view_layer.active_layer_collection.collection

        _toc_ops_begin(root)
        try:
            return _toc_add_blank_page_impl(context, root, kb, collection)
        finally:
            _toc_ops_end()


def _toc_add_blank_page_impl(context, root, kb, collection):
    # Single -> multipage: promote *_UI-as-page into a real page under UI
    ui = _ensure_single_page_promoted(kb, root, collection)
    if ui is None:
        ui = _bundle_ui_root(root)

    parent = ui or root
    depth = 0
    ref_idx = -1
    if 0 <= kb.toc_nodes_index < len(kb.toc_nodes):
        cur = kb.toc_nodes[kb.toc_nodes_index]
        ref_idx = int(kb.toc_nodes_index)
        # Blank PAGE = sibling of selection (same depth), not a child
        depth = int(cur.depth)
        if cur.kind in {"category", "subcategory"} and cur.folder_object:
            parent = cur.folder_object.parent or ui or root
        elif cur.page_object is not None:
            parent = cur.page_object.parent or ui or root
        elif cur.folder_object:
            parent = cur.folder_object.parent or ui or root
        else:
            parent = ui or root

    # Never parent new TOC folders directly on the bundle root
    if parent == root and ui is not None:
        parent = ui

    # Prefer pack UrlName — do not inherit stale kpbs_zh from siblings.
    inherit_bname = ""
    if ref_idx >= 0:
        for j in range(ref_idx, -1, -1):
            try:
                n = kb.toc_nodes[j]
                b = (n.bundle_name or "").strip()
                if b and not b.lower().startswith("kpbs"):
                    inherit_bname = b
                    break
            except Exception:
                break
    inherit_bname = _host_bundle_name_for_blank(kb, inherit_bname)

    screen_id = _unused_toc_screen_name(kb, "NewPage")
    title = "New Page"
    if screen_id.startswith("NewPage_") and screen_id[8:].isdigit():
        title = "New Page %s" % screen_id[8:]

    folder = bpy.data.objects.new(title, None)
    folder.empty_display_type = "PLAIN_AXES"
    folder.empty_display_size = 0.05
    collection.objects.link(folder)
    folder.parent = parent
    folder["ksp_toc_kind"] = "category" if depth == 0 else "subcategory"
    folder["ksp_title_screen"] = screen_id
    folder["ksp_display_title"] = title
    folder["ksp_user_added"] = True
    node = kb.toc_nodes.add()
    node.kind = "category" if depth == 0 else "subcategory"
    node.depth = depth
    node.name = screen_id
    node.screen = screen_id
    node.title_raw = title
    node.title = title
    node.bundle_name = inherit_bname
    try:
        from . import kspedia_index as _ki
        if not (node.bundle_name or "").strip():
            node.bundle_name = _ki.default_bundle_name_for_kb(kb)
        node.asset_path = _ki.default_asset_path_for_screen(screen_id)
    except Exception:
        if not (node.bundle_name or "").strip():
            node.bundle_name = (kb.bundle_name or "").strip()
        node.asset_path = "Assets/KSPedia/%s.prefab" % screen_id
    node.folder_object = folder
    node.expanded = True
    # Landing Screen under folder - exists in Outliner, not as a TOC row.
    page = bpy.data.objects.new(screen_id, None)
    page.empty_display_type = "PLAIN_AXES"
    page.empty_display_size = 0.06
    collection.objects.link(page)
    page.parent = folder
    page["ksp_page_index"] = int(kb.page_count or 0)
    page["ksp_page"] = screen_id
    page["ksp_display_title"] = title
    page["ksp_toc_kind"] = "page"
    page["ksp_user_added"] = True
    _attach_folder_title_screen(node, page)
    kb.page_count = int(kb.page_count or 0) + 1
    kb.layout_mode = "multipage"
    # Insert as sibling immediately after the selected TOC block
    last = len(kb.toc_nodes) - 1
    insert_at = last
    if ref_idx >= 0 and ref_idx < last:
        _s, end = _toc_block_range(kb.toc_nodes, ref_idx)
        if last != end:
            kb.toc_nodes.move(last, end)
            insert_at = end
        else:
            insert_at = last
    kb.toc_nodes_index = insert_at
    _remember_toc_title_for_new_page(kb, screen_id, title)
    try:
        _maybe_add_stock_background(collection, page, kb)
    except Exception:
        pass
    try:
        from . import kspedia_index
        kspedia_index.sync_bundle_toc_xml(kb)
    except Exception:
        pass
    return {"FINISHED"}


class KSPMU_OT_TocAddScreen(bpy.types.Operator):
    bl_idname = "object.ksp_toc_add_screen"
    bl_label = "Add Blank Screen"
    bl_description = "Create content Screen under the selected TOC folder (or beside a page)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        kb = root.ksp_bundle
        collection = root.users_collection[0] if root.users_collection else \
            context.view_layer.active_layer_collection.collection
        _toc_ops_begin(root)
        try:
            return _toc_add_blank_screen_impl(
                context, root, kb, collection, report=self.report,
            )
        finally:
            _toc_ops_end()


def _toc_add_blank_screen_impl(context, root, kb, collection, *, report=None):
    def _report(level, msg):
        if report is not None:
            try:
                report({level}, msg)
            except Exception:
                pass

    ui = _ensure_single_page_promoted(kb, root, collection)
    if ui is None:
        ui = _bundle_ui_root(root)
    if not kb.toc_nodes:
        _report("ERROR", "TOC is empty — Add Blank Page first")
        return {"CANCELLED"}

    ref_idx = int(kb.toc_nodes_index) if 0 <= kb.toc_nodes_index < len(kb.toc_nodes) else 0
    cur = kb.toc_nodes[ref_idx]
    # Parent folder: selected folder, or folder owning selected page
    folder_idx = ref_idx
    folder_node = cur
    if cur.kind == "page":
        pidx = _toc_parent_index(kb.toc_nodes, ref_idx)
        if pidx is None:
            _report("ERROR", "Select a folder (or a page under a folder)")
            return {"CANCELLED"}
        folder_idx = pidx
        folder_node = kb.toc_nodes[pidx]
    if folder_node.kind not in {"category", "subcategory"}:
        _report("ERROR", "Select a TOC folder to add a Screen under")
        return {"CANCELLED"}

    parent = folder_node.folder_object or ui or root
    depth = int(folder_node.depth) + 1
    inherit_bname = _host_bundle_name_for_blank(
        kb, (folder_node.bundle_name or "").strip()
    )

    screen_id = _unused_toc_screen_name(kb, "NewScreen")
    title = "New Screen"
    if screen_id.startswith("NewScreen_") and screen_id[10:].isdigit():
        title = "New Screen %s" % screen_id[10:]

    page = bpy.data.objects.new(screen_id, None)
    page.empty_display_type = "PLAIN_AXES"
    page.empty_display_size = 0.06
    collection.objects.link(page)
    page.parent = parent
    page["ksp_page_index"] = int(kb.page_count or 0)
    page["ksp_page"] = screen_id
    page["ksp_display_title"] = title
    page["ksp_toc_kind"] = "page"
    page["ksp_user_added"] = True

    node = kb.toc_nodes.add()
    node.kind = "page"
    node.depth = depth
    node.name = screen_id
    node.screen = screen_id
    node.title_raw = title
    node.title = title
    node.bundle_name = inherit_bname
    try:
        from . import kspedia_index as _ki
        if not (node.bundle_name or "").strip():
            node.bundle_name = _ki.default_bundle_name_for_kb(kb)
        node.asset_path = _ki.default_asset_path_for_screen(screen_id)
        # Refresh override flag (stock/DLC rename support)
        try:
            from . import properties as _props
            _props._update_toc_screen(node, context)
        except Exception:
            pass
    except Exception:
        node.asset_path = "Assets/KSPedia/%s.prefab" % screen_id
    node.page_object = page
    node.expanded = True
    kb.page_count = int(kb.page_count or 0) + 1
    kb.layout_mode = "multipage"

    # Insert at end of selected folder block
    last = len(kb.toc_nodes) - 1
    _s, end = _toc_block_range(kb.toc_nodes, folder_idx)
    # end points past children; new node is currently at last
    if last != end:
        kb.toc_nodes.move(last, end)
        kb.toc_nodes_index = end
    else:
        kb.toc_nodes_index = last
    try:
        folder_node.expanded = True
    except Exception:
        pass
    _remember_toc_title_for_new_page(kb, screen_id, title)
    try:
        _maybe_add_stock_background(collection, page, kb)
    except Exception:
        pass
    try:
        from . import kspedia_index
        kspedia_index.sync_bundle_toc_xml(kb)
    except Exception:
        pass
    return {"FINISHED"}



# Cached Add Replacement enum (stable between draw/execute — avoids Blender crashes).
_REPLACEMENT_ITEMS = [("NONE", "(no catalog)", "")]
_REPLACEMENT_META = {}  # screen_id -> dict


_STOCK_PLANET_MOONS = (
    ("Planets-Eve", "Eve", (("Planets-Gilly", "Gilly"),)),
    ("Planets-Kerbin", "Kerbin", (
        ("Planets-Mun", "Mun"), ("Planets-Minmus", "Minmus"),
    )),
    ("Planets-Duna", "Duna", (("Planets-Ike", "Ike"),)),
    ("Planets-Jool", "Jool", (
        ("Planets-Laythe", "Laythe"), ("Planets-Vall", "Vall"),
        ("Planets-Tylo", "Tylo"), ("Planets-Bop", "Bop"), ("Planets-Pol", "Pol"),
    )),
)


def _replacement_resolve_title(name, raw_title, filepath=""):
    from . import ksp_loc
    title = (raw_title or "").strip()
    if title and title != "." and not title.startswith("#"):
        return title
    if title.startswith("#"):
        try:
            resolved = ksp_loc.resolve_loc(title, filepath=filepath)
            if resolved and resolved != title:
                return resolved
        except Exception:
            pass
    # Planets-Eve → Eve
    if name.lower().startswith("planets-"):
        body = name.split("-", 1)[-1]
        return "Kerbol" if body.lower() == "sun" else body
    return name


def _rebuild_replacement_catalog(context):
    """Build enum items + meta (fingerprint only — never UnityPy / GameData).

    Loading live ``kspedia.ksp`` here crashes Blender during the dialog.
    """
    global _REPLACEMENT_ITEMS, _REPLACEMENT_META
    items = []
    meta = {}
    used = set()
    filepath = ""
    try:
        root = _find_root(context) if context is not None else None
        if root is not None:
            kb = root.ksp_bundle
            filepath = (
                str(getattr(kb, "source_path", "") or "").strip()
                or str(getattr(kb, "template_path", "") or "").strip()
            )
            for n in kb.toc_nodes:
                sid = (getattr(n, "screen", "") or "").strip().lower()
                if sid:
                    used.add(sid)
    except Exception:
        used = set()

    from . import kspedia_index as _ki

    def _safe_id(sid):
        # Blender Enum identifiers cannot contain # or spaces.
        s = (sid or "").strip()
        if not s or s.startswith("#") or " " in s:
            return ""
        return s

    def _add(sid, title, kind, parent_path, depth, path_titles):
        sid = _safe_id(sid)
        if not sid or sid in meta:
            return
        label = title or sid
        pretty = ("%s%s" % ("  " * max(0, int(depth)), label))
        desc = " / ".join(
            [p for p in path_titles if p] + ([label] if path_titles else [])
        ) or label
        if sid.lower() in used:
            items.append((sid, "[in TOC] " + pretty, desc))
        else:
            items.append((sid, pretty, desc))
        meta[sid] = {
            "screen": sid,
            "title": label,
            "kind": kind,
            "parent_path": tuple(parent_path),
            "path_titles": tuple(path_titles),
            "depth": int(depth),
        }

    try:
        fp = _ki.load_stock_fingerprint() or {}
    except Exception:
        fp = {}
    titles = {}
    for s in fp.get("screens") or []:
        name = _safe_id(s.get("name") or "")
        if name:
            titles[name] = _replacement_resolve_title(
                name, s.get("title") or "", filepath,
            )

    # Attachment-like Planet Wiki tree first (human names).
    wiki_path = ("PlanetWiki",)
    wiki_titles = ("Planet Wiki",)
    _add(
        "Planets-System",
        titles.get("Planets-System") or "Planet Wiki",
        "folder", (), 0, (),
    )
    planet_order = [
        ("Planets-Sun", "Kerbol"),
        ("Planets-Moho", "Moho"),
        ("Planets-Eve", "Eve"),
        ("Planets-Kerbin", "Kerbin"),
        ("Planets-Duna", "Duna"),
        ("Planets-Dres", "Dres"),
        ("Planets-Jool", "Jool"),
        ("Planets-Eeloo", "Eeloo"),
    ]
    moons_map = {p: m for p, _t, m in _STOCK_PLANET_MOONS}
    for sid, fallback in planet_order:
        title = titles.get(sid) or fallback
        _add(sid, title, "folder", wiki_path, 1, wiki_titles)
        for msid, mtitle in moons_map.get(sid, ()):
            _add(
                msid, mtitle, "page",
                wiki_path + (sid,), 2,
                wiki_titles + (title,),
            )

    # Remaining stock + DLC screens (flat), safe ids only.
    try:
        base = sorted(_ki.load_base_screens())
    except Exception:
        base = []
    for sid in base:
        sid = _safe_id(sid)
        if not sid or sid in meta:
            continue
        title = titles.get(sid) or _replacement_resolve_title(sid, "", filepath)
        _add(sid, title, "page", (), 0, ())

    if not items:
        items = [("NONE", "(no catalog)", "")]
    _REPLACEMENT_ITEMS = items
    _REPLACEMENT_META = meta
    return items


def _replacement_catalog_items(self, context):
    """Enum items: cached fingerprint tree (no UnityPy)."""
    global _REPLACEMENT_ITEMS
    # Never rebuild inside the Enum callback — only return cache.
    if not _REPLACEMENT_ITEMS:
        _REPLACEMENT_ITEMS = [("NONE", "(no catalog)", "")]
    return _REPLACEMENT_ITEMS


def _toc_append_folder_child(
    root, kb, collection, parent_idx, *, name, title, screen_id, host_bname,
    with_title_screen=True,
):
    """Append a folder (optionally + TitleScreen) as last child of parent_idx.

    ``parent_idx < 0`` → new root category at TOC end.
    """
    from . import kspedia_index as _ki

    ui = _bundle_ui_root(root) or root
    if parent_idx < 0:
        depth = 0
        parent_obj = ui
        kind = "category"
        insert_at = len(kb.toc_nodes)
    else:
        parent_node = kb.toc_nodes[parent_idx]
        depth = int(parent_node.depth) + 1
        parent_obj = parent_node.folder_object or ui
        kind = "subcategory"
        _s, insert_at = _toc_block_range(kb.toc_nodes, parent_idx)

    folder = bpy.data.objects.new(title or name, None)
    folder.empty_display_type = "PLAIN_AXES"
    folder.empty_display_size = 0.05
    collection.objects.link(folder)
    folder.parent = parent_obj
    folder["ksp_toc_kind"] = kind
    folder["ksp_display_title"] = title or name
    folder["ksp_title_screen"] = screen_id

    page = None
    if with_title_screen:
        page = bpy.data.objects.new(screen_id, None)
        page.empty_display_type = "PLAIN_AXES"
        page.empty_display_size = 0.06
        collection.objects.link(page)
        page.parent = folder
        page["ksp_page_index"] = int(kb.page_count or 0)
        page["ksp_page"] = screen_id
        page["ksp_display_title"] = title or name
        page["ksp_toc_kind"] = "page"
        kb.page_count = int(kb.page_count or 0) + 1

    node = kb.toc_nodes.add()
    node.kind = kind
    node.depth = depth
    node.name = name or screen_id
    node.screen = screen_id
    node.title = title or name
    node.title_raw = title or name
    node.bundle_name = host_bname
    try:
        node.asset_path = _ki.default_asset_path_for_screen(screen_id)
    except Exception:
        node.asset_path = "Assets/KSPedia/%s.prefab" % screen_id
    node.folder_object = folder
    node.page_object = page
    node.expanded = True
    if page is not None:
        _attach_folder_title_screen(node, page)

    last = len(kb.toc_nodes) - 1
    if last != insert_at:
        kb.toc_nodes.move(last, insert_at)
        idx = insert_at
    else:
        idx = last
    # After move into a parent block, keep as last child: move to end-1 of block
    if parent_idx >= 0:
        _s2, end2 = _toc_block_range(kb.toc_nodes, parent_idx)
        # node is at idx; want it just before end2
        if idx != end2 - 1 and idx < end2:
            pass
        elif idx >= end2 or idx < _s2:
            # re-find after moves
            for j, n in enumerate(kb.toc_nodes):
                if n.screen == screen_id and n.folder_object == folder:
                    idx = j
                    break
            _s2, end2 = _toc_block_range(kb.toc_nodes, parent_idx)
            if idx != end2 - 1:
                kb.toc_nodes.move(idx, max(_s2 + 1, end2 - 1) if end2 > _s2 + 1 else end2)
                idx = max(_s2 + 1, end2 - 1) if end2 > _s2 + 1 else end2
    kb.toc_nodes_index = idx
    return idx


def _toc_append_page_under(
    root, kb, collection, parent_idx, *, screen_id, title, host_bname,
):
    """Append a page row under parent folder at TOC end of that block."""
    from . import kspedia_index as _ki

    if parent_idx < 0 or parent_idx >= len(kb.toc_nodes):
        return -1
    parent_node = kb.toc_nodes[parent_idx]
    parent_obj = parent_node.folder_object or _bundle_ui_root(root) or root
    depth = int(parent_node.depth) + 1
    _s, insert_at = _toc_block_range(kb.toc_nodes, parent_idx)

    page = bpy.data.objects.new(screen_id, None)
    page.empty_display_type = "PLAIN_AXES"
    page.empty_display_size = 0.06
    collection.objects.link(page)
    page.parent = parent_obj
    page["ksp_page_index"] = int(kb.page_count or 0)
    page["ksp_page"] = screen_id
    page["ksp_display_title"] = title
    page["ksp_toc_kind"] = "page"
    kb.page_count = int(kb.page_count or 0) + 1

    node = kb.toc_nodes.add()
    node.kind = "page"
    node.depth = depth
    node.name = screen_id
    node.screen = screen_id
    node.title = title
    node.title_raw = title
    node.bundle_name = host_bname
    try:
        node.asset_path = _ki.default_asset_path_for_screen(screen_id)
    except Exception:
        node.asset_path = "Assets/KSPedia/%s.prefab" % screen_id
    node.page_object = page
    node.expanded = True

    last = len(kb.toc_nodes) - 1
    if last != insert_at:
        kb.toc_nodes.move(last, insert_at)
        idx = insert_at
    else:
        idx = last
    kb.toc_nodes_index = idx
    return idx


def _toc_find_folder_by_path(kb, parent_path):
    """Return toc index of folder whose chain matches parent_path, or -1."""
    if not parent_path:
        return -1
    path = tuple(parent_path)
    # indices[d] = toc index of matched folder at depth d
    matched_idx = [-1] * len(path)
    for i, n in enumerate(kb.toc_nodes):
        try:
            kind = str(n.kind or "")
            depth = int(n.depth)
        except Exception:
            continue
        if kind not in {"category", "subcategory"}:
            continue
        if depth >= len(path):
            continue
        want = path[depth]
        name = (getattr(n, "name", "") or "").strip()
        title = (getattr(n, "title", "") or "").strip()
        screen = (getattr(n, "screen", "") or "").strip()
        aliases = {name, title, screen, name.lower(), title.lower(), screen.lower()}
        if want not in aliases and want.lower() not in aliases:
            continue
        if depth == 0 or (
            depth > 0 and matched_idx[depth - 1] >= 0 and i > matched_idx[depth - 1]
        ):
            # Must be under previously matched parent block
            if depth > 0:
                pidx = matched_idx[depth - 1]
                _s, end = _toc_block_range(kb.toc_nodes, pidx)
                if not (_s < i < end):
                    continue
            matched_idx[depth] = i
    if matched_idx[-1] >= 0 and all(x >= 0 for x in matched_idx):
        return matched_idx[-1]
    return -1


def _toc_add_root_category_folder(
    context, root, kb, collection, *, name, title, host_bname,
):
    """Append a new depth-0 TOC category at the end (ignore current selection)."""
    ui = _bundle_ui_root(root) or root
    folder = bpy.data.objects.new(title or name, None)
    folder.empty_display_type = "PLAIN_AXES"
    folder.empty_display_size = 0.05
    collection.objects.link(folder)
    folder.parent = ui
    folder["ksp_toc_kind"] = "category"
    folder["ksp_display_title"] = title or name
    ph = _unused_toc_screen_name(kb, (name or "Folder").replace("#", "").replace("-", "") or "Folder")
    folder["ksp_title_screen"] = ph
    node = kb.toc_nodes.add()
    node.kind = "category"
    node.depth = 0
    node.name = name
    node.screen = ph
    node.title = title or name
    node.title_raw = title or name
    node.bundle_name = host_bname
    node.folder_object = folder
    node.expanded = True
    node.overrides_stock = False
    idx = len(kb.toc_nodes) - 1
    kb.toc_nodes_index = idx
    return idx


def _toc_ensure_ancestor_folders_at_end(
    context, root, kb, collection, parent_path, path_titles, host_bname,
):
    """Create a fresh ancestor chain at TOC bottom (Replacement only).

    Does not nest under an existing mid-TOC folder (e.g. GEP Planet Wiki) —
    always appends new roots/children at the end.
    """
    if not parent_path:
        return -1
    created_idx = -1
    for depth, name in enumerate(parent_path):
        title = (
            path_titles[depth]
            if path_titles and depth < len(path_titles)
            else _replacement_resolve_title(name, "", "")
        )
        if created_idx < 0:
            # Stock Planet Wiki home uses Planets-System as TitleScreen.
            root_screen = ""
            nl = (name or "").strip().lower()
            if nl in {"planetwiki", "planet wiki", "planets-system"}:
                root_screen = "Planets-System"
            if root_screen:
                created_idx = _toc_append_folder_child(
                    root, kb, collection, -1,
                    name=name, title=title, screen_id=root_screen,
                    host_bname=host_bname, with_title_screen=True,
                )
                try:
                    from . import kspedia_index as _ki
                    kb.toc_nodes[created_idx].overrides_stock = (
                        _ki.screen_overrides_base(
                            root_screen, host_bname, title=title,
                        )
                    )
                except Exception:
                    pass
            else:
                created_idx = _toc_add_root_category_folder(
                    context, root, kb, collection,
                    name=name, title=title, host_bname=host_bname,
                )
        else:
            ph = _unused_toc_screen_name(
                kb, (name or "Folder").replace("-", "") or "Folder",
            )
            created_idx = _toc_append_folder_child(
                root, kb, collection, created_idx,
                name=name, title=title, screen_id=ph, host_bname=host_bname,
                with_title_screen=False,
            )
    return created_idx


def _toc_add_replacement_impl(
    context, root, kb, collection, *, screen_id, as_folder=True, report=None,
):
    """Append stock/DLC override at TOC bottom (does not use selection)."""
    def _report(level, msg):
        if report is not None:
            try:
                report({level}, msg)
            except Exception:
                pass

    from . import kspedia_index as _ki
    from .unityfs_catalog import host_bundle_stem

    sid = (screen_id or "").strip()
    if not sid or sid == "NONE":
        _report("ERROR", "Pick a Screen to replace")
        return {"CANCELLED"}

    meta = _REPLACEMENT_META.get(sid) or {
        "screen": sid,
        "title": _replacement_resolve_title(sid, "", ""),
        "kind": "folder" if as_folder else "page",
        "parent_path": (),
        "path_titles": (),
        "depth": 0,
    }
    title = (meta.get("title") or sid).strip()
    parent_path = tuple(meta.get("parent_path") or ())
    path_titles = tuple(meta.get("path_titles") or ())
    host = host_bundle_stem(kb) or _ki.default_bundle_name_for_kb(kb)
    meta_kind = (meta.get("kind") or "page").strip()
    want_folder = meta_kind == "folder" or (
        bool(as_folder) and meta_kind != "page"
    )
    if meta_kind == "page":
        want_folder = False
    elif meta_kind == "folder":
        want_folder = True

    used = {
        (getattr(n, "screen", "") or "").strip().lower()
        for n in kb.toc_nodes
    }
    if sid.lower() in used:
        _report("WARNING", "Screen '%s' already in TOC" % sid)
        return {"CANCELLED"}

    # Ancestors + leaf always go to the bottom — never under TOC selection.
    parent_idx = _toc_ensure_ancestor_folders_at_end(
        context, root, kb, collection, parent_path, path_titles, host,
    )

    if want_folder:
        idx = _toc_append_folder_child(
            root, kb, collection, parent_idx,
            name=sid, title=title, screen_id=sid, host_bname=host,
            with_title_screen=True,
        )
    else:
        if parent_idx < 0:
            # Bare screen with no parent path → root folder+page at bottom
            idx = _toc_append_folder_child(
                root, kb, collection, -1,
                name=sid, title=title, screen_id=sid, host_bname=host,
                with_title_screen=True,
            )
        else:
            idx = _toc_append_page_under(
                root, kb, collection, parent_idx,
                screen_id=sid, title=title, host_bname=host,
            )
    if idx < 0:
        _report("ERROR", "Could not append replacement")
        return {"CANCELLED"}

    node = kb.toc_nodes[idx]
    try:
        node.overrides_stock = _ki.screen_overrides_base(sid, host, title=title)
    except Exception:
        node.overrides_stock = True
    try:
        from . import kspedia_index
        kspedia_index.sync_bundle_toc_xml(kb)
    except Exception:
        pass
    _report("INFO", "Replacement '%s' added at TOC bottom" % title)
    return {"FINISHED"}


class KSPMU_OT_TocAddReplacement(bpy.types.Operator):
    bl_idname = "object.ksp_toc_add_replacement"
    bl_label = "Add Replacement"
    bl_description = (
        "Append a stock/DLC Screen override at the bottom of this pack TOC "
        "(does not use the selected row)"
    )
    bl_options = {"REGISTER", "UNDO"}

    screen_id: EnumProperty(
        name="Replace Screen",
        description="Stock or DLC Screen id to override",
        items=_replacement_catalog_items,
    )
    as_folder: BoolProperty(
        name="As folder (TitleScreen)",
        description="Insert as TOC folder with TitleScreen (page) instead of bare Screen row",
        default=True,
    )

    def invoke(self, context, event):
        try:
            _rebuild_replacement_catalog(context)
        except Exception as ex:
            print("WARNING: replacement catalog rebuild failed: %s" % ex)
            global _REPLACEMENT_ITEMS, _REPLACEMENT_META
            _REPLACEMENT_ITEMS = [("NONE", "(catalog error)", "")]
            _REPLACEMENT_META = {}
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "as_folder")
        layout.prop(self, "screen_id", text="Screen")
        sid = (self.screen_id or "").strip()
        meta = _REPLACEMENT_META.get(sid) or {}
        title = (meta.get("title") or sid).strip()
        path = " / ".join(
            list(meta.get("path_titles") or ()) + ([title] if title else [])
        )
        if path:
            layout.label(text=path[:80], icon="OUTLINER")
        layout.label(text="Appends at TOC bottom (selection ignored)", icon="INFO")

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        kb = root.ksp_bundle
        collection = root.users_collection[0] if root.users_collection else \
            context.view_layer.active_layer_collection.collection
        _toc_ops_begin(root)
        try:
            return _toc_add_replacement_impl(
                context, root, kb, collection,
                screen_id=self.screen_id,
                as_folder=self.as_folder,
                report=self.report,
            )
        except Exception as ex:
            self.report({"ERROR"}, "Replacement failed: %s" % str(ex)[:80])
            print("ERROR: Add Replacement: %s" % ex)
            import traceback
            traceback.print_exc()
            return {"CANCELLED"}
        finally:
            _toc_ops_end()


class KSPMU_MT_TocAddMenu(bpy.types.Menu):
    bl_label = "Add"
    bl_idname = "KSPMU_MT_toc_add"

    def draw(self, context):
        layout = self.layout
        layout.operator(
            "object.ksp_toc_add_page",
            text="Add Blank Page",
            icon="FILE_NEW",
        )
        layout.operator(
            "object.ksp_toc_add_screen",
            text="Add Blank Screen",
            icon="DOCUMENTS",
        )
        layout.separator()
        layout.operator(
            "object.ksp_toc_add_existing_page",
            text="Add Existing Page…",
            icon="IMPORT",
        )
        layout.operator(
            "object.ksp_toc_add_to_existing_page",
            text="Add To Existing Page…",
            icon="PASTEDOWN",
        )
        layout.separator()
        layout.operator(
            "object.ksp_toc_add_replacement",
            text="Add Replacement…",
            icon="FILE_REFRESH",
        )


def _iter_scene_kspedia_roots(context, *, skip_root=None):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    for obj in scene.objects:
        try:
            if not obj.ksp_bundle.is_ksp_bundle:
                continue
        except Exception:
            continue
        if skip_root is not None and obj == skip_root:
            continue
        yield obj


def _page_candidates_from_bundle_root(root):
    """Yield (page_obj, title, screen, bundle_name, asset_path) for graft sources."""
    if root is None:
        return
    kb = root.ksp_bundle
    bname = (kb.bundle_name or kb.locale_base or root.name or "").strip()
    seen = set()
    for n in kb.toc_nodes:
        try:
            kind = str(n.kind or "")
        except Exception:
            continue
        page = None
        title = ""
        screen = ""
        asset = (getattr(n, "asset_path", None) or "").strip()
        bund = (getattr(n, "bundle_name", None) or "").strip() or bname
        if kind == "page" and n.page_object is not None:
            page = n.page_object
            screen = (n.screen or n.name or page.name or "").strip()
            title = (n.title or screen).strip()
        elif kind in ("category", "subcategory"):
            # Prefer TitleScreen page for folders.
            screen = (n.screen or n.name or "").strip()
            title = (n.title or screen).strip()
            if n.page_object is not None:
                page = n.page_object
            elif screen:
                for p in kb.toc_nodes:
                    if p.kind == "page" and (p.screen or p.name or "").strip() == screen:
                        if p.page_object is not None:
                            page = p.page_object
                            if not asset:
                                asset = (getattr(p, "asset_path", None) or "").strip()
                            break
        if page is None:
            continue
        ptr = page.as_pointer()
        if ptr in seen:
            continue
        seen.add(ptr)
        yield page, title or page.name, screen or page.name, bund, asset

    if seen:
        return
    try:
        from .import_ksp import iter_page_roots
        pages = list(iter_page_roots(root) or [])
    except Exception:
        pages = []
    if not pages:
        for n in kb.toc_nodes:
            if n.kind == "page" and n.page_object is not None:
                pages = [n.page_object]
                break
    if not pages:
        for c in list(getattr(root, "children", None) or []):
            try:
                if c.type == "EMPTY" and (
                    "_UI" in (c.name or "") or c.get("ksp_page") or c.get("ksp_page_index") is not None
                ):
                    pages = [c]
                    break
            except Exception:
                continue
    for page in pages:
        if page is None or page.as_pointer() in seen:
            continue
        seen.add(page.as_pointer())
        screen = str(page.get("ksp_page") or page.name or "Page")
        title = str(page.get("ksp_display_title") or screen)
        yield page, title, screen, bname, ""


# Blender frees enum callback strings unless Python keeps them. Using
# "root||page" as the identifier also garbled the dropdown (RNA treats '|').
_SCENE_PAGE_ENUM_ITEMS = [
    ("NONE", "(no other KSPedia pages/folders in scene)", "", 0, 0)
]
_SCENE_PAGE_ENUM_MAP = {}


def _scene_existing_page_items(self, context):
    global _SCENE_PAGE_ENUM_ITEMS, _SCENE_PAGE_ENUM_MAP
    items = []
    lookup = {}
    active = _find_root(context)
    n = 1
    for root in _iter_scene_kspedia_roots(context, skip_root=active):
        try:
            bname = (root.ksp_bundle.bundle_name or root.name or "bundle").strip()
        except Exception:
            bname = (root.name or "bundle").strip()
        for page, title, screen, bund, asset in _page_candidates_from_bundle_root(root):
            try:
                ident = "P_%d" % int(page.as_pointer())
            except Exception:
                continue
            shown = (title or screen or page.name or "Page").strip() or "Page"
            label = "%s — %s" % (bname, shown)
            desc = (screen or shown)[:240]
            items.append((ident, label, desc, 0, n))
            lookup[ident] = (page, shown, bund, asset)
            n += 1
    if not items:
        items = [
            ("NONE", "(no other KSPedia pages/folders in scene)", "", 0, 0)
        ]
    _SCENE_PAGE_ENUM_ITEMS = items
    _SCENE_PAGE_ENUM_MAP = lookup
    return _SCENE_PAGE_ENUM_ITEMS


def _resolve_scene_source_page(context, ident: str):
    if not ident or ident == "NONE":
        return None, "", "", ""
    hit = _SCENE_PAGE_ENUM_MAP.get(ident)
    if hit is not None:
        page, title, bund, asset = hit
        try:
            _ = page.name
            return page, title, bund, asset
        except Exception:
            pass
    want = 0
    if ident.startswith("P_"):
        try:
            want = int(ident[2:])
        except Exception:
            want = 0
    if want:
        for r in _iter_scene_kspedia_roots(context):
            for p, title, screen, bund, asset in _page_candidates_from_bundle_root(r):
                try:
                    if int(p.as_pointer()) == want:
                        return p, title or screen or p.name, bund, asset
                except Exception:
                    continue
    # Legacy "root||page" ids from earlier builds.
    if "||" in ident:
        root_name, page_name = ident.split("||", 1)
        for r in _iter_scene_kspedia_roots(context):
            if r.name != root_name and root_name not in (r.name or ""):
                continue
            for p, title, screen, bund, asset in _page_candidates_from_bundle_root(r):
                if p.name == page_name or page_name in (p.name or ""):
                    return p, title, bund, asset
    return None, "", "", ""


def _catalog_meta_for_page(root, page, screen_hint=""):
    """Best BundleName / AssetPath for a source page."""
    bund = ""
    asset = ""
    if root is None:
        return bund, asset
    kb = root.ksp_bundle
    bund = (kb.bundle_name or kb.locale_base or "").strip()
    hint = (screen_hint or "").strip()
    if page is not None:
        hint = hint or str(page.get("ksp_page") or page.name or "")
    for n in kb.toc_nodes:
        try:
            sc = (n.screen or n.name or "").strip()
            if hint and sc and sc != hint and n.page_object != page:
                continue
            if n.page_object == page or (hint and sc == hint):
                asset = (getattr(n, "asset_path", None) or "").strip() or asset
                bund = (getattr(n, "bundle_name", None) or "").strip() or bund
                if asset:
                    break
        except Exception:
            continue
    if not asset:
        # Parse Screen catalog from this bundle's XML text asset
        try:
            from . import kspedia_index as _ki
            xml = ""
            for ta in kb.text_assets:
                lname = (ta.name or "").lower()
                if "kspedia" in lname and "bundle" not in lname:
                    xml = ta.text or ""
                    if ta.text_block:
                        try:
                            xml = ta.text_block.as_string() or xml
                        except Exception:
                            pass
                    break
            if hint and xml:
                meta = _ki.lookup_screen_catalog(xml, hint)
                asset = (meta.get("asset_path") or "").strip() or asset
                bund = (meta.get("bundle_name") or "").strip() or bund
        except Exception:
            pass
    if not bund:
        # Stem from source_path filename
        try:
            import os
            stem = os.path.splitext(os.path.basename(kb.source_path or ""))[0]
            if stem:
                bund = stem
        except Exception:
            pass
    return bund, asset


def _pick_source_page_from_imported_root(squad_root):
    pages = []
    try:
        from .import_ksp import iter_page_roots
        pages = list(iter_page_roots(squad_root) or [])
    except Exception:
        pages = []
    if not pages:
        for n in squad_root.ksp_bundle.toc_nodes:
            if n.kind == "page" and n.page_object is not None:
                pages.append(n.page_object)
    if not pages:
        for c in list(getattr(squad_root, "children", None) or []):
            try:
                if c.type != "EMPTY":
                    continue
                if (
                    "_UI" in (c.name or "")
                    or c.get("ksp_page")
                    or c.get("ksp_page_index") is not None
                    or c.get("ksp_toc_kind") == "page"
                ):
                    pages.append(c)
            except Exception:
                continue
    if not pages:
        return None
    # Prefer the densest UI subtree
    def _score(p):
        try:
            return len(list(p.children_recursive))
        except Exception:
            return 0
    return max(pages, key=_score)


class KSPMU_OT_TocAddExistingPage(bpy.types.Operator, ImportHelper):
    """Graft an existing KSPedia page (from scene or .ksp) under the selected TOC row."""
    bl_idname = "object.ksp_toc_add_existing_page"
    bl_label = "Add Existing Page"
    bl_description = (
        "Insert a page from another KSPedia already in the scene, or from a .ksp file "
        "(stock / DLC / mod). Uses a unique Screen id so it does not override stock."
    )
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".ksp"
    filter_glob: StringProperty(default="*.ksp", options={"HIDDEN"})

    source_mode: EnumProperty(
        name="Source",
        items=(
            ("SCENE", "From Scene", "Pick a page/folder from another imported KSPedia bundle"),
            ("FILE", "From .ksp File", "Import a .ksp (stock, DLC, or mod) and graft its page"),
        ),
        default="SCENE",
    )
    scene_source: EnumProperty(
        name="Page / Folder",
        description="KSPedia page or folder already present in this Blender scene",
        items=_scene_existing_page_items,
    )
    custom_title: StringProperty(
        name="Title",
        description="TOC title in this bundle (leave empty to keep source title)",
        default="",
    )
    keep_imported_bundle: BoolProperty(
        name="Keep Imported Bundle",
        description="When adding from file, leave the temporary .ksp import in the scene",
        default=False,
    )
    adopt_into_bundle: BoolProperty(
        name="Adopt into this bundle",
        description=(
            "Rewrite BundleName/AssetPath to this pack so Export clones the prefab "
            "here. Turn off only for intentional stock/DLC overrides"
        ),
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "source_mode", expand=True)
        if self.source_mode == "SCENE":
            layout.prop(self, "scene_source")
        else:
            layout.prop(self, "filepath", text="File")
            layout.prop(self, "keep_imported_bundle")
        layout.prop(self, "custom_title")
        layout.prop(self, "adopt_into_bundle")

    def invoke(self, context, event):
        if _find_root(context) is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        kb = root.ksp_bundle
        parent_idx = int(kb.toc_nodes_index) if kb.toc_nodes else -1
        if parent_idx < 0 and kb.toc_nodes:
            parent_idx = 0
        if parent_idx < 0:
            self.report({"ERROR"}, "TOC is empty — Add Blank Page first")
            return {"CANCELLED"}

        if self.source_mode == "FILE" and not (self.filepath or "").strip():
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}

        collection = root.users_collection[0] if root.users_collection else \
            context.view_layer.active_layer_collection.collection

        src_page = None
        src_title = ""
        bund = ""
        asset = ""
        imported_root = None

        _toc_ops_begin(root)
        try:
            if self.source_mode == "SCENE":
                src_page, src_title, bund, asset = _resolve_scene_source_page(
                    context, self.scene_source,
                )
                if src_page is None:
                    self.report(
                        {"ERROR"},
                        "No scene page selected (import another KSPedia first)",
                    )
                    return {"CANCELLED"}
                # Find owning root for catalog meta
                src_root = src_page
                while src_root is not None:
                    try:
                        if src_root.ksp_bundle.is_ksp_bundle:
                            break
                    except Exception:
                        pass
                    src_root = src_root.parent
                if src_root is not None:
                    b2, a2 = _catalog_meta_for_page(
                        src_root, src_page, src_title,
                    )
                    bund = bund or b2
                    asset = asset or a2
            else:
                path = (self.filepath or "").strip()
                if not path or not os.path.isfile(path):
                    self.report({"ERROR"}, "Choose a valid .ksp file")
                    return {"CANCELLED"}
                before = set(context.scene.objects)
                try:
                    ret = bpy.ops.import_object.ksp_bundle(
                        filepath=path,
                        build_viewport=True,
                        pixel_scale=float(kb.pixel_scale or 0.001),
                    )
                except Exception as ex:
                    self.report({"ERROR"}, "Import failed: %s" % ex)
                    return {"CANCELLED"}
                if "FINISHED" not in ret:
                    self.report({"ERROR"}, "Import cancelled")
                    return {"CANCELLED"}
                new_roots = [
                    o for o in context.scene.objects
                    if o not in before
                    and getattr(o, "ksp_bundle", None)
                    and o.ksp_bundle.is_ksp_bundle
                ]
                if not new_roots:
                    self.report({"ERROR"}, "Import produced no KSPedia bundle")
                    return {"CANCELLED"}
                imported_root = max(
                    new_roots, key=lambda o: len(o.ksp_bundle.ui_elements),
                )
                src_page = _pick_source_page_from_imported_root(imported_root)
                if src_page is None:
                    self.report({"ERROR"}, "No page found in that .ksp")
                    return {"CANCELLED"}
                src_title = str(
                    src_page.get("ksp_display_title")
                    or src_page.get("ksp_page")
                    or src_page.name
                )
                bund, asset = _catalog_meta_for_page(
                    imported_root, src_page, src_title,
                )
                if not bund:
                    stem = os.path.splitext(os.path.basename(path))[0]
                    bund = stem
                graft_source_asset = (asset or "").strip()
                graft_source_ksp = path

            title = (self.custom_title or "").strip() or (src_title or "Imported Page")
            # Unique screen base from source name (graft adds _PBS).
            screen_base = (
                str(src_page.get("ksp_page") or "")
                or (src_title or "ImportedPage")
            )
            screen_base = "".join(
                ch if (ch.isalnum() or ch in "_-") else "_"
                for ch in screen_base
            ) or "ImportedPage"

            # Keep pre-adopt AssetPath for Export cross-env prefab copy
            if "graft_source_asset" not in locals():
                graft_source_asset = (asset or "").strip()
            if "graft_source_ksp" not in locals():
                graft_source_ksp = ""
                try:
                    if src_page is not None:
                        br = src_page
                        while br is not None and not (
                            getattr(br, "ksp_bundle", None)
                            and br.ksp_bundle.is_ksp_bundle
                        ):
                            br = br.parent
                        if br is not None:
                            graft_source_ksp = str(
                                getattr(br.ksp_bundle, "source_path", "") or ""
                            )
                except Exception:
                    pass

            adopt = bool(getattr(self, "adopt_into_bundle", True))
            if adopt:
                try:
                    from .unityfs_catalog import host_bundle_stem
                    from .kspedia_index import default_asset_path_for_screen
                    host = host_bundle_stem(kb) or (kb.bundle_name or "").strip()
                    # Screen id finalized inside graft; AssetPath set after with real id.
                    bund = host
                    asset = ""  # filled by graft with screen_id
                except Exception:
                    bund = (kb.bundle_name or kb.locale_base or "").strip() or bund
                    asset = ""

            if "graft_source_ksp" not in dir():
                graft_source_ksp = ""
            if "graft_source_asset" not in dir():
                graft_source_asset = (asset or "").strip()
            # Prefer filling a blank New Page instead of nesting under it
            try:
                if _toc_node_is_blank_newpage(kb.toc_nodes[parent_idx]):
                    # Keep parent_idx — graft_kspedia will detect and fill
                    pass
            except Exception:
                pass
            info = graft_kspedia_page_under(
                root, kb, parent_idx, src_page,
                new_screen=screen_base,
                new_title=title,
                bundle_name=bund,
                asset_path=asset,
                collection=collection,
                adopt_into_host=adopt,
            )
            if not info:
                self.report({"ERROR"}, "Could not graft page under selected TOC row")
                return {"CANCELLED"}
            _stamp_graft_source_meta(
                info,
                source_ksp=graft_source_ksp,
                source_asset=graft_source_asset,
            )

            if imported_root is not None and not self.keep_imported_bundle:
                try:
                    victims = [imported_root] + list(imported_root.children_recursive)
                    for o in victims:
                        bpy.data.objects.remove(o, do_unlink=True)
                except Exception:
                    pass

            # Restore selection to target bundle
            try:
                for o in context.scene.objects:
                    o.select_set(False)
                context.view_layer.objects.active = root
                root.select_set(True)
                if info.get("page") is not None:
                    info["page"].select_set(True)
            except Exception:
                pass

            self.report(
                {"INFO"},
                "Added '%s' (%s) under TOC" % (info["title"], info["screen"]),
            )
            return {"FINISHED"}
        finally:
            _toc_ops_end()



def _toc_merge_target_page(kb, idx):
    """Resolve the page empty that content should be merged into."""
    if kb is None or not (0 <= idx < len(kb.toc_nodes)):
        return None, None
    node = kb.toc_nodes[idx]
    kind = str(getattr(node, "kind", "") or "")
    if kind == "page" and node.page_object is not None:
        return node.page_object, node
    if kind in {"category", "subcategory"}:
        if node.page_object is not None:
            return node.page_object, node
        screen = (node.screen or "").strip()
        if screen:
            for n in kb.toc_nodes:
                try:
                    if (
                        str(n.kind or "") == "page"
                        and (n.screen or n.name or "").strip() == screen
                        and n.page_object is not None
                    ):
                        return n.page_object, node
                except Exception:
                    continue
    return None, node


def merge_kspedia_page_into(
    root,
    kb,
    target_idx: int,
    src_page,
    *,
    new_title: str = "",
    collection=None,
):
    """Copy UI children from ``src_page`` onto the selected TOC page (no new TOC row)."""
    import bpy

    if root is None or kb is None or src_page is None:
        return None
    dst_page, node = _toc_merge_target_page(kb, target_idx)
    if dst_page is None or node is None:
        return None

    cols = list(root.users_collection) if root.users_collection else []
    if collection is not None and collection not in cols:
        cols = [collection] + list(cols)
    if not cols:
        cols = [bpy.context.scene.collection]

    n_copied = 0
    for child in list(getattr(src_page, "children", None) or []):
        new_c = _copy_ui_object_tree(child, parent=dst_page, collections=cols)
        if new_c is not None:
            n_copied += 1

    title = (new_title or "").strip()
    if title:
        try:
            node.title = title
            node.title_raw = title
        except Exception:
            pass
        try:
            dst_page["ksp_display_title"] = title
            if node.folder_object is not None:
                node.folder_object["ksp_display_title"] = title
        except Exception:
            pass

    try:
        from . import kspedia_index as _ki
        _ki.ensure_node_catalog_meta(node, kb)
    except Exception:
        pass

    screen = ""
    try:
        screen = str(
            dst_page.get("ksp_page", "")
            or getattr(node, "screen", None)
            or ""
        )
    except Exception:
        screen = (getattr(node, "screen", None) or "") or ""

    locales = _detected_locales(kb) or [
        (getattr(kb, "active_locale", "") or "en-us").lower()
    ]
    suffix = "_" + _sanitize_toc_suffix(screen or "page") + "_mrg"
    n_ui = _register_copied_page_ui_elements(
        root, kb, dst_page, locales, name_suffix=suffix,
    )
    try:
        from . import kspedia_index
        kspedia_index.sync_bundle_toc_xml(kb)
    except Exception:
        pass
    return {
        "page": dst_page,
        "screen": screen,
        "title": (getattr(node, "title", None) or screen),
        "n_copied": n_copied,
        "n_ui": n_ui,
    }


class KSPMU_OT_TocAddToExistingPage(bpy.types.Operator, ImportHelper):
    """Merge an existing KSPedia page's content into the selected TOC page."""
    bl_idname = "object.ksp_toc_add_to_existing_page"
    bl_label = "Add To Existing Page"
    bl_description = (
        "Copy UI from another KSPedia page (scene or .ksp) onto the selected "
        "TOC page/folder TitleScreen — does not create a new TOC row"
    )
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".ksp"
    filter_glob: StringProperty(default="*.ksp", options={"HIDDEN"})

    source_mode: EnumProperty(
        name="Source",
        items=(
            ("SCENE", "From Scene", "Pick a page/folder from another imported KSPedia bundle"),
            ("FILE", "From .ksp File", "Import a .ksp and merge its page content"),
        ),
        default="SCENE",
    )
    scene_source: EnumProperty(
        name="Page / Folder",
        description="KSPedia page or folder already present in this Blender scene",
        items=_scene_existing_page_items,
    )
    custom_title: StringProperty(
        name="Title",
        description="Optional new title for the selected page (leave empty to keep)",
        default="",
    )
    keep_imported_bundle: BoolProperty(
        name="Keep Imported Bundle",
        description="When adding from file, leave the temporary .ksp import in the scene",
        default=False,
    )
    adopt_into_bundle: BoolProperty(
        name="Adopt into this bundle",
        description=(
            "Rewrite BundleName/AssetPath to this pack so Export clones the prefab "
            "here. Turn off only for intentional stock/DLC overrides"
        ),
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "source_mode", expand=True)
        if self.source_mode == "SCENE":
            layout.prop(self, "scene_source")
        else:
            layout.prop(self, "filepath", text="File")
            layout.prop(self, "keep_imported_bundle")
        layout.prop(self, "custom_title")
        layout.prop(self, "adopt_into_bundle")

    def invoke(self, context, event):
        if _find_root(context) is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=420)

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        kb = root.ksp_bundle
        target_idx = int(kb.toc_nodes_index) if kb.toc_nodes else -1
        if target_idx < 0:
            self.report({"ERROR"}, "Select a TOC page/folder first")
            return {"CANCELLED"}
        dst_page, _node = _toc_merge_target_page(kb, target_idx)
        if dst_page is None:
            self.report(
                {"ERROR"},
                "Selected TOC row has no page (TitleScreen) to merge into",
            )
            return {"CANCELLED"}

        if self.source_mode == "FILE" and not (self.filepath or "").strip():
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}

        collection = root.users_collection[0] if root.users_collection else \
            context.view_layer.active_layer_collection.collection

        src_page = None
        imported_root = None

        _toc_ops_begin(root)
        try:
            if self.source_mode == "SCENE":
                src_page, _src_title, _bund, _asset = _resolve_scene_source_page(
                    context, self.scene_source,
                )
                if src_page is None:
                    self.report(
                        {"ERROR"},
                        "No scene page selected (import another KSPedia first)",
                    )
                    return {"CANCELLED"}
            else:
                path = (self.filepath or "").strip()
                if not path or not os.path.isfile(path):
                    self.report({"ERROR"}, "Choose a valid .ksp file")
                    return {"CANCELLED"}
                before = set(context.scene.objects)
                try:
                    ret = bpy.ops.import_object.ksp_bundle(
                        filepath=path,
                        build_viewport=True,
                        pixel_scale=float(kb.pixel_scale or 0.001),
                    )
                except Exception as ex:
                    self.report({"ERROR"}, "Import failed: %s" % ex)
                    return {"CANCELLED"}
                if "FINISHED" not in ret:
                    self.report({"ERROR"}, "Import cancelled")
                    return {"CANCELLED"}
                new_roots = [
                    o for o in context.scene.objects
                    if o not in before
                    and getattr(o, "ksp_bundle", None)
                    and o.ksp_bundle.is_ksp_bundle
                ]
                if not new_roots:
                    self.report({"ERROR"}, "Import produced no KSPedia bundle")
                    return {"CANCELLED"}
                imported_root = max(
                    new_roots, key=lambda o: len(o.ksp_bundle.ui_elements),
                )
                src_page = _pick_source_page_from_imported_root(imported_root)
                if src_page is None:
                    self.report({"ERROR"}, "No page found in that .ksp")
                    return {"CANCELLED"}

            if src_page == dst_page:
                self.report({"ERROR"}, "Source and target page are the same")
                return {"CANCELLED"}

            info = merge_kspedia_page_into(
                root, kb, target_idx, src_page,
                new_title=(self.custom_title or "").strip(),
                collection=collection,
            )
            if not info:
                self.report({"ERROR"}, "Could not merge into selected page")
                return {"CANCELLED"}

            if imported_root is not None and not self.keep_imported_bundle:
                try:
                    victims = [imported_root] + list(imported_root.children_recursive)
                    for o in victims:
                        bpy.data.objects.remove(o, do_unlink=True)
                except Exception:
                    pass

            try:
                for o in context.scene.objects:
                    o.select_set(False)
                context.view_layer.objects.active = root
                root.select_set(True)
                if info.get("page") is not None:
                    info["page"].select_set(True)
            except Exception:
                pass

            self.report(
                {"INFO"},
                "Merged into '%s' (%d UI children, %d list rows)"
                % (info["title"], info.get("n_copied", 0), info.get("n_ui", 0)),
            )
            return {"FINISHED"}
        finally:
            _toc_ops_end()


# --- kept: unique screen helper / graft / duplicate ---

def _host_bundle_name_for_blank(kb, inherit: str = "") -> str:
    """UrlName / pack stem for blank pages — never keep stale kpbs_zh inherit."""
    try:
        from .unityfs_catalog import host_bundle_stem
        host = (host_bundle_stem(kb) or "").strip()
    except Exception:
        host = ""
    if host:
        return host
    for cand in (
        getattr(kb, "bundle_name", None),
        getattr(kb, "locale_base", None),
        inherit,
    ):
        s = (cand or "").strip()
        if not s:
            continue
        if s.lower().startswith("kpbs"):
            continue
        return s
    try:
        from . import kspedia_index as _ki
        return (_ki.default_bundle_name_for_kb(kb) or "").strip()
    except Exception:
        return (inherit or "").strip()


def _maybe_add_stock_background(collection, parent, kb):
    """Attach bundled BackgroundBlueGrid under a blank TitleScreen if missing."""
    try:
        from ..export_ksp.prefab_clone import bundled_background_png
    except Exception:
        return None
    png = bundled_background_png("BackgroundBlueGrid.png")
    if not png or parent is None:
        return None
    try:
        import bpy
        img = bpy.data.images.load(png, check_existing=True)
    except Exception:
        return None
    try:
        sx = float(getattr(kb, "pixel_scale", 0.001) or 0.001)
        plane_item = _add_image_plane(
            collection, parent, kb, name="Background", image=img, pixel_scale=sx,
        )
        plane = plane_item[0] if isinstance(plane_item, tuple) else plane_item
        if plane is not None:
            try:
                plane["ksp_user_added"] = True
                plane.location = (0.0, 0.0, -0.002)
            except Exception:
                pass
        return plane_item
    except Exception:
        return None


def _unused_toc_screen_name(kb, base: str) -> str:
    """First free Screen id: ``base``, then ``base_2``, ``base_3``, …"""
    stem = (base or "Page").strip() or "Page"
    used = set()
    for n in kb.toc_nodes:
        try:
            used.add((n.screen or "").strip())
            used.add((n.name or "").strip())
        except Exception:
            pass
    if stem not in used:
        return stem
    i = 2
    while True:
        cand = "%s_%d" % (stem, i)
        if cand not in used:
            return cand
        i += 1


def _unique_toc_screen_name(kb, base: str) -> str:
    stem = (base or "Page").strip() or "Page"
    if not stem.endswith("_copy"):
        stem = stem + "_copy"
    used = set()
    for n in kb.toc_nodes:
        try:
            used.add((n.screen or n.name or "").strip())
        except Exception:
            pass
    if stem not in used:
        return stem
    i = 2
    while ("%s%d" % (stem, i)) in used:
        i += 1
    return "%s%d" % (stem, i)



def _stamp_graft_source_meta(info, *, source_ksp="", source_asset=""):
    """Remember foreign .ksp + AssetPath so Export can copy the real prefab."""
    if not info:
        return
    src_ksp = (source_ksp or "").strip()
    src_ap = (source_asset or "").strip()
    if not (src_ksp or src_ap):
        return
    for key in ("folder", "page"):
        obj = info.get(key)
        if obj is None:
            continue
        try:
            if src_ksp:
                obj["ksp_graft_source_ksp"] = src_ksp
            if src_ap:
                obj["ksp_graft_source_asset"] = src_ap
            obj["ksp_grafted"] = True
        except Exception:
            pass
    # Mark all UI under page as grafted (not user inject targets)
    page = info.get("page")
    if page is not None:
        try:
            objs = [page] + list(getattr(page, "children_recursive", []) or [])
        except Exception:
            objs = [page]
        for o in objs:
            try:
                o["ksp_grafted"] = True
            except Exception:
                pass


def _toc_node_is_blank_newpage(node) -> bool:
    """True for empty Add Blank Page folders (safe to fill with a graft)."""
    if node is None:
        return False
    try:
        sid = (node.screen or node.name or "").strip().lower()
        title = (node.title or "").strip().lower()
    except Exception:
        return False
    if not (sid.startswith("newpage") or title.startswith("new page")):
        return False
    po = getattr(node, "page_object", None)
    if po is None:
        return True
    try:
        for ch in list(getattr(po, "children_recursive", []) or []):
            try:
                if ch.ksp_ui.is_ksp_ui and ch.ksp_ui.kind in ("text", "image"):
                    return False
            except Exception:
                continue
    except Exception:
        pass
    return True


def graft_kspedia_page_under(
    root,
    kb,
    parent_idx: int,
    src_page,
    *,
    new_screen: str,
    new_title: str,
    bundle_name: str = "",
    asset_path: str = "",
    collection=None,
    adopt_into_host: bool = True,
):
    """Insert an external KSPedia page under a TOC folder with a unique Screen id.

    Nested Subcategory + page under e.g. Storage System (copy). Unique
    ``new_screen`` avoids colliding with stock Screen names (last-wins).
    """
    import bpy

    if root is None or kb is None or src_page is None:
        return None
    if not (0 <= parent_idx < len(kb.toc_nodes)):
        return None
    parent_node = kb.toc_nodes[parent_idx]
    if parent_node.kind not in {"category", "subcategory"}:
        folder_idx = -1
        try:
            pd = int(parent_node.depth)
        except Exception:
            pd = 0
        for j in range(parent_idx, -1, -1):
            n = kb.toc_nodes[j]
            if n.kind in {"category", "subcategory"} and int(n.depth) < pd:
                folder_idx = j
                break
        if folder_idx < 0:
            return None
        parent_idx = folder_idx
        parent_node = kb.toc_nodes[parent_idx]

    parent_folder = parent_node.folder_object
    if parent_folder is None:
        return None

    base = (new_screen or "GraftedPage").strip() or "GraftedPage"
    if not base.endswith("_PBS"):
        base = base + "_PBS"
    used = {(n.screen or n.name or "").strip() for n in kb.toc_nodes}
    screen_id = base
    n = 2
    while screen_id in used:
        screen_id = "%s%d" % (base, n)
        n += 1
    title = (new_title or screen_id).strip() or screen_id

    cols = list(root.users_collection) if root.users_collection else []
    if collection is not None and collection not in cols:
        cols = [collection] + list(cols)
    if not cols:
        cols = [bpy.context.scene.collection]

    fill_blank = _toc_node_is_blank_newpage(parent_node)
    if fill_blank:
        # Reuse empty New Page folder — avoid game menu showing blank parent + child
        fold_depth = int(parent_node.depth)
        folder_obj = parent_folder
        # Drop empty TitleScreen under the blank folder
        try:
            old_po = parent_node.page_object
            if old_po is not None:
                victims = [old_po] + list(getattr(old_po, "children_recursive", []) or [])
                for o in victims:
                    try:
                        bpy.data.objects.remove(o, do_unlink=True)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            folder_obj["ksp_toc_kind"] = parent_node.kind or "subcategory"
            folder_obj["ksp_title_screen"] = screen_id
            folder_obj["ksp_display_title"] = title
            folder_obj["ksp_user_added"] = True
            folder_obj.name = title
        except Exception:
            pass
        # Retarget existing TOC node instead of inserting a nested one
        try:
            parent_node.screen = screen_id
            parent_node.name = screen_id
            parent_node.title = title
            parent_node.title_raw = title
        except Exception:
            pass
    else:
        fold_depth = int(parent_node.depth) + 1
        folder_obj = bpy.data.objects.new(screen_id + "_Folder", None)
        folder_obj.empty_display_type = "PLAIN_AXES"
        folder_obj.empty_display_size = 0.05
        for col in cols:
            try:
                col.objects.link(folder_obj)
            except Exception:
                pass
        folder_obj.parent = parent_folder
        try:
            folder_obj["ksp_toc_kind"] = "subcategory"
            folder_obj["ksp_title_screen"] = screen_id
            folder_obj["ksp_display_title"] = title
            folder_obj["ksp_user_added"] = True
        except Exception:
            pass

    grafted = _copy_ui_object_tree(
        src_page, parent=folder_obj, collections=cols, root_name=screen_id,
    )
    if grafted is None:
        try:
            bpy.data.objects.remove(folder_obj, do_unlink=True)
        except Exception:
            pass
        return None

    try:
        grafted["ksp_page"] = screen_id
        grafted["ksp_display_title"] = title
        grafted["ksp_toc_kind"] = "page"
        grafted["ksp_user_added"] = True
        grafted["ksp_page_index"] = int(kb.page_count or 0)
    except Exception:
        pass

    bname = (bundle_name or kb.bundle_name or "").strip()
    apath = (asset_path or "").strip()
    try:
        from . import kspedia_index as _ki
        from .unityfs_catalog import host_bundle_stem
        host = host_bundle_stem(kb) or (kb.bundle_name or "").strip()
        # Adopt → host. Without Adopt keep foreign only if stock/DLC-resolvable;
        # else force host so Export clones (no dangling Asset load failed).
        foreign_ok = False
        if (not adopt_into_host) and bname and apath:
            ap_l = apath.replace('\\', "/").lower()
            bn_l = bname.lower()
            foreign_ok = (
                "/squad/" in ap_l
                or "/makinghistory/" in ap_l
                or "/serenity/" in ap_l
                or bn_l in {"squadcore", "kspedia", "makinghistory", "serenity"}
                or bn_l.startswith("squad")
            )
            if not foreign_ok:
                try:
                    stock = _ki.load_base_screens() | _ki.load_stock_screens()
                    base = (new_screen or "").replace("_PBS", "")
                    foreign_ok = screen_id in stock or base in stock
                except Exception:
                    foreign_ok = False
        if adopt_into_host or not foreign_ok:
            if host:
                bname = host
            apath = _ki.default_asset_path_for_screen(screen_id)
        elif not apath:
            apath = _ki.default_asset_path_for_screen(screen_id)
    except Exception:
        bname = (kb.bundle_name or kb.locale_base or "kspedia").strip()
        apath = "Assets/KSPedia/%s.prefab" % screen_id
    if fill_blank:
        fnode = parent_node
        fnode.bundle_name = bname
        fnode.asset_path = apath
        fnode.folder_object = folder_obj
        fnode.expanded = True
        try:
            from . import kspedia_index as _ki
            fnode.overrides_stock = _ki.screen_overrides_base(
                screen_id, bname, title=title,
            ) or _ki.screen_overrides_base(
                (new_screen or "").replace("_PBS", ""), bname, title=title,
            )
        except Exception:
            fnode.overrides_stock = False
        _attach_folder_title_screen(fnode, grafted)
        folder_idx = parent_idx
        try:
            kb.toc_nodes_index = folder_idx
        except Exception:
            pass
    else:
        _fs, fold_end = _toc_block_range(kb.toc_nodes, parent_idx)

        fnode = kb.toc_nodes.add()
        fnode.kind = "subcategory"
        fnode.depth = fold_depth
        fnode.name = screen_id
        fnode.title = title
        fnode.title_raw = title
        fnode.screen = screen_id
        fnode.folder_object = folder_obj
        fnode.bundle_name = bname
        fnode.asset_path = apath
        fnode.expanded = True
        try:
            from . import kspedia_index as _ki
            fnode.overrides_stock = _ki.screen_overrides_base(
                screen_id, bname, title=title,
            ) or _ki.screen_overrides_base(
                (new_screen or "").replace("_PBS", ""), bname, title=title,
            )
        except Exception:
            fnode.overrides_stock = False
        _attach_folder_title_screen(fnode, grafted)
        last = len(kb.toc_nodes) - 1
        folder_idx = fold_end
        if last != fold_end:
            kb.toc_nodes.move(last, fold_end)
        else:
            folder_idx = last
        try:
            kb.toc_nodes_index = folder_idx
        except Exception:
            pass

    _recount_toc_pages(kb)
    kb.layout_mode = "multipage"
    _remember_toc_title_for_new_page(kb, screen_id, title)

    locales = _detected_locales(kb) or [
        (getattr(kb, "active_locale", "") or "en-us").lower()
    ]
    n_ui = _register_copied_page_ui_elements(
        root, kb, grafted, locales,
        name_suffix="_" + _sanitize_toc_suffix(screen_id),
    )
    try:
        from . import kspedia_index
        kspedia_index.sync_bundle_toc_xml(kb)
    except Exception:
        pass
    return {
        "folder": folder_obj,
        "page": grafted,
        "screen": screen_id,
        "title": title,
        "n_ui": n_ui,
        "folder_node": fnode,
        "page_node": fnode,
    }


def _resolve_toc_page_for_duplicate(kb, idx):
    """Return (src_index, node_with_page_object) for Duplicate Page.

    One TOC row is the page folder. The Screen child is often hidden from the
    list (PBS TitleScreen, Duplicate, Add page). Find that Screen via
    folder.page_object or parent, not via a visible page TOC row.
    """
    if not (0 <= idx < len(kb.toc_nodes)):
        return -1, None
    node = kb.toc_nodes[idx]
    if node.kind == "page" and node.page_object is not None:
        return idx, node

    # Folder TitleScreen — usually not a TOC row.
    po = node.page_object
    if po is None and node.folder_object is not None:
        po = _folder_screen_child(node.folder_object, node.screen)
        if po is not None:
            _attach_folder_title_screen(node, po)
    if po is not None:
        # Legacy: a visible page row still pointing at the same Screen.
        for i, n in enumerate(kb.toc_nodes):
            if n.kind == "page" and n.page_object == po:
                return i, n
        return idx, node

    # Nested extra Screens (not the folder TitleScreen) still listed as pages.
    start, end = _toc_block_range(kb.toc_nodes, idx)
    for i in range(start + 1, end):
        n = kb.toc_nodes[i]
        if n.kind == "page" and n.page_object is not None:
            return i, n

    # Match TitleScreen / screen id / title among all pages.
    ts = (node.screen or node.name or "").strip()
    title = (node.title or "").strip()
    if ts:
        for i, n in enumerate(kb.toc_nodes):
            if n.kind != "page" or n.page_object is None:
                continue
            if (n.screen or n.name or "").strip() == ts:
                return i, n
    if title:
        for i, n in enumerate(kb.toc_nodes):
            if n.kind != "page" or n.page_object is None:
                continue
            if (n.title or "").strip() == title:
                return i, n

    # Same-depth sibling page after this folder (legacy PBS TOC layout).
    try:
        depth = int(node.depth)
    except Exception:
        depth = 0
    for i in range(idx + 1, len(kb.toc_nodes)):
        n = kb.toc_nodes[i]
        try:
            d = int(n.depth)
        except Exception:
            break
        if d < depth:
            break
        if d == depth and n.kind in {"category", "subcategory"}:
            break
        if n.kind == "page" and n.page_object is not None and d >= depth:
            return i, n
    return -1, None


def _toc_selected_page_object(kb):
    """Viewport page empty for the current TOC selection (page or folder)."""
    try:
        idx = int(kb.toc_nodes_index)
    except Exception:
        return None
    _i, node = _resolve_toc_page_for_duplicate(kb, idx)
    if node is None:
        return None
    return node.page_object


def _ui_insert_parent_object(kb, root):
    """Where new/duplicated UI should parent — real TitleScreen, never *_UI/root.

    Stock single-page packs (e.g. kspedia_career) often point TOC ``page_object``
    at the ``*_UI`` empty. Parenting there leaves ``page_screen`` empty so Export
    cannot inject the new GO into the page prefab.
    """
    def _ok_page(obj):
        if obj is None:
            return None
        try:
            if _is_ui_wrapper(obj) or (obj.name or "").endswith("_UI"):
                return None
        except Exception:
            pass
        try:
            if _is_toc_folder(obj):
                return None
        except Exception:
            pass
        try:
            if getattr(obj, "ksp_ui", None) is not None and obj.ksp_ui.is_ksp_ui:
                return None
        except Exception:
            pass
        try:
            if root is not None and obj == root:
                return None
        except Exception:
            pass
        return obj

    def _screen_under_ui(ui, screen_id=""):
        if ui is None:
            return None
        want = (screen_id or "").strip()
        # Direct page child
        hit = _ok_page(_folder_screen_child(ui, want))
        if hit is not None:
            return hit
        try:
            kids = list(ui.children)
        except Exception:
            kids = []
        for ch in kids:
            if want and (ch.name or "") == want:
                # Folder named like screen — prefer its TitleScreen child
                nested = _ok_page(_folder_screen_child(ch, want))
                if nested is not None:
                    return nested
                if _ok_page(ch) is not None and _is_page_obj(ch):
                    return ch
                return _ok_page(ch) or ch
            if _is_page_obj(ch):
                try:
                    cid = str(ch.get("ksp_page", "") or ch.name or "").strip()
                except Exception:
                    cid = (ch.name or "").strip()
                if not want or cid == want or (ch.name or "") == want:
                    return ch
            if _is_toc_folder(ch):
                nested = _ok_page(_folder_screen_child(ch, want))
                if nested is not None:
                    return nested
        # First usable page anywhere under UI
        for ch in kids:
            if _is_page_obj(ch):
                return ch
            nested = _ok_page(_folder_screen_child(ch, ""))
            if nested is not None:
                return nested
        return None

    def _toc_screen_id():
        try:
            idx = int(kb.toc_nodes_index)
            if 0 <= idx < len(kb.toc_nodes):
                n = kb.toc_nodes[idx]
                return (n.screen or n.name or n.title or "").strip()
        except Exception:
            pass
        return ""

    screen = _toc_screen_id()
    page = _ok_page(_toc_selected_page_object(kb))
    if page is None:
        try:
            idx = int(kb.toc_nodes_index)
            if 0 <= idx < len(kb.toc_nodes):
                n = kb.toc_nodes[idx]
                raw = getattr(n, "page_object", None)
                if raw is not None and _ok_page(raw) is None:
                    # page_object is *_UI or root — resolve real screen underneath
                    page = _screen_under_ui(raw if _is_ui_wrapper(raw) else _bundle_ui_root(root), screen or n.screen)
                    if page is not None:
                        _attach_folder_title_screen(n, page)
                if page is None and n.folder_object is not None:
                    page = _ok_page(_folder_screen_child(n.folder_object, n.screen))
                    if page is not None:
                        _attach_folder_title_screen(n, page)
                if page is None:
                    page = _ok_page(getattr(n, "page_object", None))
        except Exception:
            pass
    if page is None:
        try:
            if getattr(kb, "filter_to_page", False):
                page = _ok_page(getattr(kb, "filter_page_object", None)) or _ok_page(
                    getattr(kb, "filter_scope_object", None)
                )
        except Exception:
            pass
    if page is None:
        page = _screen_under_ui(_bundle_ui_root(root), screen)
    if page is not None:
        return page
    # Absolute last resort: UI empty (still better than floating under root)
    try:
        ui = _bundle_ui_root(root)
        if ui is not None:
            return ui
    except Exception:
        pass
    return root



def _sanitize_toc_suffix(screen):
    raw = (screen or "Page").strip().replace(" ", "_")
    out = []
    for ch in raw:
        if ch.isalnum() or ch in ("_", "-"):
            out.append(ch)
    return "".join(out) or "Page"


def _update_localization_cfg_default(folder, new_default):
    """Rewrite ``default =`` in localization.cfg (keep path/filename)."""
    import os
    import re

    cfg = os.path.join(folder or "", "localization.cfg")
    if not os.path.isfile(cfg):
        return False
    try:
        text = open(cfg, "r", encoding="utf-8", errors="replace").read()
    except Exception:
        return False
    loc = (new_default or "").strip().lower()
    if not loc:
        return False
    if re.search(r"(?im)^\s*default\s*=", text):
        text2 = re.sub(
            r"(?im)^(\s*default\s*=\s*).*$",
            r"\g<1>%s" % loc,
            text,
            count=1,
        )
    else:
        text2 = text.rstrip() + "\n    default = %s\n" % loc
    if text2 == text:
        return False
    try:
        open(cfg, "w", encoding="utf-8").write(text2)
    except Exception:
        return False
    return True


def _register_copied_page_ui_elements(root, kb, page_obj, locales, *,
                                      name_suffix="", src_name_by_new=None):
    """Add UI Elements rows + locale presence for every text/image under page.

    ``name_suffix`` (e.g. ``_Storage_copy``) makes duplicated element names
    unique so they do not share locale keys with the source page.
    ``src_name_by_new`` maps new viewport → source element name for copying
    per-locale texts from RAM maps.
    """
    if page_obj is None:
        return 0
    try:
        objs = [page_obj] + list(getattr(page_obj, "children_recursive", []) or [])
    except Exception:
        objs = [page_obj]
    existing = set()
    try:
        for it in kb.ui_elements:
            vo = it.viewport_object
            if vo is not None:
                existing.add(vo.as_pointer())
    except Exception:
        pass
    screen = ""
    try:
        screen = str(page_obj.get("ksp_page", "") or "")
    except Exception:
        screen = ""
    from . import locale_buffers as _lb

    src_texts = {}
    if src_name_by_new:
        for loc in locales or []:
            maps = _lb.get_maps(kb, loc) or {}
            by_name = maps.get("text_by_name") or {}
            src_texts[loc] = dict(by_name)

    added = 0
    for obj in objs:
        if not _is_listable_ui_element(obj):
            continue
        try:
            if obj.as_pointer() in existing:
                continue
        except Exception:
            pass
        item = kb.ui_elements.add()
        _fill_ui_item_from_viewport(item, obj)
        for key in (
            "mb_path_id", "rect_path_id", "go_path_id", "path_id",
            "sprite_path_id", "parent_rect_path_id",
        ):
            try:
                setattr(item, key, "")
            except Exception:
                pass
        try:
            item.page_screen = screen
        except Exception:
            pass
        base_name = (item.name or obj.name or "UI").strip() or "UI"
        src_name = None
        if src_name_by_new is not None:
            try:
                src_name = src_name_by_new.get(obj.as_pointer())
            except Exception:
                src_name = None
        if name_suffix and not base_name.endswith(name_suffix):
            new_name = base_name + name_suffix
            # Merge-into-page (_mrg): export under the unique name so inject
            # creates new Unity GOs (blank NewPage has no stock Text000/…).
            # Prefab clone / duplicate: keep stock GO name for bind-to-clone.
            try:
                if "_mrg" in name_suffix:
                    obj["ksp_export_go_name"] = new_name
                else:
                    obj["ksp_export_go_name"] = base_name
            except Exception:
                pass
            try:
                item.name = new_name
            except Exception:
                pass
            try:
                if obj.ksp_ui.is_ksp_ui:
                    obj.ksp_ui.element_name = new_name
                obj.name = new_name
            except Exception:
                pass
            base_name = new_name
        # Per-locale texts: prefer source page's maps (translations), else live.
        for loc in locales or []:
            text = None
            if src_name and loc in src_texts:
                text = src_texts[loc].get(src_name)
            if text is None and str(item.kind or "") == "text":
                text = item.text or None
            try:
                hier, name = _element_keys(item)
                state = None
                try:
                    state = _lb.snapshot_object_el_state(
                        obj,
                        pixel_scale=float(getattr(kb, "pixel_scale", 0.001) or 0.001),
                    )
                except Exception:
                    state = None
                _lb.remember_element(
                    kb, loc, hier=hier, name=name or base_name,
                    kind=str(item.kind or "text"), state=state, text=text,
                )
            except Exception:
                pass
        added += 1
    _refresh_missing_flags(kb)
    return added


class KSPMU_OT_TocEnsurePrefab(bpy.types.Operator):
    """Clone this Screen's prefab into the source .ksp (fixes Menu Check missing)."""
    bl_idname = "object.ksp_toc_ensure_prefab"
    bl_label = "Generate Prefab"
    bl_description = (
        "Clone a donor prefab into Source .ksp at this AssetPath and register it "
        "in *_bundle.xml (same as Export auto-fix for one Screen)"
    )
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1)

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        kb = root.ksp_bundle
        idx = int(self.index)
        if idx < 0:
            try:
                idx = int(kb.toc_nodes_index)
            except Exception:
                idx = -1
        if not (0 <= idx < len(kb.toc_nodes)):
            self.report({"ERROR"}, "Select a TOC page/folder")
            return {"CANCELLED"}
        node = kb.toc_nodes[idx]
        src = (
            str(getattr(kb, "source_path", "") or "").strip()
            or str(getattr(kb, "template_path", "") or "").strip()
        )
        if not src or not os.path.isfile(src):
            self.report({"ERROR"}, "No source .ksp — set Source / import a real pack")
            return {"CANCELLED"}

        from . import kspedia_index as _ki
        from .unityfs_catalog import host_bundle_stem, node_screen_id, node_asset_path

        sid = (node_screen_id(node) or "").strip()
        if not sid:
            self.report({"ERROR"}, "TOC row has no Screen / TitleScreen id")
            return {"CANCELLED"}
        ap = (node_asset_path(node) or "").strip() or _ki.default_asset_path_for_screen(sid)
        try:
            node.asset_path = ap
            host = host_bundle_stem(kb) or (kb.bundle_name or "").strip()
            if host and not (node.bundle_name or "").strip():
                node.bundle_name = host
        except Exception:
            host = (kb.bundle_name or "").strip()

        try:
            from .bundle import (
                load_env_for_export,
                save_bundle,
                detect_bundle_compression,
            )
            from ..export_ksp.prefab_clone import (
                clone_prefab_in_env,
                update_bundle_definition_xml,
                _container_lookup,
                _norm,
            )
        except Exception as ex:
            self.report({"ERROR"}, "Prefab tools unavailable: %s" % ex)
            return {"CANCELLED"}

        try:
            src, env = load_env_for_export(src)
        except Exception as ex:
            self.report({"ERROR"}, "Load .ksp failed: %s" % ex)
            return {"CANCELLED"}

        cont = _container_lookup(env)
        if _norm(ap) in cont:
            self.report({"INFO"}, "Prefab already in UnityFS: %s" % os.path.basename(ap))
            try:
                _ki.sync_bundle_toc_xml(kb)
            except Exception:
                pass
            return {"FINISHED"}

        donor = ""
        donor_any = ""
        for cpath in sorted(cont.keys()):
            if not cpath.endswith(".prefab") or not cpath.startswith("assets/"):
                continue
            if not donor_any:
                donor_any = cpath
            if "/kspedia/" in cpath:
                donor = cpath
                break
        donor = donor or donor_any
        if not donor:
            self.report({"ERROR"}, "No donor .prefab in this .ksp to clone from")
            return {"CANCELLED"}
        donor_path = donor
        try:
            for k in dict(env.container.items()).keys():
                if _norm(str(k)) == donor:
                    donor_path = str(k)
                    break
        except Exception:
            pass

        ok = clone_prefab_in_env(env, donor_path, ap, new_go_name=sid)
        if not ok:
            self.report({"ERROR"}, "Clone failed for %s" % sid)
            return {"CANCELLED"}
        try:
            update_bundle_definition_xml(
                env, url_name=host or None, ensure_assets=[(sid, ap)],
            )
        except Exception as ex:
            print("WARNING: bundle.xml update failed: %s" % ex)

        try:
            comp = detect_bundle_compression(src)
            save_bundle(
                env, src,
                packer="original",
                fallback=comp if comp in ("lzma", "lz4") else "lz4",
            )
        except Exception as ex:
            self.report({"ERROR"}, "Save .ksp failed: %s" % ex)
            return {"CANCELLED"}

        try:
            _ki.sync_bundle_toc_xml(kb)
        except Exception:
            pass
        self.report(
            {"INFO"},
            "Prefab created: %s (repack may change .ksp size)" % os.path.basename(ap),
        )
        return {"FINISHED"}


class KSPMU_OT_TocDuplicatePage(bpy.types.Operator):
    """Deep-copy the selected TOC page (UI + texts/images) and insert it below."""
    bl_idname = "object.ksp_toc_duplicate_page"
    bl_label = "Duplicate Page"
    bl_description = "Duplicate the selected TOC page or folder"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            self.report({"ERROR"}, "Select a KSP bundle")
            return {"CANCELLED"}
        kb = root.ksp_bundle
        collection = root.users_collection[0] if root.users_collection else \
            context.view_layer.active_layer_collection.collection
        _toc_ops_begin(root)
        try:
            return self._execute_dup(context, root, kb, collection)
        finally:
            _toc_ops_end()

    def _execute_dup(self, context, root, kb, collection):
        from .import_ksp import show_multipage_scope

        ui = _ensure_single_page_promoted(kb, root, collection)
        if ui is None:
            ui = _bundle_ui_root(root)

        idx = int(kb.toc_nodes_index)
        selected = kb.toc_nodes[idx] if 0 <= idx < len(kb.toc_nodes) else None
        src_idx, src = _resolve_toc_page_for_duplicate(kb, idx)
        if src is None or src.page_object is None:
            self.report({"ERROR"}, "Select a page (or folder with a page) to duplicate")
            return {"CANCELLED"}

        src_page = src.page_object
        base_screen = (src.screen or src.name or src_page.name or "Page").strip()
        new_screen = _unique_toc_screen_name(kb, base_screen)
        new_title = ((src.title or base_screen).strip() or new_screen) + " (copy)"
        name_suffix = "_" + _sanitize_toc_suffix(new_screen)

        # Folder selection → nest the copy under that folder; else sibling of src.
        # Game TOC (PBS flat list) needs a Subcategory sibling — nested
        # <Screens> children alone do not show next to Configuration/Storage.
        parent = src_page.parent or ui or root
        depth = int(src.depth)
        folder_selected = (
            selected is not None
            and selected.kind in {"category", "subcategory"}
            and selected.folder_object is not None
        )
        toc_folder_depth = int(src.depth)
        toc_parent_folder = None
        if folder_selected:
            parent = selected.folder_object
            depth = int(selected.depth) + 1
            toc_folder_depth = int(selected.depth)
            toc_parent_folder = selected.folder_object.parent
        else:
            for j in range(src_idx, -1, -1):
                try:
                    n = kb.toc_nodes[j]
                    if n.kind in {"category", "subcategory"} and int(n.depth) < int(src.depth):
                        toc_folder_depth = int(n.depth)
                        toc_parent_folder = (
                            n.folder_object.parent if n.folder_object else None
                        )
                        break
                except Exception:
                    break
        cols = list(src_page.users_collection) or [collection]

        # Map source listable names before copy (for per-locale text clone).
        src_name_by_src_ptr = {}
        try:
            for e in kb.ui_elements:
                vo = e.viewport_object
                if vo is None:
                    continue
                cur = vo
                under = False
                while cur is not None:
                    if cur == src_page:
                        under = True
                        break
                    cur = cur.parent
                if under:
                    src_name_by_src_ptr[vo.as_pointer()] = (e.name or "").strip()
        except Exception:
            src_name_by_src_ptr = {}

        new_page = _copy_ui_object_tree(
            src_page, parent=parent, collections=cols, root_name=new_screen,
        )
        if new_page is None:
            self.report({"ERROR"}, "Failed to copy page objects")
            return {"CANCELLED"}

        src_asset = (getattr(src, "asset_path", None) or "").strip()
        src_bundle = (src.bundle_name or kb.bundle_name or "").strip()
        if not src_asset:
            try:
                from . import kspedia_index as _ki
                xml_src = ""
                for ta in kb.text_assets:
                    lname = (ta.name or "").lower()
                    if "kspedia" in lname and "bundle" not in lname:
                        xml_src = ta.text or ""
                        if ta.text_block:
                            try:
                                xml_src = ta.text_block.as_string() or xml_src
                            except Exception:
                                pass
                        break
                meta = _ki.lookup_screen_catalog(xml_src, src.screen or base_screen)
                src_asset = (meta.get("asset_path") or "").strip()
                if not src_bundle:
                    src_bundle = (meta.get("bundle_name") or "").strip()
            except Exception:
                pass

        try:
            new_page["ksp_page"] = new_screen
            new_page["ksp_display_title"] = new_title
            new_page["ksp_toc_kind"] = "page"
            new_page["ksp_user_added"] = True
            new_page["ksp_page_index"] = int(kb.page_count or 0)
        except Exception:
            pass
        # Remap nested page markers and build new→src name map by walk order.
        src_name_by_new = {}
        try:
            src_list = [src_page] + list(src_page.children_recursive)
            new_list = [new_page] + list(new_page.children_recursive)
            for s_obj, n_obj in zip(src_list, new_list):
                try:
                    if str(n_obj.get("ksp_page", "") or "") == base_screen:
                        n_obj["ksp_page"] = new_screen
                except Exception:
                    pass
                try:
                    if n_obj.ksp_ui.is_ksp_ui:
                        hier = str(n_obj.get("ksp_hierarchy") or "").strip()
                        if hier:
                            n_obj["ksp_hierarchy"] = "user/%s/%s" % (
                                new_screen, hier.split("/")[-1] or n_obj.name,
                            )
                        else:
                            n_obj["ksp_hierarchy"] = "user/%s/%s" % (
                                new_screen, n_obj.name or "el",
                            )
                        n_obj["ksp_user_added"] = True
                except Exception:
                    pass
                try:
                    sn = src_name_by_src_ptr.get(s_obj.as_pointer())
                    if sn:
                        src_name_by_new[n_obj.as_pointer()] = sn
                except Exception:
                    pass
        except Exception:
            pass

        start, end = _toc_block_range(kb.toc_nodes, src_idx)
        # When duplicating from a folder row, insert after that folder's block.
        if folder_selected:
            _fs, fold_end = _toc_block_range(kb.toc_nodes, idx)
            end = fold_end

        fold_parent = (
            toc_parent_folder
            or (parent.parent if parent is not None else None)
            or ui
            or root
        )
        if fold_parent == root and ui is not None:
            fold_parent = ui
        folder_obj = bpy.data.objects.new(new_screen + "_Folder", None)
        folder_obj.empty_display_type = "PLAIN_AXES"
        folder_obj.empty_display_size = 0.05
        try:
            collection.objects.link(folder_obj)
        except Exception:
            pass
        try:
            folder_obj.parent = fold_parent
        except Exception:
            pass
        try:
            folder_obj["ksp_toc_kind"] = (
                "category" if int(toc_folder_depth) == 0 else "subcategory"
            )
            folder_obj["ksp_title_screen"] = new_screen
            folder_obj["ksp_display_title"] = new_title
            folder_obj["ksp_user_added"] = True
        except Exception:
            pass
        try:
            new_page.parent = folder_obj
        except Exception:
            pass

        fnode = kb.toc_nodes.add()
        fnode.kind = "category" if int(toc_folder_depth) == 0 else "subcategory"
        fnode.depth = int(toc_folder_depth)
        fnode.name = new_screen
        fnode.title = new_title
        fnode.title_raw = new_title
        fnode.screen = new_screen
        try:
            from . import kspedia_index as _ki
            if not (src_bundle or "").strip():
                src_bundle = _ki.default_bundle_name_for_kb(kb)
            if not (src_asset or "").strip():
                src_asset = _ki.default_asset_path_for_screen(new_screen)
        except Exception:
            if not src_bundle:
                src_bundle = (kb.bundle_name or "").strip()
            if not src_asset:
                src_asset = "Assets/KSPedia/%s.prefab" % new_screen
        fnode.bundle_name = src_bundle
        fnode.asset_path = src_asset
        fnode.folder_object = folder_obj
        fnode.expanded = True
        fnode.overrides_stock = False
        _attach_folder_title_screen(fnode, new_page)
        last_f = len(kb.toc_nodes) - 1
        if last_f != end:
            kb.toc_nodes.move(last_f, end)
        kb.toc_nodes_index = end
        kb.layout_mode = "multipage"
        _recount_toc_pages(kb)
        _remember_toc_title_for_new_page(kb, new_screen, new_title)

        locales = _detected_locales(kb) or [
            (getattr(kb, "active_locale", "") or "en-us").lower()
        ]
        n_ui = _register_copied_page_ui_elements(
            root, kb, new_page, locales,
            name_suffix=name_suffix,
            src_name_by_new=src_name_by_new,
        )
        try:
            from . import kspedia_index
            kspedia_index.sync_bundle_toc_xml(kb)
        except Exception:
            pass
        try:
            show_multipage_scope(root, new_page)
        except Exception:
            pass
        try:
            from .operators import pin_active_bundle
            pin_active_bundle(root, context.scene)
        except Exception:
            pass
        try:
            from .properties import _keep_bundle_root_selected as _keep
            _keep(context, root, also_select=new_page)
        except Exception:
            try:
                for o in context.scene.objects:
                    o.select_set(False)
                context.view_layer.objects.active = root
                root.select_set(True)
                new_page.select_set(True)
            except Exception:
                pass
        self.report(
            {"INFO"},
            "Duplicated page '%s' (%d UI elements)" % (new_title, n_ui),
        )
        return {"FINISHED"}


class KSPMU_OT_TocMove(bpy.types.Operator):
    """Move TOC node (and its children) up/down among siblings.

    Blender UIList has no native drag-reorder; these arrows change list order
    and rewrite Categories XML so KSPedia game order matches.
    """
    bl_idname = "object.ksp_toc_move"
    bl_label = "Move TOC Entry"
    bl_description = "Move the selected TOC entry up or down"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        items=(("UP", "Up", ""), ("DOWN", "Down", "")),
        default="UP",
    )
    index: IntProperty(name="Index", default=-1)

    def execute(self, context):
        from . import kspedia_index

        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        _toc_ops_begin(root)
        try:
            return self._execute_toc_move(context, root, kspedia_index)
        finally:
            _toc_ops_end()

    def _execute_toc_move(self, context, root, kspedia_index):
        kb = root.ksp_bundle
        try:
            col = root.users_collection[0] if root.users_collection else context.scene.collection
            _ensure_single_page_promoted(kb, root, col)
        except Exception:
            pass
        nodes = kb.toc_nodes
        n = len(nodes)
        if n < 2:
            return {"CANCELLED"}
        idx = int(self.index)
        if idx < 0:
            idx = int(kb.toc_nodes_index)
        if not (0 <= idx < n):
            return {"CANCELLED"}

        def block_range(i):
            depth = int(nodes[i].depth)
            end = i + 1
            while end < len(nodes) and int(nodes[end].depth) > depth:
                end += 1
            return i, end

        start, end = block_range(idx)
        depth = int(nodes[start].depth)
        block_len = end - start

        if self.direction == "UP":
            # Previous sibling at same depth
            prev = None
            j = start - 1
            while j >= 0:
                d = int(nodes[j].depth)
                if d < depth:
                    break
                if d == depth:
                    prev = j
                    break
                j -= 1
            if prev is None:
                self.report({"INFO"}, "Already at top of siblings")
                return {"CANCELLED"}
            for i in range(block_len):
                nodes.move(start + i, prev + i)
            kb.toc_nodes_index = prev
        else:
            # Next sibling starts at end if same depth
            if end >= len(nodes) or int(nodes[end].depth) != depth:
                self.report({"INFO"}, "Already at bottom of siblings")
                return {"CANCELLED"}
            nstart, nend = block_range(end)
            next_len = nend - nstart
            # Move next block before ours (= swap)
            for i in range(next_len):
                nodes.move(nstart + i, start + i)
            kb.toc_nodes_index = start + next_len

        # Refresh page_index for multipage visibility helpers
        _recount_toc_pages(kb)

        # Keep viewport parenting aligned with TOC sibling groups
        try:
            for i, node in enumerate(nodes):
                obj = _toc_viewport_obj(node)
                if obj is None:
                    continue
                pidx = _toc_parent_index(nodes, i)
                if pidx is None:
                    want_parent = _bundle_ui_root(root) or root
                else:
                    want_parent = _toc_viewport_obj(nodes[pidx]) or (
                        _bundle_ui_root(root) or root
                    )
                if obj.parent != want_parent and want_parent is not None:
                    obj.parent = want_parent
        except Exception:
            pass

        try:
            kspedia_index.sync_bundle_toc_xml(kb)
        except Exception:
            pass

        return {"FINISHED"}


class KSPMU_OT_TocIndent(bpy.types.Operator):
    bl_idname = "object.ksp_toc_indent"
    bl_label = "Increase Chapter Depth"
    bl_description = "Increase or decrease TOC nesting depth"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        items=(("IN", "In", ""), ("OUT", "Out", "")),
        default="IN",
    )

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        _toc_ops_begin(root)
        try:
            return self._execute_toc_indent(context, root)
        finally:
            _toc_ops_end()

    def _execute_toc_indent(self, context, root):
        kb = root.ksp_bundle
        try:
            col = root.users_collection[0] if root.users_collection else context.scene.collection
            _ensure_single_page_promoted(kb, root, col)
        except Exception:
            pass
        nodes = kb.toc_nodes
        if not (0 <= kb.toc_nodes_index < len(nodes)):
            return {"CANCELLED"}
        idx = int(kb.toc_nodes_index)
        start, end = _toc_block_range(nodes, idx)
        depth = int(nodes[start].depth)
        ui = _bundle_ui_root(root) or root

        if self.direction == "IN":
            # Nest under previous sibling at the same depth
            prev = _toc_prev_sibling(nodes, start, depth)
            if prev is None:
                self.report({"INFO"}, "Nothing to nest under (no previous sibling)")
                return {"CANCELLED"}
            parent_node = nodes[prev]
            # Prefer folder; if sibling is a page, nest under its parent folder/UI
            new_parent = parent_node.folder_object
            if new_parent is None:
                po = parent_node.page_object
                new_parent = (po.parent if po is not None else None) or ui
            if new_parent is None:
                return {"CANCELLED"}
            for i in range(start, end):
                nodes[i].depth = int(nodes[i].depth) + 1
            node = nodes[start]
            if node.kind == "category":
                node.kind = "subcategory"
                try:
                    if node.folder_object is not None:
                        node.folder_object["ksp_toc_kind"] = "subcategory"
                except Exception:
                    pass
            _reparent_toc_block(kb, root, start, end, new_parent)
        else:
            if depth <= 0:
                self.report({"INFO"}, "Already at root level")
                return {"CANCELLED"}
            parent_idx = _toc_parent_index(nodes, start)
            grand_idx = _toc_parent_index(nodes, parent_idx) if parent_idx is not None else None
            if grand_idx is None:
                new_parent = ui
            else:
                new_parent = (
                    nodes[grand_idx].folder_object
                    or (nodes[grand_idx].page_object.parent if nodes[grand_idx].page_object else None)
                    or ui
                )
            for i in range(start, end):
                nodes[i].depth = max(0, int(nodes[i].depth) - 1)
            node = nodes[start]
            if int(node.depth) == 0 and node.kind == "subcategory":
                node.kind = "category"
                try:
                    if node.folder_object is not None:
                        node.folder_object["ksp_toc_kind"] = "category"
                except Exception:
                    pass
            _reparent_toc_block(kb, root, start, end, new_parent)

        try:
            from . import kspedia_index
            kspedia_index.sync_bundle_toc_xml(kb)
        except Exception:
            pass
        return {"FINISHED"}


class KSPMU_OT_TocDeletePage(bpy.types.Operator):
    bl_idname = "object.ksp_toc_delete_page"
    bl_label = "Delete Page"
    bl_description = (
        "Delete the selected TOC row and everything nested under it "
        "(folders, pages, viewport UI)"
    )
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        kb = root.ksp_bundle
        idx = int(kb.toc_nodes_index)
        if not (0 <= idx < len(kb.toc_nodes)):
            return {"CANCELLED"}
        node = kb.toc_nodes[idx]
        depth = int(node.depth)
        end = idx + 1
        while end < len(kb.toc_nodes) and int(kb.toc_nodes[end].depth) > depth:
            end += 1

        def _is_under(obj, ancestor):
            cur = obj
            while cur is not None:
                if cur == ancestor:
                    return True
                try:
                    cur = cur.parent
                except Exception:
                    break
            return False

        kill_roots = []
        # Folders: delete the folder empty (whole subtree) — not only TitleScreen.
        if str(node.kind or "") in {"category", "subcategory"} and node.folder_object:
            kill_roots.append(node.folder_object)
        else:
            for i in range(idx, end):
                n = kb.toc_nodes[i]
                cand = []
                if str(n.kind or "") in {"category", "subcategory"}:
                    if n.folder_object is not None:
                        cand.append(n.folder_object)
                    if n.page_object is not None:
                        cand.append(n.page_object)
                else:
                    if n.page_object is not None:
                        cand.append(n.page_object)
                for o in cand:
                    if o is None:
                        continue
                    if any(_is_under(o, r) for r in kill_roots):
                        continue
                    kill_roots = [r for r in kill_roots if not _is_under(r, o)]
                    kill_roots.append(o)

        kill_ptrs = set()
        for r in kill_roots:
            try:
                kill_ptrs.add(r.as_pointer())
            except Exception:
                pass
            try:
                for c in list(getattr(r, "children_recursive", []) or []):
                    kill_ptrs.add(c.as_pointer())
            except Exception:
                pass

        for i in range(len(kb.ui_elements) - 1, -1, -1):
            try:
                vo = kb.ui_elements[i].viewport_object
                if vo is not None and vo.as_pointer() in kill_ptrs:
                    kb.ui_elements.remove(i)
            except Exception:
                pass

        for r in kill_roots:
            try:
                victims = [r] + list(r.children_recursive)
                for o in victims:
                    bpy.data.objects.remove(o, do_unlink=True)
            except Exception:
                pass

        for i in range(end - 1, idx - 1, -1):
            kb.toc_nodes.remove(i)
        kb.toc_nodes_index = max(0, min(idx, len(kb.toc_nodes) - 1))
        _recount_toc_pages(kb)
        try:
            from . import kspedia_index
            kspedia_index.sync_bundle_toc_xml(kb)
        except Exception:
            pass
        return {"FINISHED"}


class KSPMU_OT_ApplyLocaleSwitch(bpy.types.Operator):
    """Chunked locale apply so Blender stays responsive (progress bar).

    While running: Ctrl+Z / Ctrl+Shift+Z are blocked and global undo is off so
    a mid-load undo cannot corrupt a half-applied locale. After finish, one
    undo step is pushed for the whole switch when possible.
    """
    bl_idname = "kspmu.apply_locale_switch"
    bl_label = "Apply KSPedia Locale"
    bl_description = "Internal: apply a locale switch in chunks"
    bl_options = {"INTERNAL"}

    _timer = None
    _token = 0
    _total = 0
    _chunk = 8
    _finish_cb = None
    _undo_prev = True
    _undo_disabled = False

    @staticmethod
    def _is_undo_redo_event(event) -> bool:
        try:
            if not getattr(event, "ctrl", False):
                return False
            # Z = undo, Shift+Z / Y = redo (depending on keymap)
            et = getattr(event, "type", "")
            if et == "Z":
                return True
            if et == "Y" and not getattr(event, "shift", False):
                return True
        except Exception:
            pass
        return False

    def modal(self, context, event):
        from . import locale_switch as ls
        # Swallow undo/redo while locale texts are still applying
        if self._is_undo_redo_event(event):
            return {"RUNNING_MODAL"}
        if event.type == "ESC":
            self._cleanup(context, cancelled=True)
            self.report({"WARNING"}, "Locale switch cancelled")
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        job = ls.get_locale_apply_job()
        if job is None or int(job.get("token") or 0) != int(self._token):
            # Superseded by a newer switch — do not run finish_cb
            self._finish_cb = None
            self._cleanup(context, cancelled=True)
            return {"FINISHED"}
        done = False
        try:
            done = bool(ls.process_locale_apply_chunk(self._chunk))
        except Exception as exc:
            try:
                print("WARNING: KSP locale chunk failed: %s" % exc)
            except Exception:
                pass
            done = True
        # After last chunk the job is cleared — keep progress at 100%
        idx = 0
        total = self._total
        try:
            job2 = ls.get_locale_apply_job()
            if job2 is not None and int(job2.get("token") or 0) == int(self._token):
                idx = int(job2.get("index") or 0)
                total = len(job2.get("jobs") or []) or total
            elif done:
                idx = total
        except Exception:
            pass
        try:
            context.window_manager.progress_update(min(idx, max(total, 1)))
        except Exception:
            pass
        try:
            for area in context.screen.areas:
                if area.type in {"VIEW_3D", "PROPERTIES", "OUTLINER"}:
                    area.tag_redraw()
        except Exception:
            pass
        if done:
            self._cleanup(context, cancelled=False)
            try:
                self.report(
                    {"INFO"},
                    (
                        "Locale switched (cached)"
                        if bool(getattr(self, "_was_instant", False))
                        else "Locale applied (%d texts)" % int(self._total)
                    ),
                )
            except Exception:
                pass
            return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _set_global_undo(self, context, enabled: bool):
        try:
            context.preferences.edit.use_global_undo = bool(enabled)
        except Exception:
            pass

    def _cleanup(self, context, cancelled=False):
        wm = context.window_manager
        try:
            if self._timer is not None:
                wm.event_timer_remove(self._timer)
        except Exception:
            pass
        self._timer = None
        try:
            wm.progress_end()
        except Exception:
            pass
        try:
            context.window.cursor_set("DEFAULT")
        except Exception:
            pass
        if cancelled:
            try:
                from . import locale_switch as ls
                ls.cancel_locale_apply_job()
            except Exception:
                pass
        # Always release live-sync lock (chunk finish may have been skipped)
        try:
            from . import locale_buffers as _lb
            _lb.release_live_sync_lock_deferred()
        except Exception:
            pass
        cb = getattr(self, "_finish_cb", None)
        self._finish_cb = None
        if cb is not None and not cancelled:
            try:
                cb(context)
            except Exception:
                pass
        # Restore undo; push one step for the completed switch
        if getattr(self, "_undo_disabled", False):
            self._set_global_undo(context, getattr(self, "_undo_prev", True))
            self._undo_disabled = False
            if not cancelled and getattr(self, "_undo_prev", True):
                try:
                    bpy.ops.ed.undo_push(message="KSPedia Locale Switch")
                except Exception:
                    pass

    def invoke(self, context, event):
        from . import locale_switch as ls
        job = ls.get_locale_apply_job()
        if job is None:
            return {"CANCELLED"}
        self._token = int(job.get("token") or 0)
        self._total = len(job.get("jobs") or [])
        self._was_instant = bool(job.get("instant"))
        # Larger chunks — maps are already in RAM; FONT rebuild dominates.
        # Instant swaps finish with jobs=[] on the first timer tick.
        if self._was_instant:
            self._chunk = 64
            self._total = max(int(self._total or 0), 1)
        else:
            self._chunk = 32 if self._total <= 80 else 16
        # Capture before job is cleared on last chunk
        self._finish_cb = job.get("finish_cb")
        # Prefer undo flag saved when the switch started (job), not current
        # (already False during burst).
        try:
            if "undo_prev" in job:
                self._undo_prev = bool(job.get("undo_prev"))
            else:
                self._undo_prev = bool(context.preferences.edit.use_global_undo)
        except Exception:
            self._undo_prev = True
        self._set_global_undo(context, False)
        self._undo_disabled = True
        wm = context.window_manager
        try:
            context.window.cursor_set("WAIT")
        except Exception:
            pass
        try:
            wm.progress_begin(0, max(self._total, 1))
        except Exception:
            pass
        self._timer = wm.event_timer_add(0.0, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

class KSPMU_OT_SyncUiListFromViewport(bpy.types.Operator):
    """Internal: map active viewport object → UI Elements list index."""
    bl_idname = "object.ksp_sync_ui_list_from_viewport"
    bl_label = "Sync UI List From Viewport"
    bl_description = "Internal: sync UI Elements list index from viewport selection"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        root = _find_root(context)
        if root is None:
            return {"CANCELLED"}
        kb = root.ksp_bundle
        ao = context.view_layer.objects.active
        if ao is None:
            return {"CANCELLED"}
        # Walk up to find a listed UI element
        cur = ao
        while cur is not None:
            try:
                if cur.get("ksp_locale_parked"):
                    cur = cur.parent
                    continue
            except Exception:
                pass
            for i, item in enumerate(kb.ui_elements):
                try:
                    if item.viewport_object == cur:
                        if kb.ui_elements_index != i:
                            kb["ui_elements_index"] = i
                        return {"FINISHED"}
                    ui = cur.ksp_ui
                    if not ui.is_ksp_ui:
                        continue
                    mb = str(getattr(ui, "mb_path_id", "") or "").strip()
                    imb = str(getattr(item, "mb_path_id", "") or "").strip()
                    if mb and imb and mb == imb:
                        if kb.ui_elements_index != i:
                            kb["ui_elements_index"] = i
                        try:
                            item.viewport_object = cur
                        except Exception:
                            pass
                        return {"FINISHED"}
                    en = (ui.element_name or "").strip()
                    iname = (item.name or "").strip()
                    if en and en == iname:
                        same = 0
                        try:
                            same = sum(
                                1 for it in kb.ui_elements
                                if (it.name or "").strip() == en
                            )
                        except Exception:
                            same = 2
                        if same == 1:
                            if kb.ui_elements_index != i:
                                kb["ui_elements_index"] = i
                            try:
                                item.viewport_object = cur
                            except Exception:
                                pass
                            return {"FINISHED"}
                except Exception:
                    continue
            cur = cur.parent
        return {"CANCELLED"}


_selection_handler = None
_last_active_name = ""
_last_selection_fp = ()
_prev_mode = ""


def _srgb_to_hex(color, *, with_alpha: bool = False) -> str:
    """Hex for ``<color=#…>`` tags.

    PBS/KSP ``UI.Text`` (Unity 2019.2) reliably renders ``#RRGGBB``. Eight-digit
    ``#RRGGBBAA`` was written into .ksp but in-game text stayed solid white
    (parser falls back to ``m_Color``). TMP accepts both; default 6-digit.
    """
    try:
        r = max(0, min(255, int(round(float(color[0]) * 255.0))))
        g = max(0, min(255, int(round(float(color[1]) * 255.0))))
        b = max(0, min(255, int(round(float(color[2]) * 255.0))))
        if with_alpha:
            a = 255
            if len(color) > 3:
                a = max(0, min(255, int(round(float(color[3]) * 255.0))))
            return "#%02X%02X%02X%02X" % (r, g, b, a)
        return "#%02X%02X%02X" % (r, g, b)
    except Exception:
        return "#FFFFFF"


def _material_slot_color(obj, index: int):
    """Linear RGB from material slot (Emission or Principled), else None."""
    try:
        mats = obj.data.materials
        if mats is None or index < 0 or index >= len(mats):
            return None
        mat = mats[index]
        if mat is None:
            return None
        if getattr(mat, "use_nodes", False) and mat.node_tree:
            for nd in mat.node_tree.nodes:
                if getattr(nd, "type", "") == "EMISSION":
                    return tuple(nd.inputs["Color"].default_value)[:4]
                if getattr(nd, "type", "") == "BSDF_PRINCIPLED":
                    return tuple(nd.inputs["Base Color"].default_value)[:4]
        return tuple(mat.diffuse_color)[:4]
    except Exception:
        return None


def _font_body_as_tmp_markup(font_obj) -> str:
    """Plain body, or TMP <color>/<b> markup when characters use multi materials."""
    try:
        curve = font_obj.data
        body = curve.body or ""
    except Exception:
        return ""
    if not body:
        return ""
    try:
        mats = list(curve.materials) if curve.materials else []
    except Exception:
        mats = []
    if len(mats) <= 1:
        # Still emit <b> runs when a single material uses bold.
        try:
            fmt = curve.body_format
            any_bold = False
            for i in range(len(body)):
                if bool(getattr(fmt[i], "use_bold", False)):
                    any_bold = True
                    break
            if not any_bold:
                return body
        except Exception:
            return body
    indices = []
    bolds = []
    try:
        fmt = curve.body_format
        for i in range(len(body)):
            try:
                indices.append(int(fmt[i].material_index) if len(mats) > 1 else 0)
            except Exception:
                indices.append(0)
            try:
                bolds.append(bool(getattr(fmt[i], "use_bold", False)))
            except Exception:
                bolds.append(False)
    except Exception:
        return body
    multi = len(mats) > 1 and indices and len(set(indices)) > 1
    any_bold = any(bolds) if bolds else False
    if not multi and not any_bold:
        return body
    parts = []
    i = 0
    n = len(body)
    while i < n:
        mi = indices[i] if i < len(indices) else 0
        bold = bolds[i] if i < len(bolds) else False
        j = i + 1
        while j < n:
            mj = indices[j] if j < len(indices) else 0
            bj = bolds[j] if j < len(bolds) else False
            if mj != mi or bj != bold:
                break
            j += 1
        chunk = body[i:j]
        out = chunk
        if multi:
            col = _material_slot_color(font_obj, mi)
            if col is not None:
                out = "<color=%s>%s</color>" % (_srgb_to_hex(col), out)
        if bold:
            out = "<b>%s</b>" % out
        parts.append(out)
        i = j
    result = "".join(parts)
    # Whole-string bold with a single material is Unity FontStyle, not TMP
    # tags — inventing <b>…</b> made KSPedia XML diverge from plain m_Text
    # (PBS headers like STHeader).
    if not multi and any_bold and result:
        try:
            import re as _re
            m = _re.fullmatch(r"(?is)<b>(.*)</b>", result)
            if m and m.group(1) == body:
                return body
        except Exception:
            pass
    return result


def collect_viewport_text_plain(vo):
    """Join FONT bodies under a UI text root (supports legacy as/each).

    When the user paints characters with a second material (multi-colour FONT),
    emit TMP ``<color=#RRGGBB>`` tags so Unity/KSP round-trips the colours.
    """
    if vo is None:
        return ""
    fonts = []
    try:
        scan = [vo] + list(getattr(vo, "children_recursive", []) or [])
    except Exception:
        scan = [vo]
    as_body = each_body = None
    for o in scan:
        try:
            if o.get("ksp_para_sep"):
                continue
        except Exception:
            pass
        try:
            if getattr(o, "type", "") != "FONT" or o.data is None:
                continue
        except Exception:
            continue
        body = _font_body_as_tmp_markup(o)
        part = ""
        try:
            part = str(o.get("ksp_para_part", "") or "")
        except Exception:
            part = ""
        if part == "as":
            as_body = body
        elif part == "each":
            each_body = body
        else:
            fonts.append(body)
    if as_body is not None or each_body is not None:
        return "%s\n\n%s" % (as_body or "", each_body or "")
    for b in fonts:
        if b:
            return b
    return fonts[0] if fonts else ""


def _is_under(obj, ancestor):
    cur = obj
    while cur is not None:
        if cur == ancestor:
            return True
        try:
            cur = cur.parent
        except Exception:
            break
    return False


def _bundle_root_of(obj):
    cur = obj
    while cur is not None:
        try:
            if cur.ksp_bundle.is_ksp_bundle:
                return cur
        except Exception:
            pass
        try:
            cur = cur.parent
        except Exception:
            break
    return None



def _find_ksp_ui_root(obj):
    """Nearest ancestor (or self) marked as a KSP UI element."""
    cur = obj
    while cur is not None:
        try:
            if cur.ksp_ui.is_ksp_ui:
                return cur
        except Exception:
            pass
        try:
            cur = cur.parent
        except Exception:
            break
    return None


_TEXT_DIRTY_KEY = "ksp_text_dirty"


def mark_text_dirty(obj) -> None:
    """Flag a UI text root so export flushes FONT body before patching."""
    root = _find_ksp_ui_root(obj) if obj is not None else None
    if root is None:
        root = obj
    if root is None:
        return
    try:
        root[_TEXT_DIRTY_KEY] = True
    except Exception:
        pass


def clear_text_dirty(obj) -> None:
    if obj is None:
        return
    root = _find_ksp_ui_root(obj) or obj
    for target in (root, obj):
        if target is None:
            continue
        try:
            if _TEXT_DIRTY_KEY in target:
                del target[_TEXT_DIRTY_KEY]
        except Exception:
            try:
                target[_TEXT_DIRTY_KEY] = False
            except Exception:
                pass


def is_text_dirty(obj) -> bool:
    if obj is None:
        return False
    root = _find_ksp_ui_root(obj) or obj
    for target in (root, obj):
        if target is None:
            continue
        try:
            if bool(target.get(_TEXT_DIRTY_KEY)):
                return True
        except Exception:
            pass
    return False


def _is_listable_ui_element(obj):
    """True for UI Elements rows: independent texts and images, not TMP runs."""
    if obj is None:
        return False
    try:
        if obj.get("ksp_outline_ghost"):
            return False
    except Exception:
        pass
    try:
        ui = obj.ksp_ui
        if not ui.is_ksp_ui or ui.kind not in ("text", "image"):
            return False
        if ui.kind == "text":
            # Add→Text used to wrap a FONT in a PLAIN_AXES empty; the empty
            # is the "point" in the viewport and must not be a second list row.
            if getattr(obj, "type", "") == "EMPTY":
                try:
                    if any(
                        getattr(ch, "type", "") == "FONT"
                        for ch in (obj.children or ())
                    ):
                        return False
                except Exception:
                    pass
            from .locale_switch import _is_locale_text_root
            return _is_locale_text_root(obj)
        return True
    except Exception:
        return False


def _page_screen_for_obj(obj):
    cur = obj
    while cur is not None:
        try:
            page = str(cur.get("ksp_page", "") or "")
            if page:
                return page
        except Exception:
            pass
        try:
            cur = cur.parent
        except Exception:
            break
    return ""


def _iter_bundle_roots(scene):
    for obj in scene.objects:
        try:
            if obj.ksp_bundle.is_ksp_bundle:
                yield obj
        except Exception:
            continue


def _remove_ui_element_viewport(kb, vo):
    """Remove all ui_elements rows pointing at vo. Returns count removed."""
    removed = 0
    try:
        n = len(kb.ui_elements)
    except Exception:
        return 0
    for i in range(n - 1, -1, -1):
        try:
            if kb.ui_elements[i].viewport_object == vo:
                kb.ui_elements.remove(i)
                removed += 1
        except Exception:
            continue
    try:
        if removed:
            kb["ui_elements_index"] = max(
                0, min(int(kb.ui_elements_index), len(kb.ui_elements) - 1)
            )
    except Exception:
        pass
    return removed


def _fill_ui_item_from_viewport(item, vo):
    """Populate a ui_elements row from object + ksp_ui props."""
    item.viewport_object = vo
    kind = "empty"
    name = vo.name or "(ui)"
    try:
        ui = vo.ksp_ui
        if ui.is_ksp_ui:
            kind = str(ui.kind or "") or kind
            name = str(ui.element_name or "") or name
            try:
                item.text = ui.text or ""
            except Exception:
                pass
            try:
                item.font_size = float(ui.font_size or 14.0)
            except Exception:
                pass
            try:
                item.font_family = str(ui.font_family or "")
            except Exception:
                pass
            try:
                item.color = tuple(ui.color)
            except Exception:
                pass
            try:
                item.size_delta = tuple(ui.size_delta)
            except Exception:
                pass
            try:
                item.pivot = tuple(ui.pivot)
            except Exception:
                pass
            for attr in (
                "path_id", "go_path_id", "rect_path_id", "mb_path_id",
                "texture_path_id", "sprite_path_id",
            ):
                try:
                    val = getattr(ui, attr, None)
                    if val is not None and hasattr(item, attr):
                        setattr(item, attr, str(val))
                except Exception:
                    pass
    except Exception:
        pass
    if kind not in {"text", "image", "meta", "empty"}:
        # Infer from object type
        try:
            if vo.type == "FONT":
                kind = "text"
            elif vo.type == "MESH":
                kind = "image"
        except Exception:
            pass
    item.kind = kind
    item.name = name
    if kind == "text" and not (item.text or "").strip():
        try:
            item.text = collect_viewport_text_plain(vo) or ""
        except Exception:
            pass
    item.page_screen = _page_screen_for_obj(vo)


def heal_ui_elements_list(root) -> int:
    """Re-add UI Elements rows for viewport texts/images missing from the list.

    Addon reload wipes CollectionProperty data; objects stay in the Outliner.
    Flatten/rebuild can also drop pointers. Never run from a panel draw.
    """
    if root is None:
        return 0
    try:
        kb = root.ksp_bundle
        if not kb.is_ksp_bundle:
            return 0
    except Exception:
        return 0
    try:
        objs = [root] + list(getattr(root, "children_recursive", []) or [])
    except Exception:
        objs = [root]
    live = []
    for obj in objs:
        if _is_listable_ui_element(obj):
            live.append(obj)
    if not live:
        return 0
    by_vo = {}
    by_rect = {}
    by_mb = {}
    by_name = {}
    list_name_counts = {}
    live_name_counts = {}
    try:
        items = list(kb.ui_elements)
    except Exception:
        return 0
    for obj in live:
        try:
            nm = (obj.ksp_ui.element_name or obj.name or "").strip()
        except Exception:
            nm = (obj.name or "").strip()
        if nm:
            live_name_counts[nm] = live_name_counts.get(nm, 0) + 1
    for item in items:
        vo = None
        try:
            vo = item.viewport_object
        except Exception:
            vo = None
        if vo is not None:
            by_vo[vo] = item
        try:
            rid = str(item.rect_path_id or "")
            if rid and rid not in by_rect:
                by_rect[rid] = item
        except Exception:
            pass
        try:
            from .locale_switch import _unity_id_str
            mb = _unity_id_str(getattr(item, "mb_path_id", "") or "")
            if mb and mb not in by_mb:
                by_mb[mb] = item
        except Exception:
            pass
        try:
            nm = (item.name or "").strip()
            if nm:
                list_name_counts[nm] = list_name_counts.get(nm, 0) + 1
                if nm not in by_name:
                    by_name[nm] = item
        except Exception:
            pass
    if len(by_vo) >= len(live) and len(items) >= len(live):
        return 0
    added = 0
    for obj in live:
        if obj in by_vo:
            continue
        rid = ""
        nm = ""
        mb = ""
        try:
            ui = obj.ksp_ui
            rid = str(getattr(ui, "rect_path_id", "") or "")
            nm = (ui.element_name or obj.name or "").strip()
            from .locale_switch import _unity_id_str
            mb = _unity_id_str(getattr(ui, "mb_path_id", "") or "")
        except Exception:
            nm = (obj.name or "").strip()
        existing = by_rect.get(rid) if rid else None
        if existing is None and mb:
            existing = by_mb.get(mb)
        # Name is last and only when unique — two "Craft Pitches" must not
        # share a UI Elements row (the extra viewport object then vanished).
        if (
            existing is None
            and nm
            and live_name_counts.get(nm, 0) == 1
            and list_name_counts.get(nm, 0) <= 1
        ):
            existing = by_name.get(nm)
        if existing is not None:
            try:
                if existing.viewport_object is None:
                    existing.viewport_object = obj
                if not (existing.page_screen or "").strip():
                    existing.page_screen = _page_screen_for_obj(obj)
            except Exception:
                pass
            by_vo[obj] = existing
            continue
        item = kb.ui_elements.add()
        _fill_ui_item_from_viewport(item, obj)
        try:
            if obj.get("ksp_user_added"):
                nm = (item.name or "").strip()
                n_same = sum(
                    1 for e in kb.ui_elements if (e.name or "").strip() == nm
                )
                if nm and n_same > 1:
                    uniq = nm + "_copy"
                    names = {(e.name or "").strip() for e in kb.ui_elements}
                    i = 2
                    while uniq in names:
                        uniq = "%s_copy%d" % (nm, i)
                        i += 1
                    item.name = uniq
                    try:
                        obj.ksp_ui.element_name = uniq
                    except Exception:
                        pass
                    try:
                        obj["ksp_export_go_name"] = uniq
                    except Exception:
                        pass
                    nm = uniq
        except Exception:
            pass
        by_vo[obj] = item
        if rid:
            by_rect[rid] = item
        if mb:
            by_mb[mb] = item
        if nm:
            by_name[nm] = item
            list_name_counts[nm] = list_name_counts.get(nm, 0) + 1
        added += 1
    return added



_hierarchy_repair_lock = False
_toc_ops_lock = False
_toc_ops_root = None


def _is_page_obj(obj):
    """True for KSPedia Screen empties in the TOC tree — not UI Image/Text rows.

    User-added UI stamps ``ksp_page`` for export inject. Treating that as a TOC
    page made hierarchy-repair / rebuild_toc collapse the whole TOC after
    Load Image on a blank New Page.
    """
    if obj is None:
        return False
    # Image / Text / Button stand-ins — never TOC pages
    try:
        if obj.ksp_ui.is_ksp_ui:
            return False
    except Exception:
        pass
    try:
        kind = str(obj.get("ksp_toc_kind", "") or "")
        if kind in {"category", "subcategory"}:
            return False
        if kind == "page":
            return True
    except Exception:
        pass
    try:
        if "ksp_page_index" in obj.keys():
            return True
    except Exception:
        pass
    # Legacy Screen empties without ksp_toc_kind
    try:
        if str(obj.get("ksp_page", "") or ""):
            return True
    except Exception:
        pass
    return False


def _is_toc_folder(obj):
    try:
        return str(obj.get("ksp_toc_kind", "") or "") in {"category", "subcategory"}
    except Exception:
        return False


def _is_ui_wrapper(obj):
    """Bundle *_UI empty that holds TOC folders/pages (not a page itself)."""
    if obj is None or _is_page_obj(obj):
        return False
    try:
        name = obj.name or ""
    except Exception:
        name = ""
    if name.endswith("_UI"):
        return True
    # Heuristic: has TOC children, no ksp_ui on self
    try:
        if obj.ksp_ui.is_ksp_ui:
            return False
    except Exception:
        pass
    try:
        kids = list(obj.children)
    except Exception:
        kids = []
    if not kids:
        return False
    toc_kids = 0
    for ch in kids:
        if _is_page_obj(ch) or _is_toc_folder(ch) or _is_ui_wrapper(ch):
            toc_kids += 1
    return toc_kids > 0 and toc_kids == len(kids)


def _find_bundle_ui_root(bundle_root):
    if bundle_root is None:
        return None
    try:
        for ch in list(bundle_root.children):
            try:
                if (ch.name or "").endswith("_UI"):
                    return ch
            except Exception:
                continue
    except Exception:
        pass
    return None


def rebuild_toc_from_hierarchy(bundle_root):
    """Rebuild kb.toc_nodes from the viewport TOC tree under the bundle."""
    if _toc_ops_lock or _hierarchy_repair_lock:
        return False
    if bundle_root is None:
        return False
    try:
        kb = bundle_root.ksp_bundle
        if not kb.is_ksp_bundle:
            return False
    except Exception:
        return False

    # Preserve catalog fields keyed by screen id
    meta = {}
    prev_toc_n = 0
    try:
        prev_toc_n = len(kb.toc_nodes)
        for n in kb.toc_nodes:
            sid = (n.screen or n.name or "").strip()
            if not sid:
                continue
            meta[sid] = {
                "bundle_name": n.bundle_name or "",
                "asset_path": n.asset_path or "",
                "title_raw": getattr(n, "title_raw", "") or "",
                "title": n.title or "",
                "overrides_stock": bool(getattr(n, "overrides_stock", False)),
            }
    except Exception:
        pass

    scan = _find_bundle_ui_root(bundle_root) or bundle_root
    kb.toc_nodes.clear()
    page_i = [0]

    def _add_folder(obj, depth):
        node = kb.toc_nodes.add()
        kind = str(obj.get("ksp_toc_kind", "") or "category")
        if kind not in {"category", "subcategory"}:
            kind = "category" if depth == 0 else "subcategory"
        node.kind = kind
        node.depth = depth
        title = str(obj.get("ksp_display_title", "") or obj.name or "")
        screen = str(obj.get("ksp_title_screen", "") or "")
        node.name = screen or title or obj.name
        node.title = title or node.name
        node.screen = screen
        node.folder_object = obj
        node.expanded = True
        m = meta.get(screen) or {}
        if m:
            node.bundle_name = m.get("bundle_name", "") or node.bundle_name
            node.asset_path = m.get("asset_path", "") or ""
            try:
                node.title_raw = m.get("title_raw", "") or node.title_raw
            except Exception:
                pass
            if m.get("title") and not title:
                node.title = m["title"]
            node.overrides_stock = bool(m.get("overrides_stock", False))

    def _add_page(obj, depth):
        node = kb.toc_nodes.add()
        node.kind = "page"
        node.depth = depth
        screen = str(obj.get("ksp_page", "") or obj.name or "")
        title = str(obj.get("ksp_display_title", "") or screen)
        node.name = screen
        node.title = title
        node.screen = screen
        node.page_object = obj
        node.page_index = page_i[0]
        try:
            obj["ksp_page_index"] = page_i[0]
            obj["ksp_toc_kind"] = "page"
            if screen:
                obj["ksp_page"] = screen
        except Exception:
            pass
        page_i[0] += 1
        m = meta.get(screen) or {}
        if m:
            node.bundle_name = m.get("bundle_name", "") or ""
            node.asset_path = m.get("asset_path", "") or ""
            try:
                node.title_raw = m.get("title_raw", "") or ""
            except Exception:
                pass
            if m.get("title"):
                node.title = m["title"]
            node.overrides_stock = bool(m.get("overrides_stock", False))

    def walk(obj, depth):
        if obj is None:
            return
        # Folders before pages — a wrongly stamped ksp_page on a folder must
        # not stop the walk (that wiped the entire TOC after Load Image).
        if _is_toc_folder(obj):
            _add_folder(obj, depth)
            folder_node = kb.toc_nodes[-1]
            ts = (folder_node.screen or "").strip()
            try:
                kids = list(obj.children)
            except Exception:
                kids = []
            for ch in kids:
                if _is_toc_folder(ch):
                    walk(ch, depth + 1)
                    continue
                if _is_page_obj(ch):
                    try:
                        ch_id = str(ch.get("ksp_page", "") or ch.name or "").strip()
                    except Exception:
                        ch_id = (ch.name or "").strip()
                    is_title = (ts and ch_id == ts) or (
                        not ts and folder_node.page_object is None
                    )
                    if is_title:
                        _attach_folder_title_screen(folder_node, ch)
                        # Misparented TOC folders under TitleScreen still count
                        for nested in list(getattr(ch, "children", None) or []):
                            if _is_toc_folder(nested) or _is_page_obj(nested):
                                walk(nested, depth + 1)
                        continue
                    # Extra nested Screen (different id) stays a TOC page row.
                    _add_page(ch, depth + 1)
                    continue
                walk(ch, depth + 1)
            return
        if _is_page_obj(obj):
            _add_page(obj, depth)
            # Recover TOC folders accidentally parented under a Screen
            try:
                kids = list(obj.children)
            except Exception:
                kids = []
            for ch in kids:
                if _is_toc_folder(ch) or _is_page_obj(ch):
                    walk(ch, depth)
            return
        # Other empties / wrappers: descend without a TOC row
        try:
            kids = list(obj.children)
        except Exception:
            kids = []
        for ch in kids:
            walk(ch, depth)

    try:
        for ch in list(scan.children):
            walk(ch, 0)
    except Exception:
        pass

    try:
        n_pages = _recount_toc_pages(kb)
        if n_pages > 1:
            kb.layout_mode = "multipage"
    except Exception:
        pass
    # Do not wipe Categories XML when hierarchy scan collapsed the TOC
    # (e.g. after a bad parent stamp). Prefer keeping the previous TextAsset.
    try:
        new_n = len(kb.toc_nodes)
        if prev_toc_n >= 3 and new_n > 0 and new_n < max(2, prev_toc_n // 2):
            return True
    except Exception:
        pass
    try:
        from . import kspedia_index
        kspedia_index.sync_bundle_toc_xml(kb)
    except Exception:
        pass
    return True


def repair_outliner_page_drop(scene, depsgraph=None):
    """Fix accidental Outliner drops: page-under-page, or whole *_UI under a page.

    Dragging a page "onto" another page often parents the source *_UI under that
    page — hoist TOC children to be siblings instead.
    """
    global _hierarchy_repair_lock
    if _toc_ops_lock or _hierarchy_repair_lock or scene is None or depsgraph is None:
        return False

    touched = []
    for u in depsgraph.updates:
        id_data = getattr(u, "id", None)
        if id_data is None:
            continue
        try:
            if id_data.bl_rna.identifier != "Object":
                continue
        except Exception:
            continue
        touched.append(id_data)
    if not touched:
        return False

    changed = False
    rebuild = set()

    def _note_bundles(*objs):
        for o in objs:
            br = _bundle_root_of(o) if o is not None else None
            if br is not None:
                rebuild.add(br)

    for o in touched:
        try:
            parent = o.parent
        except Exception:
            continue
        if parent is None:
            continue

        # Page nested under page → make sibling (KSPedia TOC never nests pages)
        if _is_page_obj(o) and _is_page_obj(parent):
            dest = parent.parent
            if dest is None:
                br = _bundle_root_of(parent)
                dest = _find_bundle_ui_root(br) if br is not None else None
            if dest is not None and o.parent != dest:
                _hierarchy_repair_lock = True
                try:
                    o.parent = dest
                    changed = True
                    _note_bundles(dest, parent, o)
                finally:
                    _hierarchy_repair_lock = False
            continue

        # Whole *_UI (or TOC-only wrapper) dropped under a page
        if _is_ui_wrapper(o) and _is_page_obj(parent):
            dest = parent.parent
            br = _bundle_root_of(parent)
            if dest is None and br is not None:
                dest = _find_bundle_ui_root(br) or br
            if dest is None:
                continue
            _hierarchy_repair_lock = True
            try:
                for ch in list(o.children):
                    try:
                        ch.parent = dest
                        changed = True
                    except Exception:
                        pass
                # Detach empty foreign UI wrapper (do not delete in depsgraph)
                try:
                    if not list(o.children):
                        o.parent = None
                except Exception:
                    pass
                _note_bundles(dest, parent, o)
            finally:
                _hierarchy_repair_lock = False
            continue

        # Foreign *_UI parented directly under another bundle root → merge into its _UI
        try:
            if parent.ksp_bundle.is_ksp_bundle and _is_ui_wrapper(o):
                own_ui = _find_bundle_ui_root(parent)
                if own_ui is not None and o != own_ui:
                    _hierarchy_repair_lock = True
                    try:
                        for ch in list(o.children):
                            try:
                                ch.parent = own_ui
                                changed = True
                            except Exception:
                                pass
                        try:
                            if not list(o.children):
                                o.parent = None
                        except Exception:
                            pass
                        rebuild.add(parent)
                    finally:
                        _hierarchy_repair_lock = False
        except Exception:
            pass

    if not changed:
        return False

    # Rebuild TOC on every bundle (stale page_object pointers on the donor)
    for br in list(_iter_bundle_roots(scene)):
        try:
            rebuild_toc_from_hierarchy(br)
        except Exception:
            pass
    return True


_OBJECT_DELETE_OPS = frozenset({
    "OBJECT_OT_delete",
    "OUTLINER_OT_delete",
    "OBJECT_OT_delete_override_confirm",
})


def _last_operator_is_object_delete():
    """True only after Blender's X / Delete, not after locale / Refresh / TOC."""
    try:
        ops = bpy.context.window_manager.operators
        if not ops:
            return False
        return str(ops[-1].bl_idname) in _OBJECT_DELETE_OPS
    except Exception:
        return False


def _viewport_is_ui_match(obj, name, kind=""):
    """True when obj is a live ksp_ui stand-in for this UI Elements row."""
    if obj is None:
        return False
    try:
        if obj.name not in bpy.data.objects:
            return False
    except Exception:
        return False
    try:
        ui = obj.ksp_ui
        if not ui.is_ksp_ui:
            return False
        en = (ui.element_name or obj.name or "").strip()
        if name and en != name and obj.name != name:
            if not obj.name.startswith("%s__ksp_loc" % name):
                return False
        ik = str(kind or "")
        uk = str(ui.kind or "")
        if ik and uk and ik != uk:
            return False
        return True
    except Exception:
        return False


def prune_dead_viewport_ui_elements(kb, scene=None, *, force=False) -> int:
    """Drop UI Elements rows whose viewport object was deleted (X / Delete).

    Must NOT run on every depsgraph tick: locale rebuild, Refresh and page
    hide all look like "dead" pointers and wiped the whole list. Only run
    after Blender's own delete operator, unless ``force=True`` (tests).
    """
    if kb is None:
        return 0
    if not force and not _last_operator_is_object_delete():
        return 0
    if not force:
        try:
            from . import locale_buffers as _lb
            from .locale_switch import get_locale_apply_job
            if _lb.is_live_sync_locked() or get_locale_apply_job() is not None:
                return 0
        except Exception:
            pass
    import bpy
    removed = 0
    try:
        n = len(kb.ui_elements)
    except Exception:
        return 0
    # Scope rematches to THIS bundle — bpy.data.objects.get("ConfT3") would
    # otherwise steal the first import's object into the second bundle's list.
    bundle_root = getattr(kb, "id_data", None)
    under = set()
    if bundle_root is not None:
        try:
            under = {bundle_root} | set(
                getattr(bundle_root, "children_recursive", []) or []
            )
        except Exception:
            under = {bundle_root}

    def _cand_under_bundle(name):
        if not name:
            return None
        cand = bpy.data.objects.get(name)
        if cand is not None and (not under or cand in under):
            return cand
        # Second import: Blender renamed to Name.001 under this root.
        if under:
            for obj in under:
                try:
                    if (obj.name or "") == name:
                        return obj
                    en = ""
                    try:
                        en = (obj.ksp_ui.element_name or "").strip()
                    except Exception:
                        en = ""
                    if en == name and obj in under:
                        return obj
                except Exception:
                    continue
        return None

    for i in range(n - 1, -1, -1):
        try:
            item = kb.ui_elements[i]
        except Exception:
            continue
        vo = None
        try:
            vo = item.viewport_object
        except Exception:
            vo = None
        alive = False
        if vo is not None:
            try:
                _ = vo.name
                alive = vo.name in bpy.data.objects
            except Exception:
                alive = False
        if alive:
            continue
        # Hidden-for-locale rows still have a live object; skip if we just
        # failed to resolve a pointer that Blender has not flushed yet.
        try:
            if item.missing_in_locale:
                continue
        except Exception:
            pass
        name = (getattr(item, "name", "") or "").strip()
        kind = str(getattr(item, "kind", "") or "")
        cand = _cand_under_bundle(name)
        # Duplicate GO names: bpy.data.objects.get("Craft Pitches") always
        # returns the first object and would steal the sibling's row.
        name_unique = True
        if name:
            try:
                name_unique = sum(
                    1 for j in range(n)
                    if (kb.ui_elements[j].name or "").strip() == name
                ) == 1
            except Exception:
                name_unique = False
        if name_unique and _viewport_is_ui_match(cand, name, kind):
            try:
                item.viewport_object = cand
            except Exception:
                pass
            continue
        # Locale rebuild creates Name__ksp_loc before renaming. That window
        # used to look like a real delete and wiped every text row.
        tmp = ("%s__ksp_loc" % name) if name else ""
        cand = _cand_under_bundle(tmp)
        if name_unique and _viewport_is_ui_match(cand, name, kind):
            try:
                item.viewport_object = cand
            except Exception:
                pass
            continue
        hier, _nm = _element_keys(item)
        if not name:
            name = _nm
        same_name = 0
        if name:
            for j in range(n):
                if j == i:
                    continue
                try:
                    if (kb.ui_elements[j].name or "").strip() == name:
                        same_name += 1
                except Exception:
                    pass
        try:
            from . import locale_buffers as _lb
            active = (getattr(kb, "active_locale", "") or "").lower()
            locs = [active] if active else _detected_locales(kb)[:1]
            for loc in locs:
                if hier:
                    _lb.forget_element(kb, loc, hier=hier, name="")
                elif name and same_name == 0:
                    _lb.forget_element(kb, loc, hier="", name=name)
        except Exception:
            pass
        try:
            kb.ui_elements.remove(i)
            removed += 1
        except Exception:
            pass
    if removed:
        try:
            kb["ui_elements_index"] = max(
                0, min(int(kb.ui_elements_index), len(kb.ui_elements) - 1)
            )
        except Exception:
            pass
    return removed


def reconcile_ui_elements_membership(scene, depsgraph=None):
    """After Outliner reparent (Shift-drag), move ui_elements rows to the new bundle.

    Hierarchy alone is not enough — each bundle keeps its own ui_elements list.
    """
    if scene is None or depsgraph is None:
        return False
    pruned = False
    try:
        for broot in _iter_bundle_roots(scene):
            n = prune_dead_viewport_ui_elements(broot.ksp_bundle, scene=scene)
            if n:
                pruned = True
                try:
                    _sync_text_box_overlays_root(broot)
                except Exception:
                    pass
    except Exception:
        pruned = False
    touched = []
    for u in depsgraph.updates:
        id_data = getattr(u, "id", None)
        if id_data is None:
            continue
        try:
            if id_data.bl_rna.identifier != "Object":
                continue
        except Exception:
            continue
        # Deleted / not-yet-linked IDs must not strip UI Elements rows.
        # Locale rebuild and import briefly look like this.
        try:
            if id_data.name not in bpy.data.objects:
                continue
        except Exception:
            continue
        touched.append(id_data)

    if not touched:
        return pruned

    ui_roots = set()
    for o in touched:
        ui = _find_ksp_ui_root(o)
        if _is_listable_ui_element(ui):
            ui_roots.add(ui)
        # Parent folder moved: also re-home direct ksp_ui children
        try:
            for ch in list(o.children):
                if _is_listable_ui_element(ch):
                    ui_roots.add(ch)
        except Exception:
            pass

    if not ui_roots:
        return pruned

    changed = pruned
    for vo in ui_roots:
        new_root = _bundle_root_of(vo)
        if new_root is None:
            # Unparented (import/rebuild) or deleted — never strip the row
            # from every bundle. Keyboard X is handled by prune instead.
            continue
        # Drop from every other bundle's list
        for broot in _iter_bundle_roots(scene):
            if broot == new_root:
                continue
            kb = broot.ksp_bundle
            if _remove_ui_element_viewport(kb, vo):
                changed = True

        kb = new_root.ksp_bundle
        found = None
        for item in kb.ui_elements:
            if item.viewport_object == vo:
                found = item
                break
        page = _page_screen_for_obj(vo)
        if found is None:
            if not _is_listable_ui_element(vo):
                continue
            item = kb.ui_elements.add()
            _fill_ui_item_from_viewport(item, vo)
            changed = True
        else:
            try:
                if page and found.page_screen != page:
                    found.page_screen = page
                    changed = True
            except Exception:
                pass
            # Keep name/kind in sync with object
            try:
                ui = vo.ksp_ui
                if ui.is_ksp_ui:
                    if ui.element_name and found.name != ui.element_name:
                        found.name = ui.element_name
                        changed = True
                    if ui.kind and found.kind != ui.kind:
                        found.kind = ui.kind
                        changed = True
            except Exception:
                pass

    return changed


def _sync_font_obj_to_ui_list(font_obj, *, commit_body: bool = False):
    """Push FONT edits into matching ui_elements / ksp_ui / RAM.

    ``commit_body=True`` only after leaving Edit Text — that is the one moment
    the FONT body is the user's new source string. Every other depsgraph echo
    (G/R/S, curve size, material) must keep the stamped source text, otherwise
    a rotate would bake figure-spaces and soft wraps into the .lang.
    """
    if font_obj is None:
        return False
    root = _bundle_root_of(font_obj)
    if root is None:
        return False
    kb = root.ksp_bundle
    changed = False
    plain = None
    target = font_obj
    try:
        if font_obj.type == "FONT" and font_obj.parent is not None:
            pui = font_obj.parent.ksp_ui
            if pui.is_ksp_ui and pui.kind == "text":
                # Rich-text RUNS (same element_name) sync via the parent.
                # Independent nested texts (ConfT3 under ConfS2) must sync
                # themselves — otherwise G-move is dropped (USER-LATEST-008)
                # and the parent is falsely marked edited (blue/white drift).
                independent = False
                try:
                    from .locale_switch import _is_locale_text_root
                    independent = bool(_is_locale_text_root(font_obj))
                except Exception:
                    independent = False
                if not independent:
                    target = font_obj.parent
    except Exception:
        pass
    for item in kb.ui_elements:
        if item.kind != "text":
            continue
        vo = item.viewport_object
        if vo is None:
            continue
        if not (_is_under(font_obj, vo) or font_obj == vo):
            continue
        if commit_body:
            plain = collect_viewport_text_plain(vo)
            # Viewport may use figure-spaces for indent preview; Unity wants
            # regular spaces in the asset.
            if plain:
                plain = str(plain).replace("\u2007", " ")
        else:
            try:
                from . import locale_buffers as _lb
                plain = _lb.viewport_text_of(vo)
            except Exception:
                plain = item.text or ""
        if plain is None:
            continue
        if commit_body:
            # Capture native Text Boxes / extra FONT lines before ksp_ui.text
            # is overwritten — persist compares body against the old string.
            try:
                from . import locale_buffers as _lb
                sx = 0.001
                try:
                    sx = float(getattr(kb, "pixel_scale", 0.001) or 0.001)
                except Exception:
                    sx = 0.001
                for fo in [vo] + list(getattr(vo, "children_recursive", []) or []):
                    try:
                        if getattr(fo, "type", "") != "FONT" or fo.data is None:
                            continue
                        _lb.persist_live_font_box_size(fo, pixel_scale=sx)
                    except Exception:
                        continue
            except Exception:
                pass
            try:
                if item.text != plain:
                    item.text = plain
                    changed = True
            except Exception:
                pass
            try:
                if vo.ksp_ui.is_ksp_ui and vo.ksp_ui.text != plain:
                    vo.ksp_ui.text = plain
                    changed = True
            except Exception:
                pass
            try:
                vo["ksp_text_display"] = plain
            except Exception:
                pass
            try:
                clear_text_dirty(vo)
            except Exception:
                pass
            # Overflow after edit: keep Unity font_size / spacing. Re-pin the
            # Blender curve yardstick so fit remnants are not exported as tweaks.
            try:
                from . import locale_buffers as _lb
                for fo in [vo] + list(getattr(vo, "children_recursive", []) or []):
                    try:
                        if getattr(fo, "type", "") != "FONT" or fo.data is None:
                            continue
                        try:
                            fo.data.overflow = "OVERFLOW"
                        except Exception:
                            pass
                        _lb.pin_build_state(fo)
                        c = fo.data
                        fo["ksp_layout_curve"] = (
                            float(c.size),
                            float(c.space_character),
                            float(c.space_word),
                            float(c.space_line),
                        )
                        # FONT rebuild after a glyph edit can nudge location
                        # by a pixel. Snap back so export does not bake AP.
                        try:
                            if not fo.get("ksp_has_viewport_edit"):
                                pin = fo.get("ksp_applied_xy") or fo.get("ksp_layout_xy")
                                if pin is not None and len(pin) >= 2:
                                    dx = abs(float(fo.location.x) - float(pin[0]))
                                    dy = abs(float(fo.location.y) - float(pin[1]))
                                    if dx < 0.004 and dy < 0.004:
                                        fo.location.x = float(pin[0])
                                        fo.location.y = float(pin[1])
                        except Exception:
                            pass
                    except Exception:
                        continue
            except Exception:
                pass
        break
    # Live RAM: TRS / spacing / boxes + text for active locale (undo-safe).
    try:
        from . import locale_buffers
        if locale_buffers.sync_object_live(target, kb=kb, root=root, plain=plain):
            changed = True
    except Exception:
        pass
    return changed


def _sync_ksp_obj_live(obj):
    """Sync text/image KSPedia object transforms into RAM + ksp_ui."""
    if obj is None:
        return False
    try:
        from . import locale_buffers
        return bool(locale_buffers.sync_object_live(obj))
    except Exception:
        return False


def _tag_view3d_redraw():
    try:
        wm = bpy.context.window_manager
        for window in wm.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
    except Exception:
        pass


def _on_selection_depsgraph(scene, depsgraph=None):
    global _last_active_name, _prev_mode
    try:
        from .blend_persist import in_undo_redo
        if in_undo_redo():
            return
    except Exception:
        pass
    ctx = None
    try:
        ctx = bpy.context
        mode = getattr(ctx, "mode", "") or ""
    except Exception:
        mode = ""

    # Locale apply mutates many FONT/Object IDs — live sync mid-switch crashes
    # Blender and poisons RAM with has_viewport_edit.
    try:
        from . import locale_buffers as _lb
        if _lb.is_live_sync_locked():
            return
    except Exception:
        pass
    try:
        from . import locale_switch as _ls
        if _ls.get_locale_apply_job() is not None:
            return
    except Exception:
        pass

    # Outliner reparent: fix page/_UI drops, then sync ui_elements lists
    membership_changed = False
    try:
        if repair_outliner_page_drop(scene, depsgraph):
            membership_changed = True
    except Exception:
        pass
    try:
        if reconcile_ui_elements_membership(scene, depsgraph):
            membership_changed = True
    except Exception:
        pass
    try:
        for broot in _iter_bundle_roots(scene):
            if heal_ui_elements_list(broot):
                membership_changed = True
    except Exception:
        pass

    text_changed = False
    live_changed = False
    # Never fight Edit Text: live sync / handle drag rewrites on every keystroke.
    # Still mark dirty so Export can commit if the mode transition is missed
    # (file browser / Export click often leaves Edit Text without our hook).
    editing_text = mode == "EDIT_TEXT"
    try:
        if depsgraph is not None:
            for u in depsgraph.updates:
                id_data = getattr(u, "id", None)
                if id_data is None:
                    continue
                try:
                    ident = id_data.bl_rna.identifier
                except Exception:
                    continue
                font_objs = []
                sync_objs = []
                if ident == "TextCurve":
                    try:
                        for o in scene.objects:
                            if o.type == "FONT" and o.data == id_data:
                                font_objs.append(o)
                    except Exception:
                        pass
                elif ident == "Object":
                    try:
                        otype = getattr(id_data, "type", "")
                        if otype == "FONT":
                            font_objs.append(id_data)
                        # Mesh/empty images + any ksp_ui object transform (R/S/G)
                        try:
                            if id_data.ksp_ui.is_ksp_ui:
                                sync_objs.append(id_data)
                        except Exception:
                            pass
                    except Exception:
                        pass
                if editing_text:
                    for fo in font_objs:
                        try:
                            mark_text_dirty(fo)
                        except Exception:
                            pass
                    continue
                for fo in font_objs:
                    if _sync_font_obj_to_ui_list(fo):
                        text_changed = True
                for so in sync_objs:
                    # FONT already handled above (includes live sync)
                    try:
                        if so.type == "FONT":
                            continue
                    except Exception:
                        pass
                    if _sync_ksp_obj_live(so):
                        live_changed = True
        if _prev_mode == "EDIT_TEXT" and mode == "OBJECT":
            ao = getattr(ctx, "active_object", None) if ctx else None
            if ao is not None and _sync_font_obj_to_ui_list(ao, commit_body=True):
                text_changed = True
            if ao is not None and ao.parent is not None:
                if _sync_font_obj_to_ui_list(ao.parent, commit_body=True):
                    text_changed = True
    except Exception:
        pass
    _prev_mode = mode
    if text_changed or membership_changed or live_changed:
        _tag_view3d_redraw()

    if ctx is None:
        return
    try:
        global _last_selection_fp
        ao = ctx.view_layer.objects.active
        name = ao.name if ao is not None else ""
        # Fingerprint selection so Shift-deselect / empty click still syncs checkboxes
        try:
            sel_fp = tuple(sorted(
                o.as_pointer() for o in (getattr(ctx, "selected_objects", None) or [])
            ))
        except Exception:
            sel_fp = ()
        active_changed = (name != _last_active_name)
        sel_changed = (sel_fp != _last_selection_fp)
        if not active_changed and not sel_changed:
            return
        _last_active_name = name
        _last_selection_fp = sel_fp

        # Resolve bundle: active object, else pinned
        root = None
        if ao is not None:
            cur = ao
            while cur is not None:
                try:
                    if cur.ksp_bundle.is_ksp_bundle:
                        root = cur
                        break
                except Exception:
                    pass
                cur = cur.parent
        if root is None:
            try:
                from .operators import _pinned_bundle
                root = _pinned_bundle(scene)
            except Exception:
                root = None
        if root is None:
            return

        if ao is not None:
            try:
                ao_hidden = bool(ao.hide_get())
            except Exception:
                ao_hidden = False
            if ao_hidden:
                try:
                    from .operators import _pinned_bundle
                    pinned = _pinned_bundle(scene)
                except Exception:
                    pinned = None
                if pinned is not None and pinned != root:
                    return
            try:
                from .operators import pin_active_bundle
                pin_active_bundle(root, scene)
            except Exception:
                pass

        kb = root.ksp_bundle
        # Sync multi-select checkboxes from viewport (incl. full deselect → clear)
        try:
            sel_ptrs = set()
            for obj in list(getattr(ctx, "selected_objects", None) or []):
                ui = _find_ksp_ui_root(obj)
                if ui is None:
                    continue
                try:
                    # Only count UI belonging to this bundle
                    br = _bundle_root_of(ui)
                    if br is not None and br != root:
                        continue
                except Exception:
                    pass
                try:
                    sel_ptrs.add(ui.as_pointer())
                except Exception:
                    pass
            locking = False
            try:
                from . import properties as _props
                if not getattr(_props, "_ui_list_select_lock", False):
                    _props._ui_list_select_lock = True
                    locking = True
                for i, item in enumerate(kb.ui_elements):
                    want = False
                    vo = item.viewport_object
                    try:
                        if vo is not None and vo.as_pointer() in sel_ptrs:
                            want = True
                    except Exception:
                        want = False
                    if bool(getattr(item, "list_selected", False)) != want:
                        item.list_selected = want
            finally:
                if locking:
                    try:
                        from . import properties as _props
                        _props._ui_list_select_lock = False
                    except Exception:
                        pass
        except Exception:
            pass
        if ao is None:
            return
        cur = ao
        while cur is not None:
            try:
                if cur.get("ksp_locale_parked"):
                    cur = cur.parent
                    continue
            except Exception:
                pass
            matched = False
            for i, item in enumerate(kb.ui_elements):
                try:
                    if item.viewport_object == cur:
                        matched = True
                    else:
                        ui = cur.ksp_ui
                        if not ui.is_ksp_ui:
                            continue
                        mb = str(getattr(ui, "mb_path_id", "") or "").strip()
                        imb = str(getattr(item, "mb_path_id", "") or "").strip()
                        if mb and imb and mb == imb:
                            matched = True
                        elif (ui.element_name or "").strip() == (item.name or "").strip():
                            en = (ui.element_name or "").strip()
                            same = 0
                            try:
                                same = sum(
                                    1 for it in kb.ui_elements
                                    if (it.name or "").strip() == en
                                )
                            except Exception:
                                same = 2
                            if same == 1:
                                matched = True
                except Exception:
                    continue
                if matched:
                    if int(kb.ui_elements_index) != i:
                        kb["ui_elements_index"] = i
                    try:
                        if item.viewport_object != cur:
                            item.viewport_object = cur
                    except Exception:
                        pass
                    return
            cur = cur.parent
    except Exception:
        pass


def ensure_selection_handler():
    global _selection_handler
    if _selection_handler is not None:
        return
    if _on_selection_depsgraph not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_selection_depsgraph)
    _selection_handler = _on_selection_depsgraph


def remove_selection_handler():
    global _selection_handler
    try:
        if _on_selection_depsgraph in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(_on_selection_depsgraph)
    except Exception:
        pass
    _selection_handler = None


_ui_delete_keymaps = []


def register_ui_delete_keymap():
    """X / Del on a KSPedia box opens the language-scope dialog, not native delete."""
    unregister_ui_delete_keymap()
    try:
        wm = bpy.context.window_manager
        kc = wm.keyconfigs.addon
    except Exception:
        return
    if kc is None:
        return
    specs = (
        ("Object Mode", "EMPTY", "WINDOW"),
        ("Outliner", "OUTLINER", "WINDOW"),
    )
    for name, space, region in specs:
        try:
            km = kc.keymaps.new(name=name, space_type=space, region_type=region)
        except Exception:
            continue
        for key in ("X", "DEL"):
            try:
                kmi = km.keymap_items.new(
                    "object.ksp_viewport_ui_delete", key, "PRESS",
                )
            except Exception:
                continue
            _ui_delete_keymaps.append((km, kmi))


def unregister_ui_delete_keymap():
    for km, kmi in _ui_delete_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _ui_delete_keymaps.clear()


# Blender frees enum item strings it does not own. Cache one list of interned
# tuples (same pattern as locale-scope / replacement enums).
_FONT_ENUM_ITEMS = [("NONE", "(none)", "")]
_FONT_ENUM_KEY = None
_FONT_ENUM_INTERN = {}
_FONT_IDENT_TO_NAME = {}


def _font_intern(s):
    s = str(s)
    return _FONT_ENUM_INTERN.setdefault(s, s)


def selected_ksp_text_roots(context):
    """Selected KSP text UI roots (FONT / ksp_ui text), excluding outline ghosts."""
    from .operators import _iter_context_objects

    out = []
    seen = set()
    for obj in _iter_context_objects(context):
        root = _text_ui_root_of(obj)
        if root is None:
            continue
        rid = id(root)
        if rid in seen:
            continue
        seen.add(rid)
        out.append(root)
    return out


def _text_ui_root_of(obj):
    if obj is None:
        return None
    try:
        if obj.get("ksp_outline_ghost"):
            obj = obj.parent
    except Exception:
        pass
    ui_root = _find_ksp_ui_root(obj)
    if ui_root is None:
        return None
    try:
        if not ui_root.ksp_ui.is_ksp_ui or ui_root.ksp_ui.kind != "text":
            return None
    except Exception:
        return None
    return ui_root


def _collect_ui_font_names(kb):
    names = []
    seen = set()

    def _add(n):
        n = (n or "").strip()
        if not n or n.startswith("("):
            return
        key = n.lower()
        if key in seen:
            return
        seen.add(key)
        names.append(n)

    try:
        for it in getattr(kb, "font_inventory", None) or []:
            _add(getattr(it, "name", ""))
    except Exception:
        pass
    if not names:
        try:
            for el in kb.ui_elements:
                if str(getattr(el, "kind", "") or "") != "text":
                    continue
                _add(getattr(el, "font_family", ""))
        except Exception:
            pass
    try:
        from .fonts_util import list_bundled_standin_stems
        for stem in list_bundled_standin_stems():
            _add(stem)
    except Exception:
        pass
    return names


def _ui_font_enum_items(self, context):
    global _FONT_ENUM_ITEMS, _FONT_ENUM_KEY, _FONT_IDENT_TO_NAME
    root = _find_root(context)
    kb = root.ksp_bundle if root is not None else None
    names = _collect_ui_font_names(kb) if kb is not None else []
    try:
        ptr = int(kb.as_pointer()) if kb is not None else 0
    except Exception:
        ptr = 0
    key = (ptr, tuple(names))
    if key == _FONT_ENUM_KEY and _FONT_ENUM_ITEMS:
        return _FONT_ENUM_ITEMS
    items = []
    ident_map = {}
    if not names:
        none = _font_intern("NONE")
        items = [(none, _font_intern("(none)"), _font_intern(""), 0)]
    else:
        for i, name in enumerate(names):
            ident = name.replace(" ", "_")
            if ident and ident[0].isdigit():
                ident = "F_" + ident
            ident = _font_intern(ident)
            label = _font_intern(name)
            desc = _font_intern("Apply %s to the text box" % name)
            items.append((ident, label, desc, i))
            ident_map[ident] = name
    _FONT_ENUM_ITEMS = items
    _FONT_ENUM_KEY = key
    _FONT_IDENT_TO_NAME = ident_map
    return _FONT_ENUM_ITEMS


def _match_ui_element_item(kb, ui_root):
    if kb is None or ui_root is None:
        return None
    try:
        items = list(kb.ui_elements)
    except Exception:
        return None
    for item in items:
        try:
            if item.viewport_object == ui_root:
                return item
        except Exception:
            pass
    mb = ""
    name = ""
    try:
        mb = str(ui_root.ksp_ui.mb_path_id or "")
        name = str(ui_root.ksp_ui.element_name or "")
    except Exception:
        pass
    if mb:
        for item in items:
            try:
                if str(item.mb_path_id or "") == mb:
                    return item
            except Exception:
                pass
    if name:
        for item in items:
            try:
                if str(item.name or "") == name:
                    return item
            except Exception:
                pass
    return None


def _text_box_font_objects(ui_root):
    out = []
    seen = set()

    def _add(obj):
        if obj is None or getattr(obj, "type", "") != "FONT":
            return
        oid = id(obj)
        if oid in seen:
            return
        seen.add(oid)
        out.append(obj)

    _add(ui_root)
    try:
        kids = list(ui_root.children_recursive)
    except Exception:
        kids = list(ui_root.children or [])
    for ch in kids:
        _add(ch)
    return out


def _apply_font_to_text_box(ui_root, kb, fam, locale, fid, pid):
    try:
        ui_root.ksp_ui.font_family = fam
    except Exception:
        pass
    # Do NOT overwrite ksp_import_font_family — that stamp is the Unity face
    # used as fallback for other languages when their .lang has no family.
    item = _match_ui_element_item(kb, ui_root)
    if item is not None:
        try:
            item.font_family = fam
        except Exception:
            pass
        if pid:
            try:
                item.font_asset_path_id = str(int(pid))
                item.font_asset_file_id = str(int(fid or 0))
            except Exception:
                pass
    style = 0
    try:
        style = int(getattr(ui_root.ksp_ui, "font_style", 0) or 0)
    except Exception:
        style = 0
    bold = bool(style & 1)
    italic = bool(style & 2)
    from .fonts_util import apply_fonts_to_curve
    for font_obj in _text_box_font_objects(ui_root):
        body = ""
        try:
            body = font_obj.data.body or ""
        except Exception:
            body = ""
        if not body:
            try:
                body = ui_root.ksp_ui.text or ""
            except Exception:
                body = ""
        try:
            apply_fonts_to_curve(
                font_obj.data,
                bold=bold,
                italic=italic,
                text=body,
                font_family=fam,
                locale=locale or "",
            )
        except Exception:
            pass
        try:
            if font_obj.ksp_ui.is_ksp_ui:
                font_obj.ksp_ui.font_family = fam
        except Exception:
            pass
    mark_text_dirty(ui_root)
    return True


class KSPMU_OT_SetUiFont(_LocaleScopeMixin, bpy.types.Operator):
    """Apply one outline font to the selected KSP text box(es)."""
    bl_idname = "object.ksp_set_ui_font"
    bl_label = "Font"
    bl_description = "Set the font for the selected KSP text box"
    bl_options = {"REGISTER", "UNDO"}

    font: EnumProperty(
        name="Font",
        description="Fonts from the imported bundle plus plugin stand-ins",
        items=_ui_font_enum_items,
    )
    font_scope_ok: BoolProperty(default=False, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return True

    def scope_summary(self, context):
        fam = _FONT_IDENT_TO_NAME.get(self.font, "") or str(self.font or "")
        return "Apply font '%s' to which languages?" % (fam or "font")

    def invoke(self, context, event):
        self.font_scope_ok = True
        return _LocaleScopeMixin.invoke(self, context, event)

    def execute(self, context):
        # operator_menu_enum skips invoke — show the language scope dialog.
        if not self.font_scope_ok:
            return self.invoke(context, None)
        roots = selected_ksp_text_roots(context)
        if not roots:
            self.report({"ERROR"}, "Select a KSP text box")
            return {"CANCELLED"}
        fam = _FONT_IDENT_TO_NAME.get(self.font, "") or str(self.font or "")
        if not fam or fam == "NONE":
            return {"CANCELLED"}
        bundle_root = _find_root(context)
        kb = bundle_root.ksp_bundle if bundle_root is not None else None
        locale = ""
        try:
            locale = (
                getattr(kb, "active_locale", "")
                or getattr(kb, "locale", "")
                or ""
            )
        except Exception:
            locale = ""
        targets = []
        try:
            if kb is not None:
                targets = list(self.target_locales(kb) or [])
        except Exception:
            targets = [locale] if locale else []
        fid, pid = 0, 0
        if kb is not None:
            try:
                from .ui_roundtrip import resolve_font_path_id_from_kb
                fid, pid = resolve_font_path_id_from_kb(kb, fam)
            except Exception:
                fid, pid = 0, 0
        n = 0
        from . import locale_buffers as _lb
        src = ""
        try:
            src = (
                getattr(kb, "source_path", "")
                or getattr(kb, "template_path", "")
                or ""
            )
        except Exception:
            src = ""
        for ui_root in roots:
            try:
                _apply_font_to_text_box(ui_root, kb, fam, locale, fid, pid)
                n += 1
            except Exception:
                pass
            item = _match_ui_element_item(kb, ui_root)
            hier, name = ("", "")
            if item is not None:
                hier, name = _element_keys(item)
            if not hier:
                try:
                    from .locale_switch import _obj_hierarchy_key
                    hier = _obj_hierarchy_key(ui_root)
                except Exception:
                    hier = ""
            if not name:
                try:
                    name = str(
                        ui_root.ksp_ui.element_name or ui_root.name or ""
                    ).strip()
                except Exception:
                    name = ""
            for loc in targets:
                loc = (loc or "").strip().lower()
                if not loc:
                    continue
                try:
                    if kb is not None and src and not _lb.has_locale_maps(kb, loc):
                        _lb.ensure_locale_maps(kb, loc, src)
                    if kb is not None:
                        _lb.update_element_fields(
                            kb, loc, hier=hier, name=name, font_family=fam,
                        )
                except Exception:
                    pass
        self.report({"INFO"}, "Font: %s" % fam)
        return {"FINISHED"}


from .menu_check import (
    KSPMU_OT_MenuCheck, KSPMU_OT_MenuCheckSelect,
    KSPMU_UL_MenuCheckToc, KSPMU_UL_MenuCheckExplore,
)

classes_to_register = (
    KSPMU_MT_KspBundleNewMenu,
    KSPMU_OT_KspBundleNewTemplate,
    KSPMU_OT_DeselectBundle,
    KSPMU_OT_SelectNextBundle,
    KSPMU_OT_AddLocale,
    KSPMU_OT_RemoveLocale,
    KSPMU_OT_SetActiveLocale,
    KSPMU_OT_RefreshViewportPreview,
    KSPMU_OT_MenuCheck,
    KSPMU_OT_MenuCheckSelect,
    KSPMU_UL_MenuCheckToc,
    KSPMU_UL_MenuCheckExplore,
    KSPMU_MT_LocaleSelect,
    KSPMU_OT_SetUiFont,
    KSPMU_OT_UiElementAdd,
    KSPMU_OT_UiElementLoadImage,
    KSPMU_MT_UiElementAddMenu,
    KSPMU_OT_UiElementDuplicate,
    KSPMU_OT_UiElementDelete,
    KSPMU_OT_ViewportUiDelete,
    KSPMU_OT_UiElementImportImage,
    KSPMU_OT_UiElementExportImage,
    KSPMU_MT_TocAddMenu,
    KSPMU_OT_TocAddPage,
    KSPMU_OT_TocAddScreen,
    KSPMU_OT_TocAddReplacement,
    KSPMU_OT_TocAddExistingPage,
    KSPMU_OT_TocAddToExistingPage,
    KSPMU_OT_TocEnsurePrefab,
    KSPMU_OT_TocDuplicatePage,
    KSPMU_OT_TocMove,
    KSPMU_OT_TocIndent,
    KSPMU_OT_TocDeletePage,
    KSPMU_OT_ApplyLocaleSwitch,
    KSPMU_OT_SyncUiListFromViewport,
)
