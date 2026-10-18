# vim:ts=4:et
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

import os

import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from .bundle import KspBundleError
from .deps import ensure_unitypy, last_error
from .import_ksp import import_ksp
from . import viewport


def _find_bundle_root(obj):
    if obj is None:
        return None
    cur = obj
    while cur is not None:
        try:
            if cur.ksp_bundle.is_ksp_bundle:
                return cur
        except Exception:
            pass
        cur = cur.parent
    return None


def _iter_context_objects(context):
    """Yield selected objects including viewport-hidden ones.

    `context.selected_objects` omits hide_set objects, so after
    Select Bundle hides a root, Outliner clicks never appear there —
    but `Object.select_get()` stays True.
    """
    seen = set()
    scene = getattr(context, "scene", None)
    if scene is not None:
        for obj in scene.objects:
            try:
                if not obj.select_get():
                    continue
            except Exception:
                continue
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            yield obj
    ao = None
    try:
        ao = context.view_layer.objects.active
    except Exception:
        ao = None
    if ao is None:
        ao = getattr(context, "active_object", None)
    if ao is not None and id(ao) not in seen:
        yield ao


def _find_bundle_root_from_context(context):
    """Resolve bundle root from selection; prefer currently hidden roots."""
    roots = []
    for obj in _iter_context_objects(context):
        root = _find_bundle_root(obj)
        if root is None:
            continue
        if root not in roots:
            roots.append(root)
    if not roots:
        return None
    for root in roots:
        try:
            if root.hide_get():
                return root
        except Exception:
            pass
    return roots[0]


def import_ksp_op(self, context, filepath, build_viewport, pixel_scale):
    undo = bpy.context.preferences.edit.use_global_undo
    bpy.context.preferences.edit.use_global_undo = False
    try:
        if not ensure_unitypy(False):
            from .deps import ensure_unitypy_or_prompt, need_restart
            if not ensure_unitypy_or_prompt():
                err = last_error() or "unknown"
                lvl = {'WARNING'} if need_restart() else {'ERROR'}
                self.report(lvl, err if need_restart() else ("UnityPy unavailable: %s" % err))
                return {'CANCELLED'}
        collection = context.view_layer.active_layer_collection.collection
        try:
            from .progress_util import progress_bar
            with progress_bar(context, total=100, title="KSP Import"):
                root = import_ksp(
                    collection,
                    filepath,
                    pixel_scale=pixel_scale,
                    build_viewport=build_viewport,
                )
        except KspBundleError as e:
            self.report({'ERROR'}, e.message)
            return {'CANCELLED'}
        for o in context.scene.objects:
            o.select_set(False)
        context.view_layer.objects.active = root
        root.select_set(True)
        root.location = context.scene.cursor.location
        self.report(
            {'INFO'},
            "Imported %s (%s)" % (root.ksp_bundle.bundle_name,
                                  root.ksp_bundle.bundle_kind),
        )
        return {'FINISHED'}
    finally:
        bpy.context.preferences.edit.use_global_undo = undo


class KSPMU_OT_ImportKspBundle(bpy.types.Operator, ImportHelper):
    '''Load a KSP .ksp Unity AssetBundle'''
    bl_idname = "import_object.ksp_bundle"
    bl_label = "Import KSP Bundle (.ksp)"
    bl_description = "Import a KSP .ksp UnityFS AssetBundle (KSPedia UI, etc.)"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ""
    filter_glob: StringProperty(default="*.ksp", options={'HIDDEN'})

    build_viewport: BoolProperty(
        name="Build Viewport",
        description="Create UI preview objects (planes / text)",
        default=True,
    )
    pixel_scale: FloatProperty(
        name="Pixel Scale",
        description="Unity pixel to Blender unit scale",
        default=viewport.DEFAULT_PIXEL_SCALE,
        min=1e-6,
    )

    def execute(self, context):
        return import_ksp_op(
            self,
            context,
            self.filepath,
            self.build_viewport,
            self.pixel_scale,
        )


class KSPMU_OT_ReimportKspBundle(bpy.types.Operator):
    '''Reimport the source .ksp for the active bundle root'''
    bl_idname = "import_object.ksp_bundle_reimport"
    bl_label = "Reimport KSP Bundle"
    bl_options = {'REGISTER', 'UNDO'}

    build_viewport: BoolProperty(name="Build Viewport", default=True)

    @classmethod
    def poll(cls, context):
        return _find_bundle_root_from_context(context) is not None

    def execute(self, context):
        root = _find_bundle_root_from_context(context)
        if root is None:
            self.report({'ERROR'}, "No KSP bundle root")
            return {'CANCELLED'}
        path = root.ksp_bundle.source_path
        if not path:
            self.report({'ERROR'}, "Bundle has no source_path")
            return {'CANCELLED'}
        scale = root.ksp_bundle.pixel_scale or viewport.DEFAULT_PIXEL_SCALE
        # Remove old hierarchy under root's parent collection
        collection = root.users_collection[0] if root.users_collection else \
            context.view_layer.active_layer_collection.collection
        parent = root.parent
        loc = root.location.copy()
        try:
            from .progress_util import progress_bar
            with progress_bar(context, total=100, title="KSP Import"):
                # Delete old tree
                victims = [root] + list(root.children_recursive)
                for o in victims:
                    bpy.data.objects.remove(o, do_unlink=True)
                new_root = import_ksp(
                    collection, path,
                    pixel_scale=scale,
                    build_viewport=self.build_viewport,
                )
        except KspBundleError as e:
            self.report({'ERROR'}, e.message)
            return {'CANCELLED'}
        new_root.parent = parent
        new_root.location = loc
        context.view_layer.objects.active = new_root
        new_root.select_set(True)
        self.report({'INFO'}, "Reimported %s" % path)
        return {'FINISHED'}


class KSPMU_OT_InstallUnityPyPrompt(bpy.types.Operator):
    """Ask before installing UnityPy and Pillow."""
    bl_idname = "import_object.ksp_install_unitypy_prompt"
    bl_label = "Python module required"
    bl_options = {'REGISTER', 'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="Python modules are required (UnityPy, Pillow).")
        col.label(text="Install them?")

    def execute(self, context):
        from .deps import last_error, last_source, need_restart
        ok = ensure_unitypy(True)
        if ok:
            self.report(
                {'INFO'},
                "Installed (%s). Retry the import or export."
                % (last_source() or "ok"),
            )
            return {'FINISHED'}
        err = last_error() or "unknown"
        lvl = {'WARNING'} if need_restart() else {'ERROR'}
        self.report(lvl, err)
        return {'CANCELLED'}


class KSPMU_OT_EnsureUnityPy(bpy.types.Operator):
    '''pip --target into this Blender version scripts/addons/modules'''
    bl_idname = "import_object.ksp_ensure_unitypy"
    bl_label = "Ensure UnityPy"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        from .deps import last_source, last_target, need_restart
        ok = ensure_unitypy(True)
        if ok:
            tgt = last_target()
            msg = "UnityPy ready (%s)" % (last_source() or "ok")
            if tgt:
                msg = "%s → %s" % (msg, tgt)
            self.report({'INFO'}, msg)
            return {'FINISHED'}
        err = last_error() or "unknown"
        self.report({'ERROR'}, "UnityPy unavailable: %s" % err)
        return {'CANCELLED'}


class KSPMU_OT_ApplyUiText(bpy.types.Operator):
    '''Copy edited UI text from properties onto the viewport FONT object'''
    bl_idname = "object.ksp_apply_ui_text"
    bl_label = "Apply UI Text to Viewport"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        try:
            return obj.ksp_ui.is_ksp_ui and obj.ksp_ui.kind == 'text'
        except Exception:
            return False

    def execute(self, context):
        from .tmp_markup import parse_tmp_rich_text, dominant_style
        from .viewport import (
            _prepare_display_body,
            _split_intro_paragraphs,
            _find_para_child,
        )

        obj = context.active_object
        ui = obj.ksp_ui
        text = ui.text or ""  # raw markup
        parsed = parse_tmp_rich_text(text)
        plain = _prepare_display_body(parsed.plain or "")

        def _set_font_body(font_obj, body):
            font_obj.data.body = body or ""
            bold, italic, underline, color, _sz = dominant_style(
                parsed, tuple(ui.color)
            )
            try:
                if font_obj.data.materials:
                    mat = font_obj.data.materials[0]
                    nt = mat.node_tree
                    for n in nt.nodes:
                        if n.type == 'EMISSION':
                            n.inputs["Color"].default_value = (
                                float(color[0]), float(color[1]),
                                float(color[2]), 1.0,
                            )
                from .fonts_util import apply_fonts_to_curve
                apply_fonts_to_curve(font_obj.data, bold=bold, italic=italic)
                font_obj["ksp_text_underline"] = bool(underline)
            except Exception:
                pass

        if obj.type == 'FONT':
            _set_font_body(obj, plain)
        elif any(c.type == 'FONT' for c in obj.children):
            parts = _split_intro_paragraphs(plain)
            as_obj = _find_para_child(obj, "as")
            each_obj = _find_para_child(obj, "each")
            if parts and as_obj is not None and each_obj is not None:
                _set_font_body(as_obj, _prepare_display_body(parts[0]))
                _set_font_body(each_obj, _prepare_display_body(parts[1]))
            elif as_obj is not None:
                _set_font_body(as_obj, plain)
                if each_obj is not None:
                    _set_font_body(each_obj, "")
            else:
                font_kids = [c for c in obj.children if c.type == 'FONT']
                if font_kids:
                    _set_font_body(font_kids[0], plain)
        try:
            obj["ksp_text_display"] = plain
        except Exception:
            pass
        # Also sync matching entry on bundle root
        root = _find_bundle_root(obj)
        if root is not None:
            mb = ui.mb_path_id
            for el in root.ksp_bundle.ui_elements:
                if el.mb_path_id == mb or el.name == ui.element_name:
                    el.text = text
                    break
        self.report({'INFO'}, "Applied UI text")
        return {'FINISHED'}


class KSPMU_OT_ShowKspPage(bpy.types.Operator):
    """Show one multipage wiki tab (hide other page object trees)."""
    bl_idname = "object.ksp_show_page"
    bl_label = "Show KSP Page"
    bl_options = {'REGISTER', 'UNDO'}

    direction: bpy.props.EnumProperty(
        name="Direction",
        items=(
            ('SET', "Set", "Show active_page_index"),
            ('PREV', "Previous", ""),
            ('NEXT', "Next", ""),
        ),
        default='SET',
    )

    def execute(self, context):
        from .import_ksp import iter_page_roots, show_multipage_index

        root = _find_bundle_root_from_context(context)
        if root is None:
            self.report({'ERROR'}, "Select a KSP bundle root")
            return {'CANCELLED'}
        kb = root.ksp_bundle
        if kb.layout_mode != 'multipage' or kb.page_count < 1:
            self.report({'WARNING'}, "Bundle is not multipage")
            return {'CANCELLED'}
        pages = iter_page_roots(root)
        if not pages:
            self.report({'ERROR'}, "No page roots found under bundle")
            return {'CANCELLED'}
        n = len(pages)
        idx = int(kb.active_page_index or 0)
        if self.direction == 'PREV':
            idx = (idx - 1) % n
        elif self.direction == 'NEXT':
            idx = (idx + 1) % n
        idx = max(0, min(idx, n - 1))
        page = show_multipage_index(root, idx)
        name = page.name if page else "?"
        self.report({'INFO'}, "Page %d/%d: %s" % (idx + 1, n, name))
        return {'FINISHED'}


class KSPMU_OT_SelectBundle(bpy.types.Operator):
    """Make the active KSP bundle the only visible one; clear TOC filter."""
    bl_idname = "object.ksp_select_bundle"
    bl_label = "Select Bundle"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from .import_ksp import set_active_bundle, show_multipage_index, _set_hide_tree

        root = _find_bundle_root_from_context(context)
        if root is None:
            self.report({'ERROR'}, "Select a KSP bundle (or any object under it)")
            return {'CANCELLED'}
        # Reveal first — hidden roots are hard to activate as view_layer.active
        try:
            _set_hide_tree(root, False)
        except Exception:
            pass
        set_active_bundle(root, context.scene)
        kb = root.ksp_bundle
        kb.filter_page_object = None
        kb.filter_scope_object = None
        if kb.layout_mode == 'multipage' and kb.page_count:
            show_multipage_index(root, int(kb.active_page_index or 0))
            # After show, clear folder scope so lists show whole active bundle
            kb.filter_scope_object = None
            kb.filter_page_object = None
        for o in context.scene.objects:
            o.select_set(False)
        context.view_layer.objects.active = root
        root.select_set(True)
        self.report({'INFO'}, "Active bundle: %s" % (kb.bundle_name or root.name))
        return {'FINISHED'}


class KSPMU_OT_DeleteBundle(bpy.types.Operator):
    """Delete the active KSP bundle hierarchy (and empty import collections)."""
    bl_idname = "object.ksp_delete_bundle"
    bl_label = "Delete Bundle"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _find_bundle_root_from_context(context) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        root = _find_bundle_root_from_context(context)
        if root is None:
            self.report({'ERROR'}, "Select a KSP bundle (or any object under it)")
            return {'CANCELLED'}
        name = ""
        try:
            name = root.ksp_bundle.bundle_name or root.name
        except Exception:
            name = root.name
        try:
            from . import source_embed
            source_embed.clear_embedded_source(root.ksp_bundle)
        except Exception:
            pass
        cols = list(root.users_collection)
        victims = [root] + list(root.children_recursive)
        for o in victims:
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except Exception:
                pass
        # Drop empty collections left by this import (bundle / _UI / pages)
        for col in cols:
            try:
                if col is None or col == context.scene.collection:
                    continue
                if len(col.objects) or len(col.children):
                    continue
                bpy.data.collections.remove(col)
            except Exception:
                pass
        self.report({'INFO'}, "Deleted bundle: %s" % name)
        return {'FINISHED'}


class KSPMU_OT_ApplyDisplayTitle(bpy.types.Operator):
    """Write edited display title back into the KSPedia XML TextAsset."""
    bl_idname = "object.ksp_apply_display_title"
    bl_label = "Apply Display Title to XML"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        root = _find_bundle_root_from_context(context)
        if root is None:
            return False
        kb = root.ksp_bundle
        return bool(kb.toc_nodes) and 0 <= kb.toc_nodes_index < len(kb.toc_nodes)

    def execute(self, context):
        from . import kspedia_index

        root = _find_bundle_root_from_context(context)
        kb = root.ksp_bundle
        node = kb.toc_nodes[kb.toc_nodes_index]
        screen = node.screen or node.name
        # Prefer raw XML title (#autoLOC_*) when set; else display title
        title = (getattr(node, "title_raw", "") or "").strip() or (
            node.title or ""
        ).strip()
        if not screen or not title:
            self.report({'ERROR'}, "Need screen id + title / title_raw")
            return {'CANCELLED'}
        xml_name = kb.kspedia_xml_asset
        target = None
        for ta in kb.text_assets:
            if xml_name and ta.name == xml_name:
                target = ta
                break
            if target is None and "kspedia" in (ta.name or "").lower() and \
                    "bundle" not in (ta.name or "").lower():
                target = ta
        if target is None:
            self.report({'ERROR'}, "No KSPedia XML TextAsset on bundle")
            return {'CANCELLED'}
        src = ""
        if target.text_block:
            src = target.text_block.as_string()
        if not src:
            src = target.text or ""
        new_xml = kspedia_index.set_screen_title_in_xml(src, screen, title)
        try:
            bname = (getattr(node, "bundle_name", "") or "").strip()
            apath = (getattr(node, "asset_path", "") or "").strip()
            if bname or apath:
                new_xml = kspedia_index.set_screen_meta_in_xml(
                    new_xml,
                    screen,
                    bundle_name=bname or None,
                    asset_path=apath or None,
                )
        except Exception:
            pass
        target.text = new_xml
        if target.text_block:
            target.text_block.clear()
            target.text_block.write(new_xml)
        if node.page_object:
            try:
                node.page_object["ksp_display_title"] = title
            except Exception:
                pass
        try:
            kb.display_title = title
        except Exception:
            pass
        self.report({'INFO'}, "Updated title for %s → %s" % (screen, title))
        return {'FINISHED'}


class KSPMU_OT_EmbedSource(bpy.types.Operator):
    '''Copy the Source .ksp into this .blend for portable Export'''
    bl_idname = "object.ksp_embed_source"
    bl_label = "Embed Source .ksp"
    bl_description = (
        "Store the source .ksp in this session (save the .blend to keep it). "
        "Export then works without the original file on disk"
    )
    # No UNDO: snapshotting a multi-MB Text datablock freezes Blender,
    # especially when the .blend has never been saved (memory undo).
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        root = _find_bundle_root_from_context(context) or _find_bundle_root(
            context.active_object
        )
        if root is None:
            return False
        kb = root.ksp_bundle
        src = (getattr(kb, "source_path", "") or "").strip()
        return bool(src) and os.path.isfile(src)

    def execute(self, context):
        from . import source_embed

        root = _find_bundle_root_from_context(context) or _find_bundle_root(
            context.active_object
        )
        if root is None:
            self.report({'ERROR'}, "Select a KSP bundle root")
            return {'CANCELLED'}
        kb = root.ksp_bundle
        src = (kb.source_path or "").strip()
        if not src or not os.path.isfile(src):
            self.report({'ERROR'}, "Source .ksp path not found on disk")
            return {'CANCELLED'}
        updating = source_embed.has_embedded_source(kb)
        try:
            from .progress_util import progress_bar, tick
            with progress_bar(context, total=100, title="KSP Embed"):
                tick(10, text="Reading .ksp…", force=True)
                ok = source_embed.embed_source_from_path(kb, src, root=root)
                tick(100, text="Done", force=True)
        except Exception:
            ok = source_embed.embed_source_from_path(kb, src, root=root)
        if not ok:
            self.report({'ERROR'}, "Failed to embed source .ksp")
            return {'CANCELLED'}
        size = os.path.getsize(src)
        saved = False
        try:
            saved = bool(bpy.data.is_saved and (bpy.data.filepath or "").strip())
        except Exception:
            saved = False
        verb = "Updated" if updating else "Embedded"
        mb = size / (1024.0 * 1024.0)
        if saved:
            self.report(
                {'INFO'},
                "%s %s (%.1f MB) into .blend" % (verb, os.path.basename(src), mb),
            )
        else:
            self.report(
                {'WARNING'},
                "%s %s (%.1f MB) in RAM — save the .blend to keep it"
                % (verb, os.path.basename(src), mb),
            )
        return {'FINISHED'}


class KSPMU_OT_UpdateSourceEmbed(bpy.types.Operator):
    '''Refresh the embedded template from the current Source path'''
    bl_idname = "object.ksp_update_source_embed"
    bl_label = "Update Embedded Source"
    bl_description = "Embed source .ksp in this session (save .blend to keep it)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return KSPMU_OT_EmbedSource.poll(context)

    def execute(self, context):
        return KSPMU_OT_EmbedSource.execute(self, context)


def import_ksp_menu_func(self, context):
    self.layout.operator(
        KSPMU_OT_ImportKspBundle.bl_idname, text="KSP Bundle (.ksp / .lang)"
    )


classes_to_register = (
    KSPMU_OT_ImportKspBundle,
    KSPMU_OT_ReimportKspBundle,
    KSPMU_OT_EnsureUnityPy,
    KSPMU_OT_InstallUnityPyPrompt,
    KSPMU_OT_ApplyUiText,
    KSPMU_OT_ShowKspPage,
    KSPMU_OT_SelectBundle,
    KSPMU_OT_DeleteBundle,
    KSPMU_OT_ApplyDisplayTitle,
    KSPMU_OT_EmbedSource,
    KSPMU_OT_UpdateSourceEmbed,
)

menus_to_register = (
    (bpy.types.TOPBAR_MT_file_import, import_ksp_menu_func),
)
