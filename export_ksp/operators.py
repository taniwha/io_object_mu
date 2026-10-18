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
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from ..import_ksp.bundle import KspBundleError
from .export_ksp import export_ksp, find_bundle_root, _flush_text_edits_for_export
from ..import_ksp.operators import _find_bundle_root_from_context


def _dll_source_path():
    return os.path.join(
        os.path.dirname(__file__),
        "KSPModFileLocalizer.dll",
    )


def _write_localization_cfg(folder, *, path_val, filename, default_locale):
    """Create localization.cfg only when missing (never overwrite user edits)."""
    cfg = os.path.join(folder, "localization.cfg")
    if os.path.isfile(cfg):
        return False
    body = (
        "KSPediaLocalization\n"
        "{\n"
        "    path = %s\n"
        "    filename = %s\n"
        "    default = %s\n"
        "}\n"
        % (path_val, filename, default_locale)
    )
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(body)
    return True


def _read_localization_cfg(folder):
    cfg = os.path.join(folder, "localization.cfg")
    if not os.path.isfile(cfg):
        return None
    try:
        from ..import_ksp import kspedia_index
        return kspedia_index.parse_localization_cfg(cfg)
    except Exception:
        return None


def _gamedata_path_for_export(folder, fallback="GameData/KSPedia/"):
    """Build path= value: GameData/<dirs under GameData>/ or GameData/<foldername>/."""
    folder = os.path.abspath(folder or "").replace("\\", "/")
    parts = [p for p in folder.split("/") if p]
    for i, part in enumerate(parts):
        if part.lower() == "gamedata":
            rest = parts[i:]
            return "/".join(rest) + ("/" if rest else "")
    name = os.path.basename(folder.rstrip("/")) or "KSPedia"
    return "GameData/%s/" % name


def _bundle_filename_base(kb, main_path):
    import re
    base = (getattr(kb, "locale_base", "") or getattr(kb, "bundle_name", "") or "").strip()
    if not base:
        stem = os.path.splitext(os.path.basename(main_path))[0]
        m = re.match(r"^(?P<base>.+?)_(?P<loc>[a-z]{2}(?:-[a-z]{2})?)$", stem, re.I)
        base = m.group("base") if m else stem
    return base


def _filename_base_from_filepath(filepath):
    """Basename the user typed in the export dialog (locale suffix stripped)."""
    import re
    stem = os.path.splitext(os.path.basename(filepath or ""))[0].strip()
    if not stem:
        return ""
    m = re.match(r"^(?P<base>.+?)_(?P<loc>[a-z]{2}(?:-[a-z]{2})?)$", stem, re.I)
    return (m.group("base") if m else stem).strip()


def _locale_from_filepath(filepath):
    """Locale suffix from ``name_en-us.ksp`` / ``name_zh-cn.lang``, else ``\"\"``."""
    import re
    stem = os.path.splitext(os.path.basename(filepath or ""))[0].strip()
    if not stem:
        return ""
    m = re.match(r"^(?P<base>.+?)_(?P<loc>[a-z]{2}(?:-[a-z]{2})?)$", stem, re.I)
    return (m.group("loc").lower() if m else "")


def _update_localization_cfg_default(folder, default_locale):
    """Rewrite ``default =`` when an existing cfg disagrees with the main .ksp."""
    loc = (default_locale or "").strip().lower()
    if not folder or not loc:
        return False
    cfg = os.path.join(folder, "localization.cfg")
    if not os.path.isfile(cfg):
        return False
    try:
        with open(cfg, "r", encoding="utf-8") as f:
            body = f.read()
    except Exception:
        return False
    import re
    m = re.search(r"(?im)^\s*default\s*=\s*([^\s#]+)", body)
    cur = (m.group(1).strip().lower() if m else "")
    if cur == loc:
        return False
    if m:
        new_body, n = re.subn(
            r"(?im)^(\s*default\s*=\s*)([^\s#]+)",
            r"\g<1>%s" % loc,
            body,
            count=1,
        )
        if n < 1:
            return False
    else:
        new_body = body.rstrip() + "\n    default = %s\n" % loc
    try:
        with open(cfg, "w", encoding="utf-8") as f:
            f.write(new_body)
    except Exception:
        return False
    return True


def _purge_removed_locale_files(folder, filename_base, pending, keep_locales, default_locale):
    """Delete .lang/.ksp siblings for languages removed in the UI (Export time only)."""
    if not folder or not filename_base or not pending:
        return []
    keep = set((x or "").strip().lower() for x in (keep_locales or []) if x)
    default = (default_locale or "").strip().lower()
    if default:
        keep.add(default)
    removed = []
    for loc in pending:
        loc = (loc or "").strip().lower()
        if not loc or loc in keep:
            continue
        for ext in (".lang", ".ksp"):
            path = os.path.join(folder, "%s_%s%s" % (filename_base, loc, ext))
            if not os.path.isfile(path):
                continue
            # Never delete the default main .ksp
            if ext == ".ksp" and loc == default:
                continue
            try:
                os.remove(path)
                removed.append(path)
            except Exception as e:
                print("WARNING: could not delete removed locale file %s: %s" % (path, e))
    return removed


def _apply_locale_for_export(root, kb, locale, source_path, *, update_viewport=False):
    """Push RAM (or disk) texts for locale into ui_elements before patching.

    Default leaves the viewport alone — switching every .lang through
    ``apply_text_map_to_viewport`` during export left Chinese texts in the
    UI list, hid overlays via presence, and only Ctrl+Z restored the scene.

    Also applies that language's TOC titles into ``kb.toc_nodes`` + KSPedia XML
    so sibling ``.lang`` files keep Containersystem / Korridore / … instead of
    being overwritten with the English snapshot from the main .ksp export.
    """
    from ..import_ksp import locale_buffers

    maps = locale_buffers.ensure_locale_maps(kb, locale, source_path)
    if maps:
        locale_buffers.apply_maps_to_ui_elements(kb, maps, locale=locale)
        # Drives which rows export_ksp is allowed to patch for this language.
        try:
            locale_buffers.sync_missing_flags(kb, maps, locale=locale)
        except Exception:
            pass

    # TOC / Categories <Title> per language
    try:
        from ..import_ksp import properties as _props
        from ..import_ksp import kspedia_index
        loc = (locale or "").strip().lower()
        # Seed from .lang XML when RAM titles are missing/empty
        titles = _props._locale_titles(kb, loc)
        if not titles and source_path:
            try:
                seeded = locale_buffers.seed_from_disk(kb, loc, source_path)
            except Exception:
                seeded = None
            titles = _props._locale_titles(kb, loc)
        _props.apply_locale_toc_titles(kb, loc)
        kspedia_index.sync_bundle_toc_xml(kb)
    except Exception as ex:
        try:
            print("WARNING: locale TOC titles for export %s: %s" % (locale, ex))
        except Exception:
            pass

    if not update_viewport:
        return
    if not maps:
        return
    try:
        from ..import_ksp.locale_switch import apply_text_map_to_viewport
        apply_text_map_to_viewport(
            root,
            maps,
            locale=locale,
            pixel_scale=float(getattr(kb, "pixel_scale", 0.001) or 0.001),
        )
    except Exception:
        pass


def _restore_locale_after_export(root, kb, locale, source_path):
    """Put ui_elements / locale tags back to what the user was viewing.

    Must not assign ``kb.active_locale`` via RNA — that runs the live locale
    switch (viewport + TOC title refresh) and used to rewrite the selected
    page/folder Title to the bundle display name after Export.
    """
    from ..import_ksp import locale_buffers

    loc = (locale or "").strip().lower()
    if not loc:
        return
    try:
        _apply_locale_for_export(root, kb, loc, source_path, update_viewport=False)
    except Exception:
        pass
    try:
        kb["active_locale"] = loc
    except Exception:
        try:
            kb.active_locale = loc
        except Exception:
            pass
    try:
        locale_buffers.set_prev_locale(kb, loc)
    except Exception:
        pass


def _ensure_viewport_locale(root, kb, loc, source_path, *, pack_default=""):
    """Live-switch the viewport to ``loc`` without changing the pack default.

    Export safeguard: the main ``.ksp`` must be written from the default
    (English) language. Restoring after export uses the same path so the
    Locale dropdown and viewport stay in sync.
    """
    loc = (loc or "").strip().lower()
    if not loc or root is None or kb is None:
        return False
    cur = (getattr(kb, "active_locale", "") or "").strip().lower()
    if cur == loc:
        return False
    try:
        kb.active_locale = loc
    except Exception:
        try:
            from ..import_ksp import locale_buffers
            locale_buffers.set_live_sync_lock(True)
            locale_buffers.park_outgoing_locale(kb, root, loc)
        except Exception:
            pass
        try:
            _apply_locale_for_export(
                root, kb, loc, source_path, update_viewport=True,
            )
        except Exception:
            pass
        try:
            kb["active_locale"] = loc
        except Exception:
            pass
        try:
            from ..import_ksp import locale_buffers
            locale_buffers.set_prev_locale(kb, loc)
        except Exception:
            pass
    pack = (pack_default or "").strip().lower()
    if pack:
        try:
            kb.locale = pack
        except Exception:
            pass
    return True


def _export_locale_siblings(
    root,
    main_path,
    locales,
    default_locale,
    filename_base,
    maps_source=None,
    restore_locale=None,
    restore=True,
):
    """Write name_<locale>.lang for each extra language using that locale's RAM texts.

    Template is the main .ksp (keeps Font assets like PlanetaryBaseInc).
    ``maps_source`` is the pre-export path used to load/seed .lang RAM maps —
    never the freshly written main_path (that folder has no sibling .lang yet).
    """
    from ..import_ksp.locale_switch import path_for_locale
    from ..import_ksp.progress_util import tick, tick_items

    folder = os.path.dirname(os.path.abspath(main_path))
    base = filename_base or _bundle_filename_base(root.ksp_bundle, main_path)
    written = []
    kb = root.ksp_bundle
    src = maps_source or kb.source_path or main_path
    view_loc = (restore_locale or getattr(kb, "active_locale", "") or default_locale or "").lower()

    extra_locs = []
    for loc in locales:
        loc = (loc or "").strip().lower()
        if not loc or loc == default_locale:
            continue
        extra_locs.append(loc)

    n_extra = max(len(extra_locs), 1)
    for i, loc in enumerate(extra_locs):
        tick_items(
            i, n_extra, 74, 96,
            text="Writing .lang %s (%d/%d)…" % (loc, i + 1, n_extra),
            every=1,
            force=True,
        )
        out = os.path.join(folder, "%s_%s.lang" % (base, loc))
        # Prefer existing .lang beside maps_source; else main .ksp (fonts stay)
        template = path_for_locale(src, loc)
        if not template or not os.path.isfile(template):
            template = main_path
        try:
            _apply_locale_for_export(root, kb, loc, src, update_viewport=False)
            export_ksp(
                root,
                out,
                template_path=template,
                prefer_list_text=True,
                sync_from_viewport=False,
                set_source_path=False,
                export_locale=loc,
            )
            written.append(out)
        except Exception as e:
            print("WARNING: locale export %s failed: %s" % (loc, e))

    tick(97, text="Restoring viewport locale…")
    if restore:
        _restore_locale_after_export(root, kb, view_loc, src)
    return written


class KSPMU_OT_ExportKspBundle(bpy.types.Operator, ExportHelper):
    '''Export edited KSP .ksp AssetBundle'''
    bl_idname = "export_object.ksp_bundle"
    bl_label = "Export KSP Bundle (.ksp)"
    bl_description = "Patch and write a .ksp UnityFS AssetBundle"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".ksp"
    filter_glob: StringProperty(default="*.ksp", options={'HIDDEN'})
    gamedata_path: StringProperty(
        name="localization.cfg path=",
        description="Value for path = in localization.cfg",
        default="GameData/KSPedia/",
    )
    copy_localizer_dll: BoolProperty(
        name="Copy KSPModFileLocalizer.dll to GameData",
        description="Ask/copy the language loader DLL next to the export folder's GameData",
        default=False,
    )

    def invoke(self, context, event):
        root = _find_bundle_root_from_context(context) or find_bundle_root(context.active_object)
        if root is not None:
            kb = root.ksp_bundle
            # Commit Edit Text / dirty FONT bodies *before* the file dialog —
            # opening ExportHelper often leaves Edit Text without our mode hook.
            try:
                _flush_text_edits_for_export(root, kb, context)
            except Exception:
                pass
            if kb.source_path:
                self.filepath = kb.source_path
            else:
                base = (kb.locale_base or kb.bundle_name or "kspedia").strip()
                default = (kb.locale or "en-us").lower()
                locs = [
                    x.strip().lower()
                    for x in (kb.available_locales or "").split(",")
                    if x.strip()
                ]
                # Only suffix _<lang> when extra languages exist (.lang siblings).
                if len(set(locs)) > 1:
                    self.filepath = "%s_%s.ksp" % (base, default)
                else:
                    self.filepath = "%s.ksp" % base
            if getattr(kb, "export_gamedata_path", ""):
                self.gamedata_path = kb.export_gamedata_path
        return ExportHelper.invoke(self, context, event)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "gamedata_path")
        layout.prop(self, "copy_localizer_dll")
        layout.label(text="Multi-lang → .lang + localization.cfg (if missing)", icon='INFO')
        root = _find_bundle_root_from_context(context) or find_bundle_root(
            context.active_object
        )
        if root is not None:
            try:
                from ..import_ksp import source_embed
                kb = root.ksp_bundle
                layout.label(
                    text="Template: %s" % source_embed.source_display_label(kb),
                    icon='PACKAGE' if source_embed.has_embedded_source(kb) else 'FILE',
                )
            except Exception:
                pass

    def execute(self, context):
        from ..import_ksp.progress_util import progress_bar, tick

        root = _find_bundle_root_from_context(context) or find_bundle_root(context.active_object)
        if root is None:
            self.report({'ERROR'}, "Select a KSP bundle root object")
            return {'CANCELLED'}
        kb = root.ksp_bundle
        # Guard: never overwrite plugin sample assets
        try:
            samples = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "import_ksp", "samples")
            )
            dest = os.path.abspath(self.filepath)
            if dest.startswith(samples + os.sep) or dest.startswith(samples + "/"):
                self.report({'ERROR'}, "Cannot overwrite plugin sample templates — pick another folder")
                return {'CANCELLED'}
        except Exception:
            pass

        with progress_bar(context, total=100, title="KSP Export"):
            from ..import_ksp import locale_buffers

            # Flush Edit Text / panel text into ksp_ui before capturing RAM maps.
            tick(2, text="Flushing text edits…", force=True)
            try:
                _flush_text_edits_for_export(root, kb, context)
            except Exception:
                pass

            # Keep KSPedia Categories + Screen catalog in sync (duplicated /
            # grafted pages need a flat <Screen Name> entry or the game hides them).
            try:
                from ..import_ksp import kspedia_index
                kspedia_index.sync_bundle_toc_xml(kb)
            except Exception:
                pass

            # Capture live edits for the currently viewed locale into RAM
            active_now = (getattr(kb, "active_locale", "") or "").lower()
            try:
                if active_now:
                    locale_buffers.capture_current(kb, root, active_now)
            except Exception:
                pass

            folder = os.path.dirname(os.path.abspath(self.filepath)) or os.getcwd()
            # Prefer the name typed in the file dialog over stale locale_base/bundle_name.
            filename = (
                _filename_base_from_filepath(self.filepath)
                or _bundle_filename_base(kb, self.filepath)
            )
            try:
                kb.locale_base = filename
            except Exception:
                pass

            # Default language for the main .ksp:
            # 1) locale suffix on the chosen filepath (planetarybaseinc_en-us.ksp)
            # 2) else localization.cfg default=
            # 3) else kb.locale / en-us
            # Stale cfg default=es-es must NOT redirect an explicit *_en-us.ksp
            # export — that left the en-us file byte-identical while writing es-es.
            info = _read_localization_cfg(folder)
            file_loc = _locale_from_filepath(self.filepath)
            if file_loc:
                default = file_loc
            elif info is not None and (info.default or "").strip():
                default = info.default.strip().lower()
            else:
                default = (kb.locale or "en-us").lower()
            try:
                kb.locale = default
            except Exception:
                pass
            if info is not None and info.filename and not filename:
                try:
                    kb.locale_base = info.filename
                    filename = info.filename
                except Exception:
                    pass

            locs = [
                x.strip().lower()
                for x in (kb.available_locales or "").split(",")
                if x.strip()
            ]
            if default not in locs:
                locs = sorted(set(locs + [default]))
                kb.available_locales = ",".join(locs)
            multi_lang = len(set(locs)) > 1

            # PBS / multi-lang → {filename}_{default}.ksp; solo packs stay unsuffixed.
            # Honour the exact dialog path when it already matches that pattern.
            if multi_lang:
                path = os.path.join(folder, "%s_%s.ksp" % (filename, default))
                try:
                    chosen = os.path.abspath(self.filepath)
                    if (
                        file_loc == default
                        and chosen.lower().endswith(".ksp")
                        and os.path.normcase(os.path.dirname(chosen))
                        == os.path.normcase(folder)
                    ):
                        path = chosen
                except Exception:
                    pass
            else:
                path = os.path.join(folder, "%s.ksp" % filename)
            path_val = (self.gamedata_path or "").strip()
            if not path_val or path_val == "GameData/KSPedia/":
                path_val = _gamedata_path_for_export(folder, path_val)

            # Export default locale texts into the .ksp
            maps_source = kb.source_path or path
            # Safety: after the filename is chosen, the main .ksp must be
            # written from the default (English) viewport — never from a
            # RAM-only swap of a non-default language.
            switched_locale = False
            if active_now and active_now != default:
                tick(6, text="Switching to %s for export…" % default, force=True)
                switched_locale = _ensure_viewport_locale(
                    root, kb, default, maps_source, pack_default=default,
                )
            # Flush Edit Text / list edits into ksp_ui and export from the live
            # viewport. Do NOT capture→apply_maps first — that rewrote
            # ui_elements from a stale ksp_ui stamp and the .ksp was saved as
            # a byte-identical copy of the source.
            try:
                tick(8, text="Writing main .ksp…", force=True)
                try:
                    maps = locale_buffers.get_maps(kb, default)
                    if maps is None:
                        maps = locale_buffers.ensure_locale_maps(
                            kb, default, maps_source,
                        )
                    if maps:
                        locale_buffers.apply_maps_to_ui_elements(
                            kb, maps, touch_viewport=False,
                        )
                        locale_buffers.sync_missing_flags(kb, maps)
                except Exception:
                    pass
                try:
                    _flush_text_edits_for_export(root, kb, context)
                except Exception:
                    pass
                path = export_ksp(
                    root,
                    path,
                    prefer_list_text=False,
                    sync_from_viewport=True,
                    set_source_path=True,
                    progress_start=8,
                    progress_end=70,
                    export_locale=default,
                )
            except KspBundleError as e:
                self.report({'ERROR'}, e.message)
                return {'CANCELLED'}
            except Exception as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}

            try:
                kb.is_sample_template = False
                kb.source_path = path
                kb.export_gamedata_path = path_val
            except Exception:
                pass

            extra = []
            if multi_lang:
                tick(72, text="Writing localization.cfg…")
                if _write_localization_cfg(
                    folder, path_val=path_val, filename=filename, default_locale=default,
                ):
                    self.report({'INFO'}, "Created localization.cfg (default=%s)" % default)
                elif _update_localization_cfg_default(folder, default):
                    self.report(
                        {'INFO'},
                        "Updated localization.cfg default=%s" % default,
                    )
                extra = _export_locale_siblings(
                    root,
                    path,
                    locs,
                    default,
                    filename,
                    maps_source=maps_source,
                    restore_locale=active_now or default,
                    restore=not switched_locale,
                )
                if self.copy_localizer_dll:
                    dll = _dll_source_path()
                    # Walk up looking for GameData; else put next to export
                    target_dir = folder
                    cur = folder
                    for _ in range(6):
                        gd = os.path.join(cur, "GameData")
                        if os.path.isdir(gd):
                            target_dir = gd
                            break
                        parent = os.path.dirname(cur)
                        if parent == cur:
                            break
                        cur = parent
                    if os.path.isfile(dll):
                        try:
                            dest_dll = os.path.join(target_dir, "KSPModFileLocalizer.dll")
                            if not os.path.isfile(dest_dll):
                                import shutil
                                shutil.copy2(dll, dest_dll)
                                self.report({'INFO'}, "Copied KSPModFileLocalizer.dll → %s" % target_dir)
                        except Exception as e:
                            self.report({'WARNING'}, "DLL copy failed: %s" % e)
            else:
                # Solo pack still swapped ui_elements to default for the write.
                if not switched_locale:
                    _restore_locale_after_export(
                        root, kb, active_now or default, maps_source
                    )

            if switched_locale and active_now:
                tick(98, text="Restoring locale %s…" % active_now)
                _ensure_viewport_locale(
                    root, kb, active_now, maps_source, pack_default=default,
                )

            # Disk delete for languages removed in the UI (deferred until Export).
            try:
                pending = [
                    x.strip().lower()
                    for x in (getattr(kb, "pending_removed_locales", "") or "").split(",")
                    if x.strip()
                ]
                purged = _purge_removed_locale_files(
                    folder, filename, pending, locs, default,
                )
                if purged:
                    self.report(
                        {'INFO'},
                        "Deleted %d removed locale file(s)" % len(purged),
                    )
                kb.pending_removed_locales = ""
            except Exception:
                pass

            tick(100, text="Export complete", force=True)

        msg = "Exported %s" % path
        if extra:
            msg += " + %d .lang" % len(extra)
        self.report({'INFO'}, msg)
        return {'FINISHED'}


class KSPMU_OT_KspBundleNew(bpy.types.Operator):
    '''Legacy id — opens the New sample menu'''
    bl_idname = "object.ksp_bundle_new"
    bl_label = "New KSP Bundle"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return bpy.ops.wm.call_menu(name="KSPMU_MT_ksp_bundle_new")

    def execute(self, context):
        return bpy.ops.object.ksp_bundle_new_template(template='KSPEDIA')


class KSPMU_OT_KspReplaceTexture(bpy.types.Operator, ImportHelper):
    '''Replace the selected bundle texture from an image file'''
    bl_idname = "object.ksp_replace_texture"
    bl_label = "Replace KSP Texture"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".png"
    filter_glob: StringProperty(
        default="*.png;*.tga;*.jpg;*.jpeg", options={'HIDDEN'}
    )

    @classmethod
    def poll(cls, context):
        root = _find_bundle_root_from_context(context) or find_bundle_root(context.active_object)
        if root is None:
            return False
        kb = root.ksp_bundle
        return bool(kb.textures) and 0 <= kb.textures_index < len(kb.textures)

    def execute(self, context):
        root = _find_bundle_root_from_context(context) or find_bundle_root(context.active_object)
        kb = root.ksp_bundle
        item = kb.textures[kb.textures_index]
        try:
            img = bpy.data.images.load(self.filepath, check_existing=True)
        except Exception as e:
            self.report({'ERROR'}, "Failed to load image: %s" % e)
            return {'CANCELLED'}
        try:
            img.pack()
        except Exception:
            pass
        # Fit into existing Unity texture canvas (never change stock KSPedia size).
        try:
            tw = int(getattr(item, "width", 0) or 0)
            th = int(getattr(item, "height", 0) or 0)
        except Exception:
            tw = th = 0
        if tw > 0 and th > 0:
            try:
                from ..import_ksp import viewport as _vp
                fitted = _vp.fit_blender_image_to_canvas(img, tw, th)
                if fitted is not None:
                    img = fitted
            except Exception:
                pass
        item.image = img
        try:
            item.dirty = True
        except Exception:
            pass
        try:
            # Clear hash so export always rewrites even if dirty is lost.
            item.content_hash = ""
        except Exception:
            pass
        # Keep item.width/height as Unity size; do not overwrite with source PNG.
        self.report(
            {'INFO'},
            "Replaced texture %s (canvas %sx%s)"
            % (item.name, getattr(item, "width", "?"), getattr(item, "height", "?")),
        )
        return {'FINISHED'}



class KSPMU_OT_KspRemoveTexture(bpy.types.Operator):
    """Remove the selected texture from the Blender list; purge on export if unused."""
    bl_idname = "object.ksp_remove_texture"
    bl_label = "Remove KSP Texture"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        root = _find_bundle_root_from_context(context) or find_bundle_root(
            context.active_object
        )
        if root is None:
            return False
        kb = root.ksp_bundle
        return bool(kb.textures) and 0 <= kb.textures_index < len(kb.textures)

    def execute(self, context):
        root = _find_bundle_root_from_context(context) or find_bundle_root(
            context.active_object
        )
        kb = root.ksp_bundle
        idx = int(kb.textures_index)
        item = kb.textures[idx]
        try:
            pid = int(getattr(item, "path_id", 0) or 0)
        except Exception:
            pid = 0
        users = []
        for el in list(kb.ui_elements):
            try:
                if bool(getattr(el, "missing_in_locale", False)):
                    continue
            except Exception:
                pass
            try:
                tpid = int(getattr(el, "texture_path_id", 0) or 0)
            except Exception:
                tpid = 0
            if pid and tpid == pid:
                users.append(getattr(el, "name", "") or "?")
        if users:
            self.report(
                {"ERROR"},
                "Texture still used by UI: %s — delete/retarget those first"
                % ", ".join(users[:5]),
            )
            return {"CANCELLED"}
        name = getattr(item, "name", "") or str(pid)
        kb.textures.remove(idx)
        try:
            kb.textures_index = max(0, min(idx, len(kb.textures) - 1))
        except Exception:
            pass
        if pid:
            pending = []
            try:
                raw = str(getattr(kb, "pending_remove_textures", "") or "")
            except Exception:
                raw = ""
            for part in raw.replace(";", ",").split(","):
                part = part.strip()
                if part:
                    pending.append(part)
            spid = str(pid)
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
        self.report(
            {"INFO"},
            "Removed '%s' from list (export drops it if unreferenced)" % name,
        )
        return {"FINISHED"}


class KSPMU_OT_KspEditTextAsset(bpy.types.Operator):
    '''Copy Text datablock contents into the selected text asset entry'''
    bl_idname = "object.ksp_edit_text_asset"
    bl_label = "Pull Text Asset from Block"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        root = _find_bundle_root_from_context(context) or find_bundle_root(context.active_object)
        if root is None:
            return False
        kb = root.ksp_bundle
        return (
            bool(kb.text_assets)
            and 0 <= kb.text_assets_index < len(kb.text_assets)
        )

    def execute(self, context):
        root = _find_bundle_root_from_context(context) or find_bundle_root(context.active_object)
        kb = root.ksp_bundle
        item = kb.text_assets[kb.text_assets_index]
        if item.text_block is None:
            self.report({'ERROR'}, "No Text datablock assigned")
            return {'CANCELLED'}
        try:
            item.text = item.text_block.as_string()
        except Exception:
            item.text = "\n".join(line.body for line in item.text_block.lines)
        self.report({'INFO'}, "Updated text asset %s" % item.name)
        return {'FINISHED'}


class KSPMU_OT_KspPushUiText(bpy.types.Operator):
    '''Push UI text from the bundle list (or active UI object) to viewport'''
    bl_idname = "object.ksp_push_ui_text"
    bl_label = "Push UI Text"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        root = _find_bundle_root_from_context(context) or find_bundle_root(context.active_object)
        if root is None:
            return False
        obj = context.active_object
        try:
            if obj.ksp_ui.is_ksp_ui and obj.ksp_ui.kind == 'text':
                return True
        except Exception:
            pass
        kb = root.ksp_bundle
        return (
            bool(kb.ui_elements)
            and 0 <= kb.ui_elements_index < len(kb.ui_elements)
            and kb.ui_elements[kb.ui_elements_index].kind == 'text'
        )

    def execute(self, context):
        root = _find_bundle_root_from_context(context) or find_bundle_root(context.active_object)
        kb = root.ksp_bundle
        obj = context.active_object
        text = None
        mb = None
        name = None
        try:
            if obj.ksp_ui.is_ksp_ui and obj.ksp_ui.kind == 'text':
                # Prefer list entry if indices match, else object prop
                text = obj.ksp_ui.text
                mb = obj.ksp_ui.mb_path_id
                name = obj.ksp_ui.element_name
        except Exception:
            pass
        if (
            kb.ui_elements
            and 0 <= kb.ui_elements_index < len(kb.ui_elements)
            and kb.ui_elements[kb.ui_elements_index].kind == 'text'
        ):
            el = kb.ui_elements[kb.ui_elements_index]
            text = el.text
            mb = el.mb_path_id
            name = el.name
            # Sync onto matching viewport objects
        if text is None:
            self.report({'ERROR'}, "No UI text selected")
            return {'CANCELLED'}
        updated = 0
        from ..import_ksp.tmp_markup import parse_tmp_rich_text
        from ..import_ksp.viewport import (
            _prepare_display_body,
            _split_intro_paragraphs,
            _find_para_child,
        )
        plain = _prepare_display_body(parse_tmp_rich_text(text).plain or "")
        parts = _split_intro_paragraphs(plain)

        def _push_onto(o):
            nonlocal updated
            ui = o.ksp_ui
            if not ui.is_ksp_ui:
                return False
            if mb and ui.mb_path_id == mb:
                match = True
            elif (not mb) and name and ui.element_name == name:
                match = True
            else:
                match = False
            if not match:
                return False
            ui.text = text
            try:
                o["ksp_text_display"] = plain
            except Exception:
                pass
            if o.type == 'FONT':
                o.data.body = plain
                updated += 1
                return True
            as_obj = _find_para_child(o, "as")
            each_obj = _find_para_child(o, "each")
            if as_obj is not None and each_obj is not None and parts:
                as_obj.data.body = _prepare_display_body(parts[0])
                each_obj.data.body = _prepare_display_body(parts[1])
                updated += 1
                return True
            if as_obj is not None:
                as_obj.data.body = plain
                updated += 1
                return True
            updated += 1
            return True

        for o in [root] + list(root.children_recursive):
            try:
                _push_onto(o)
            except Exception:
                continue
        self.report({'INFO'}, "Pushed UI text to %d object(s)" % updated)
        return {'FINISHED'}


def export_ksp_menu_func(self, context):
    self.layout.operator(
        KSPMU_OT_ExportKspBundle.bl_idname, text="KSP Bundle (.ksp)"
    )


classes_to_register = (
    KSPMU_OT_ExportKspBundle,
    KSPMU_OT_KspBundleNew,
    KSPMU_OT_KspReplaceTexture,
    KSPMU_OT_KspRemoveTexture,
    KSPMU_OT_KspEditTextAsset,
    KSPMU_OT_KspPushUiText,
)

menus_to_register = (
    (bpy.types.TOPBAR_MT_file_export, export_ksp_menu_func),
)
