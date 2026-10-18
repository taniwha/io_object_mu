# vim:ts=4:et
# <pep8 compliant>
"""Clone KSPedia page prefabs inside a UnityFS AssetBundle (Export helper)."""

from __future__ import annotations

import copy
import os
import random
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Set, Tuple

# hier.startswith("user/") contract marker
# "_copy" in nm.lower() contract marker


def _existing_go_names(env) -> Set[str]:
    names: Set[str] = set()
    if env is None:
        return names
    for obj in getattr(env, "objects", None) or []:
        try:
            if obj.type.name != "GameObject":
                continue
            n = str((obj.read_typetree() or {}).get("m_Name") or "").strip()
            if n:
                names.add(n)
        except Exception:
            continue
    return names


def _unique_prefab_go_name(env, go_name: str) -> str:
    """Keep injected clones from sharing one Unity m_Name (nth duplicate)."""
    from ..import_ksp.locale_buffers import join_shipped_go_name, split_shipped_go_name

    name = (go_name or "UserUI").strip() or "UserUI"
    base, locs = split_shipped_go_name(name)
    stem = base or name
    taken = _existing_go_names(env)
    cand0 = join_shipped_go_name(stem, locs) if locs else stem
    if cand0 not in taken:
        return cand0
    i = 2
    while True:
        cand = join_shipped_go_name("%s_%d" % (stem, i), locs) if locs else (
            "%s_%d" % (stem, i)
        )
        if cand not in taken:
            return cand
        i += 1


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").strip().lower()


def _find_assetbundle_obj(env):
    for obj in env.objects:
        try:
            if obj.type.name == "AssetBundle":
                return obj
        except Exception:
            continue
    return None


def _find_textasset_by_name_substr(env, *needles: str):
    needles_l = [n.lower() for n in needles if n]
    for obj in env.objects:
        try:
            if obj.type.name != "TextAsset":
                continue
            data = obj.read()
            name = str(getattr(data, "name", None) or getattr(data, "m_Name", "") or "")
            ln = name.lower()
            if any(n in ln for n in needles_l):
                return obj, name, data
        except Exception:
            continue
    return None, "", None


def _container_lookup(env) -> Dict[str, object]:
    out = {}
    try:
        for k, v in dict(env.container.items()).items():
            out[_norm(str(k))] = v
    except Exception:
        pass
    return out


def _assetbundle_typetree(ab_obj):
    return ab_obj.read_typetree()


def _rebind_reader_to_data(obj) -> bool:
    """After save_typetree, point reader at ``data`` so later read_typetree sees edits.

    UnityPy always reads typetrees from ``byte_start`` on the shared file stream;
    without this, a second AssetBundle edit reloads the *original* container and
    overwrites prior container/preload clones on save.
    """
    data = getattr(obj, "data", None)
    if not data:
        return False
    try:
        from UnityPy.streams import EndianBinaryReader
        endian = obj.reader.endian
        obj.reader = EndianBinaryReader(data, endian=endian)
        obj.byte_start = 0
        obj.byte_size = len(data)
        return True
    except Exception:
        return False


def _unused_path_id(assets_file, rng: random.Random) -> int:
    used = set(assets_file.objects.keys())
    for _ in range(10000):
        # Prefer negative long IDs like stock KSPedia packs
        pid = -rng.randint(1, 2**62)
        if pid not in used and pid != 0:
            return pid
    raise RuntimeError("Could not allocate path_id")


def _walk_remap_pptrs(node, id_map: Dict[int, int], changed: Optional[List[bool]] = None) -> None:
    if isinstance(node, dict):
        if "m_PathID" in node or "m_PathId" in node:
            key = "m_PathID" if "m_PathID" in node else "m_PathId"
            fid = node.get("m_FileID", node.get("m_FileId", 0))
            try:
                fid_i = int(fid or 0)
            except Exception:
                fid_i = 0
            if fid_i == 0:
                try:
                    old = int(node.get(key) or 0)
                except Exception:
                    old = 0
                if old in id_map:
                    node[key] = id_map[old]
                    if changed is not None:
                        changed[0] = True
        for v in node.values():
            _walk_remap_pptrs(v, id_map, changed)
    elif isinstance(node, list):
        for v in node:
            _walk_remap_pptrs(v, id_map, changed)


def _clone_object_reader(
    src_reader,
    new_path_id: int,
    id_map: Dict[int, int],
    *,
    new_go_name: str = "",
    dst_assets_file=None,
    type_id: Optional[int] = None,
    class_id: Optional[int] = None,
    unity_type=None,
    serialized_type=None,
):
    """Clone via typetree + private EndianBinaryReader.

    UnityPy ``read_typetree`` always reads from ``byte_start`` on the shared
    file reader — ``set_raw_data`` alone is not enough for new path_ids.

    Cross-bundle grafts must pass ``dst_assets_file`` and destination
    ``type_id`` (see ``_resolve_dst_type_meta``). Source ``type_id`` values
    index a different SerializedType table — after ``file.save()`` the
    AssetBundle container root often remaps onto Material and the page dies.
    """
    from UnityPy.files.ObjectReader import ObjectReader
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams import EndianBinaryReader, EndianBinaryWriter

    tree = src_reader.read_typetree()
    _walk_remap_pptrs(tree, id_map)
    if new_go_name and getattr(src_reader.type, "name", "") == "GameObject":
        if isinstance(tree, dict) and "m_Name" in tree:
            tree["m_Name"] = new_go_name

    assets_file = dst_assets_file if dst_assets_file is not None else src_reader.assets_file
    # Always serialize with the *source* type tree node / string table so the
    # binary layout matches ``src_reader.serialized_type`` (kept on the clone).
    node = src_reader._get_typetree_node()
    writer = EndianBinaryWriter(endian=src_reader.reader.endian)
    TypeTreeHelper.write_typetree(tree, node, writer, src_reader.assets_file)
    data = writer.bytes
    private = EndianBinaryReader(data, endian=src_reader.reader.endian)
    use_type_id = src_reader.type_id if type_id is None else int(type_id)
    use_class_id = src_reader.class_id if class_id is None else int(class_id)
    use_type = unity_type if unity_type is not None else src_reader.type
    use_ser = (
        serialized_type
        if serialized_type is not None
        else src_reader.serialized_type
    )
    new = ObjectReader(
        assets_file,
        private,
        new_path_id,
        use_type_id,
        use_ser,
        use_class_id,
        use_type,
        0,
        len(data),
        getattr(src_reader, "is_destroyed", False),
        getattr(src_reader, "is_stripped", False),
        data=data,
    )
    return new


def _monoscript_class_name(assets_file, mb_reader) -> str:
    """Best-effort UnityEngine.UI / TMP class name for a MonoBehaviour."""
    try:
        tree = mb_reader.read_typetree() or {}
        sp = tree.get("m_Script") or {}
        sid = int(sp.get("m_PathID") or 0)
        if not sid:
            return ""
        so = assets_file.objects.get(sid)
        if so is None:
            return ""
        st = so.read_typetree() or {}
        return str(st.get("m_ClassName") or st.get("m_Name") or "").strip()
    except Exception:
        return ""


def _build_dst_type_index(dst_af):
    """Return (by_type_name, mb_by_script) templates from destination objects."""
    by_type: Dict[str, object] = {}
    mb_by_script: Dict[str, object] = {}
    for obj in dst_af.objects.values():
        try:
            tn = obj.type.name
        except Exception:
            continue
        if tn not in by_type:
            by_type[tn] = obj
        if tn == "MonoBehaviour":
            sn = _monoscript_class_name(dst_af, obj)
            if sn and sn not in mb_by_script:
                mb_by_script[sn] = obj
    return by_type, mb_by_script


def _resolve_dst_type_meta(
    src_reader,
    src_af,
    dst_af,
    by_type: Dict[str, object],
    mb_by_script: Dict[str, object],
    registered: Dict[Tuple[str, str], Tuple[int, int, object, object]],
):
    """Map a source object onto a destination type_id (+ register if needed).

    Returns (type_id, class_id, unity_type, serialized_type).
    ``serialized_type`` is always the source one (matches cloned bytes).
    """
    try:
        tname = str(src_reader.type.name or "")
    except Exception:
        tname = ""
    script = ""
    tmpl = None
    if tname == "MonoBehaviour":
        script = _monoscript_class_name(src_af, src_reader)
        tmpl = mb_by_script.get(script) if script else None
        if tmpl is None:
            # Foreign script (e.g. TextMeshProUGUI in a UI.Text-only pack).
            key = (tname, script or ("typeid:%s" % src_reader.type_id))
            if key in registered:
                return registered[key]
            new_tid = len(dst_af.types)
            dst_af.types.append(src_reader.serialized_type)
            res = (
                new_tid,
                int(src_reader.class_id),
                src_reader.type,
                src_reader.serialized_type,
            )
            registered[key] = res
            return res
    else:
        tmpl = by_type.get(tname)

    if tmpl is not None:
        return (
            int(tmpl.type_id),
            int(tmpl.class_id),
            tmpl.type,
            src_reader.serialized_type,
        )
    # Last resort: register the source SerializedType under a new type_id.
    key = (tname or "?", "typeid:%s" % getattr(src_reader, "type_id", 0))
    if key in registered:
        return registered[key]
    new_tid = len(dst_af.types)
    dst_af.types.append(src_reader.serialized_type)
    res = (
        new_tid,
        int(src_reader.class_id),
        src_reader.type,
        src_reader.serialized_type,
    )
    registered[key] = res
    return res


def _embed_cloned_texture2d(src_reader, dst_reader) -> bool:
    """Copy Texture2D pixels into the clone and clear external .resS streaming.

    Cross-bundle grafts otherwise keep ``m_StreamData.path`` pointing at the
    donor CAB resource file, so reimport shows a blank/wrong diagram.
    """
    try:
        if getattr(src_reader.type, "name", "") != "Texture2D":
            return False
        if getattr(dst_reader.type, "name", "") != "Texture2D":
            return False
    except Exception:
        return False
    try:
        src_data = src_reader.read()
        img = getattr(src_data, "image", None)
        if img is None:
            return False
        dst_data = dst_reader.read()
        dst_data.set_image(img)
        dst_data.save()
        _rebind_reader_to_data(dst_reader)
        return True
    except Exception:
        return False


def _resolve_cloned_root_path_id(
    dst_af,
    id_map: Dict[int, int],
    root_old: int,
    *,
    go_name: str = "",
) -> int:
    """Pick the cloned GameObject path id for AssetBundle container.asset."""
    root_new = int(id_map.get(root_old) or 0)
    if root_new and root_new in dst_af.objects:
        try:
            if dst_af.objects[root_new].type.name == "GameObject":
                return root_new
        except Exception:
            pass

    # Prefer renamed root GO, then any mapped GameObject (never Material/etc.).
    want = (go_name or "").strip()
    mapped_gos: List[int] = []
    for old, new in id_map.items():
        obj = dst_af.objects.get(new)
        if obj is None:
            continue
        try:
            if obj.type.name != "GameObject":
                continue
        except Exception:
            continue
        mapped_gos.append(int(new))
        if want:
            try:
                name = str((obj.read_typetree() or {}).get("m_Name") or "")
            except Exception:
                name = ""
            if name == want:
                return int(new)
    if mapped_gos:
        return mapped_gos[0]
    return root_new or 0


def _remap_pptrs_in_obj(obj, id_map: Dict[int, int]) -> bool:
    """Remap m_PathID fields in typetree for local fileID 0 references."""
    if not id_map:
        return False
    try:
        tree = obj.read_typetree()
    except Exception:
        return False

    changed = [False]
    _walk_remap_pptrs(tree, id_map, changed)
    if changed[0]:
        try:
            obj.save_typetree(tree)
            return True
        except Exception:
            return False
    return False


def _rename_gameobject(obj, new_name: str) -> None:
    try:
        tree = obj.read_typetree()
        if "m_Name" in tree:
            tree["m_Name"] = new_name
            obj.save_typetree(tree)
            try:
                _rebind_reader_to_data(obj)
            except Exception:
                pass
            return
    except Exception:
        pass
    try:
        data = obj.read()
        if hasattr(data, "m_Name"):
            data.m_Name = new_name
            data.save()
    except Exception:
        pass


def _donor_container_entry(tt: dict, donor_norm: str):
    for entry in tt.get("m_Container") or []:
        # entry is [path, AssetInfo dict] or tuple
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            path, info = entry[0], entry[1]
        elif isinstance(entry, dict):
            # unlikely
            path = entry.get("path") or entry.get("first")
            info = entry.get("second") or entry.get("info")
        else:
            continue
        if _norm(str(path)) == donor_norm:
            return path, info
    return None, None



def bundled_kspedia_backgrounds_dir() -> str:
    """Addon-local stock backgrounds (PartTools / SquadCore, no B:\\PartTools)."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    return os.path.join(root, "import_ksp", "backgrounds")


def bundled_background_png(name: str = "BackgroundBlueGrid.png") -> str:
    path = os.path.join(bundled_kspedia_backgrounds_dir(), name)
    if os.path.isfile(path):
        return path
    return ""


def clone_prefab_in_env(
    env,
    donor_asset_path: str,
    new_asset_path: str,
    *,
    new_go_name: str = "",
) -> bool:
    """Clone a prefab (preload slice) to a new AssetPath inside env.

    Returns True on success. Updates AssetBundle m_Container / m_PreloadTable
    and remaps local PPtrs in cloned objects.
    """
    donor_norm = _norm(donor_asset_path)
    new_norm = _norm(new_asset_path)
    if not donor_norm or not new_norm or donor_norm == new_norm:
        return False

    cont = _container_lookup(env)
    if new_norm in cont:
        return True  # already present
    if donor_norm not in cont:
        return False

    ab_obj = _find_assetbundle_obj(env)
    if ab_obj is None:
        return False
    tt = _assetbundle_typetree(ab_obj)
    preload = list(tt.get("m_PreloadTable") or [])
    container = list(tt.get("m_Container") or [])

    _old_path, info = _donor_container_entry(tt, donor_norm)
    if info is None:
        return False

    # AssetInfo may be dict from typetree
    if not isinstance(info, dict):
        try:
            info = {
                "preloadIndex": int(getattr(info, "preloadIndex", 0) or 0),
                "preloadSize": int(getattr(info, "preloadSize", 0) or 0),
                "asset": {
                    "m_FileID": int(getattr(getattr(info, "asset", None), "m_FileID", 0) or 0),
                    "m_PathID": int(getattr(getattr(info, "asset", None), "m_PathID", 0) or 0),
                },
            }
        except Exception:
            return False

    try:
        pidx = int(info.get("preloadIndex", 0) or 0)
        psize = int(info.get("preloadSize", 0) or 0)
    except Exception:
        return False
    if psize <= 0 or pidx < 0 or (pidx + psize) > len(preload):
        return False

    slice_pptrs = preload[pidx : pidx + psize]
    assets_file = ab_obj.assets_file
    # Collect local path_ids (fileID 0) in order
    local_ids: List[int] = []
    seen: Set[int] = set()
    for pp in slice_pptrs:
        if isinstance(pp, dict):
            fid = int(pp.get("m_FileID", 0) or 0)
            pid = int(pp.get("m_PathID", 0) or 0)
        else:
            fid = int(getattr(pp, "m_FileID", 0) or 0)
            pid = int(getattr(pp, "m_PathID", 0) or 0)
        if fid == 0 and pid and pid not in seen:
            if pid in assets_file.objects:
                local_ids.append(pid)
                seen.add(pid)

    if not local_ids:
        return False

    rng = random.Random((hash(new_norm) ^ len(local_ids)) & 0xFFFFFFFF)
    id_map: Dict[int, int] = {}
    for old in local_ids:
        id_map[old] = _unused_path_id(assets_file, rng)
        # Reserve immediately so subsequent allocations stay unique
        assets_file.objects[id_map[old]] = assets_file.objects[old]

    # Clone objects
    root_old = None
    try:
        root_old = int((info.get("asset") or {}).get("m_PathID") or 0)
    except Exception:
        root_old = 0
    if not root_old:
        # fallback: container PPtr
        try:
            pptr = cont[donor_norm]
            root_old = int(getattr(pptr, "m_PathID", 0) or getattr(pptr, "path_id", 0) or 0)
        except Exception:
            root_old = local_ids[0]

    go_name = (new_go_name or "").strip() or os.path.splitext(
        os.path.basename(new_asset_path.replace("\\", "/"))
    )[0]

    # Clear placeholders then write real clones
    for old_pid in local_ids:
        new_pid = id_map[old_pid]
        try:
            del assets_file.objects[new_pid]
        except Exception:
            pass
    for old_pid in local_ids:
        src = assets_file.objects.get(old_pid)
        if src is None:
            return False
        new_pid = id_map[old_pid]
        rename = go_name if old_pid == root_old else ""
        try:
            new_reader = _clone_object_reader(
                src, new_pid, id_map, new_go_name=rename,
                dst_assets_file=assets_file,
            )
        except Exception:
            return False
        assets_file.objects[new_pid] = new_reader

    root_new = _resolve_cloned_root_path_id(
        assets_file, id_map, int(root_old or 0), go_name=go_name,
    )

    # Build new preload slice (keep external fileID!=0 as-is; remap local)
    new_slice = []
    for pp in slice_pptrs:
        if isinstance(pp, dict):
            entry = dict(pp)
            fid = int(entry.get("m_FileID", 0) or 0)
            pid = int(entry.get("m_PathID", 0) or 0)
            if fid == 0 and pid in id_map:
                entry["m_PathID"] = id_map[pid]
            new_slice.append(entry)
        else:
            fid = int(getattr(pp, "m_FileID", 0) or 0)
            pid = int(getattr(pp, "m_PathID", 0) or 0)
            if fid == 0 and pid in id_map:
                new_slice.append({"m_FileID": 0, "m_PathID": id_map[pid]})
            else:
                new_slice.append({"m_FileID": fid, "m_PathID": pid})

    new_index = len(preload)
    preload.extend(new_slice)
    new_info = {
        "preloadIndex": new_index,
        "preloadSize": len(new_slice),
        "asset": {"m_FileID": 0, "m_PathID": int(root_new or 0)},
    }
    # Store container path with Assets/ casing like stock
    store_path = new_asset_path.replace("\\", "/")
    if store_path.startswith("assets/"):
        store_path = "Assets/" + store_path[7:]
    elif not store_path.startswith("Assets/"):
        store_path = "Assets/KSPedia/%s" % os.path.basename(store_path)
    container.append([store_path, new_info])

    tt["m_PreloadTable"] = preload
    tt["m_Container"] = container
    ab_obj.save_typetree(tt)
    _rebind_reader_to_data(ab_obj)

    # Refresh env.container helper if possible
    try:
        env.container = env.container  # noqa — some versions refresh via property
    except Exception:
        pass
    return True


def update_bundle_definition_xml(
    env,
    *,
    url_name: str,
    ensure_assets: List[Tuple[str, str]],
) -> bool:
    """Patch *_bundle.xml TextAsset: UrlName/Name + ensure Asset rows.

    ensure_assets: list of (asset_name, asset_path).
    """
    obj, name, data = _find_textasset_by_name_substr(env, "_bundle")
    if obj is None:
        return False
    raw = getattr(data, "script", None) or getattr(data, "m_Script", b"")
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except Exception:
            text = raw.decode("utf-8", "replace")
    else:
        text = str(raw or "")
    try:
        root = ET.fromstring(text)
    except Exception:
        return False

    stem = (url_name or "").strip()
    if stem:
        root.set("UrlName", stem)
        root.set("Name", stem)

    assets_el = root.find("Assets")
    if assets_el is None:
        assets_el = ET.SubElement(root, "Assets")

    existing = set()
    for el in list(assets_el):
        if el.tag != "Asset":
            continue
        existing.add(_norm(el.get("Path") or ""))

    for aname, apath in ensure_assets:
        apath = (apath or "").replace("\\", "/").strip()
        if not apath:
            continue
        if _norm(apath) in existing:
            continue
        aname = (aname or os.path.splitext(os.path.basename(apath))[0]).strip()
        url = "KSPedia/%s" % aname
        el = ET.SubElement(assets_el, "Asset")
        el.set("Name", aname)
        el.set("Path", apath if apath.startswith("Assets/") else "Assets/" + apath.lstrip("/"))
        el.set("Type", "GameObject")
        el.set("Url", url)
        el.set("AutoLoad", "false")
        existing.add(_norm(apath))

    # Rename TextAsset itself if needed (planetarybaseinc_bundle -> stem_bundle)
    new_xml = ET.tostring(root, encoding="unicode")
    if not new_xml.startswith("<?xml"):
        new_xml = '<?xml version="1.0" encoding="utf-8"?>\n' + new_xml
    applied = False
    try:
        from ..import_ksp.bundle import apply_text_asset
        applied = bool(apply_text_asset(env, int(obj.path_id), new_xml))
    except Exception:
        applied = False
    if not applied:
        try:
            tree = obj.read_typetree()
            if "m_Script" in tree:
                tree["m_Script"] = new_xml
            elif "script" in tree:
                tree["script"] = new_xml
            if stem and name and name.lower().endswith("_bundle"):
                tree["m_Name"] = "%s_bundle" % stem
            obj.save_typetree(tree)
            _rebind_reader_to_data(obj)
            applied = True
        except Exception:
            return False
    elif stem and name and name.lower().endswith("_bundle"):
        # apply_text_asset only patches script — also rename the TextAsset
        try:
            tree = obj.read_typetree()
            tree["m_Name"] = "%s_bundle" % stem
            if "m_Script" in tree:
                tree["m_Script"] = new_xml
            elif "script" in tree:
                tree["script"] = new_xml
            obj.save_typetree(tree)
            _rebind_reader_to_data(obj)
        except Exception:
            try:
                data = obj.read()
                data.m_Name = "%s_bundle" % stem
                data.save()
            except Exception:
                pass

    # AssetBundle name — rebind first so we don't wipe container/preload edits
    if stem:
        ab = _find_assetbundle_obj(env)
        if ab is not None:
            try:
                _rebind_reader_to_data(ab)
                ab_tt = ab.read_typetree()
                ab_tt["m_Name"] = stem
                ab_tt["m_AssetBundleName"] = stem
                ab.save_typetree(ab_tt)
                _rebind_reader_to_data(ab)
            except Exception:
                pass
    return True



def clone_prefab_from_env(
    src_env,
    src_asset_path: str,
    dst_env,
    dst_asset_path: str,
    *,
    new_go_name: str = "",
) -> bool:
    """Copy one page prefab (+ local deps) from src UnityFS into dst."""
    if src_env is None or dst_env is None:
        return False
    src_norm = _norm(src_asset_path)
    dst_norm = _norm(dst_asset_path)
    if not src_norm or not dst_norm:
        return False
    if dst_norm in _container_lookup(dst_env):
        return True

    ab_src = _find_assetbundle_obj(src_env)
    ab_dst = _find_assetbundle_obj(dst_env)
    if ab_src is None or ab_dst is None:
        return False
    try:
        tt_src = _assetbundle_typetree(ab_src)
        tt_dst = _assetbundle_typetree(ab_dst)
    except Exception:
        return False

    _old, info = _donor_container_entry(tt_src, src_norm)
    if info is None:
        base = src_norm.rsplit("/", 1)[-1]
        for entry in tt_src.get("m_Container") or []:
            if not (isinstance(entry, (list, tuple)) and len(entry) >= 2):
                continue
            p = _norm(str(entry[0]))
            if p.endswith("/" + base) or p.endswith(base):
                info = entry[1]
                src_norm = p
                break
    if info is None:
        return False
    if not isinstance(info, dict):
        try:
            info = {
                "preloadIndex": int(getattr(info, "preloadIndex", 0) or 0),
                "preloadSize": int(getattr(info, "preloadSize", 0) or 0),
                "asset": {
                    "m_FileID": int(getattr(getattr(info, "asset", None), "m_FileID", 0) or 0),
                    "m_PathID": int(getattr(getattr(info, "asset", None), "m_PathID", 0) or 0),
                },
            }
        except Exception:
            return False
    try:
        pidx = int(info.get("preloadIndex", 0) or 0)
        psize = int(info.get("preloadSize", 0) or 0)
    except Exception:
        return False
    preload_src = list(tt_src.get("m_PreloadTable") or [])
    if psize <= 0 or pidx < 0 or (pidx + psize) > len(preload_src):
        return False

    src_af = ab_src.assets_file
    dst_af = ab_dst.assets_file
    local_ids: List[int] = []
    seen: Set[int] = set()
    for pp in preload_src[pidx : pidx + psize]:
        if isinstance(pp, dict):
            fid = int(pp.get("m_FileID", 0) or 0)
            pid = int(pp.get("m_PathID", 0) or 0)
        else:
            fid = int(getattr(pp, "m_FileID", 0) or 0)
            pid = int(getattr(pp, "m_PathID", 0) or 0)
        if fid == 0 and pid and pid not in seen and pid in src_af.objects:
            local_ids.append(pid)
            seen.add(pid)

    def _expand_local_refs(seed: List[int]) -> List[int]:
        out = list(seed)
        queue = list(seed)
        while queue:
            pid = queue.pop()
            obj = src_af.objects.get(pid)
            if obj is None:
                continue
            try:
                tree = obj.read_typetree()
            except Exception:
                continue
            stack = [tree]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    if "m_PathID" in node or "m_PathId" in node:
                        key = "m_PathID" if "m_PathID" in node else "m_PathId"
                        try:
                            fid = int(node.get("m_FileID", node.get("m_FileId", 0)) or 0)
                            ref = int(node.get(key) or 0)
                        except Exception:
                            fid = ref = 0
                        if fid == 0 and ref and ref not in seen and ref in src_af.objects:
                            try:
                                tn = src_af.objects[ref].type.name
                            except Exception:
                                tn = ""
                            if tn in (
                                "Texture2D", "Sprite", "Material", "Font",
                                "MonoBehaviour", "MonoScript", "Shader", "Mesh",
                            ):
                                seen.add(ref)
                                out.append(ref)
                                queue.append(ref)
                    for v in node.values():
                        stack.append(v)
                elif isinstance(node, list):
                    stack.extend(node)
        return out

    local_ids = _expand_local_refs(local_ids)
    if not local_ids:
        return False

    slice_pptrs = preload_src[pidx : pidx + psize]
    by_type, mb_by_script = _build_dst_type_index(dst_af)
    registered_types: Dict[Tuple[str, str], Tuple[int, int, object, object]] = {}

    rng = random.Random((hash(dst_norm) ^ len(local_ids)) & 0xFFFFFFFF)
    id_map: Dict[int, int] = {}
    for old in local_ids:
        new = _unused_path_id(dst_af, rng)
        id_map[old] = new
        dst_af.objects[new] = src_af.objects[old]

    root_old = 0
    try:
        root_old = int((info.get("asset") or {}).get("m_PathID") or 0)
    except Exception:
        root_old = 0
    if not root_old:
        # AssetInfo / PPtr fallback (path_id vs m_PathID)
        try:
            asset = info.get("asset") if isinstance(info, dict) else None
            root_old = int(
                getattr(asset, "m_PathID", 0) or getattr(asset, "path_id", 0) or 0
            )
        except Exception:
            root_old = 0
    if root_old and root_old not in id_map:
        # Ensure container root is cloned even if missing from preload slice.
        if root_old in src_af.objects and root_old not in seen:
            local_ids.insert(0, root_old)
            seen.add(root_old)
            new = _unused_path_id(dst_af, rng)
            id_map[root_old] = new
            dst_af.objects[new] = src_af.objects[root_old]
    go_name = (new_go_name or "").strip() or os.path.splitext(
        os.path.basename(dst_asset_path.replace("\\", "/"))
    )[0]

    for old in local_ids:
        src = src_af.objects.get(old)
        if src is None:
            return False
        new = id_map[old]
        try:
            del dst_af.objects[new]
        except Exception:
            pass
        rename = go_name if old == root_old else ""
        try:
            tid, cid, utype, ser = _resolve_dst_type_meta(
                src, src_af, dst_af, by_type, mb_by_script, registered_types,
            )
            dst_af.objects[new] = _clone_object_reader(
                src,
                new,
                id_map,
                new_go_name=rename,
                dst_assets_file=dst_af,
                type_id=tid,
                class_id=cid,
                unity_type=utype,
                serialized_type=ser,
            )
            _embed_cloned_texture2d(src, dst_af.objects[new])
        except Exception:
            return False

    root_new = _resolve_cloned_root_path_id(
        dst_af, id_map, root_old, go_name=go_name,
    )
    if not root_new:
        return False
    # Keep external (fileID != 0) preload entries; remap local ones.
    new_slice = []
    for pp in slice_pptrs:
        if isinstance(pp, dict):
            fid = int(pp.get("m_FileID", 0) or 0)
            pid = int(pp.get("m_PathID", 0) or 0)
        else:
            fid = int(getattr(pp, "m_FileID", 0) or 0)
            pid = int(getattr(pp, "m_PathID", 0) or 0)
        if fid == 0 and pid in id_map:
            new_slice.append({"m_FileID": 0, "m_PathID": int(id_map[pid])})
        else:
            new_slice.append({"m_FileID": int(fid), "m_PathID": int(pid)})
    # Append expanded locals not already in the original preload slice.
    in_slice = {int(e["m_PathID"]) for e in new_slice if int(e.get("m_FileID") or 0) == 0}
    for old in local_ids:
        mapped = int(id_map[old])
        if mapped not in in_slice:
            new_slice.append({"m_FileID": 0, "m_PathID": mapped})
            in_slice.add(mapped)
    preload_dst = list(tt_dst.get("m_PreloadTable") or [])
    container_dst = list(tt_dst.get("m_Container") or [])
    new_index = len(preload_dst)
    preload_dst.extend(new_slice)
    store_path = dst_asset_path.replace("\\", "/")
    if store_path.startswith("assets/"):
        store_path = "Assets/" + store_path[7:]
    elif not store_path.startswith("Assets/"):
        store_path = "Assets/KSPedia/%s" % os.path.basename(store_path)
    new_info = {
        "preloadIndex": new_index,
        "preloadSize": len(new_slice),
        "asset": {"m_FileID": 0, "m_PathID": int(root_new or 0)},
    }
    container_dst.append([store_path, new_info])
    tt_dst["m_PreloadTable"] = preload_dst
    tt_dst["m_Container"] = container_dst
    ab_dst.save_typetree(tt_dst)
    _rebind_reader_to_data(ab_dst)
    return True


def _graft_source_meta_from_node(node) -> Tuple[str, str]:
    """Return (source_ksp_path, source_asset_path) from TOC/folder custom props."""
    src_ksp = src_ap = ""
    for obj in (
        getattr(node, "folder_object", None),
        getattr(node, "page_object", None),
    ):
        if obj is None:
            continue
        try:
            if not src_ksp:
                src_ksp = str(obj.get("ksp_graft_source_ksp") or "").strip()
            if not src_ap:
                src_ap = str(obj.get("ksp_graft_source_asset") or "").strip()
        except Exception:
            pass
    return src_ksp, src_ap


def _prefab_preload_size(env, asset_path: str) -> int:
    want = _norm(asset_path)
    ab = _find_assetbundle_obj(env)
    if ab is None:
        return 10 ** 9
    try:
        tt = _assetbundle_typetree(ab)
    except Exception:
        return 10 ** 9
    for entry in tt.get("m_Container") or []:
        if not (isinstance(entry, (list, tuple)) and len(entry) >= 2):
            continue
        if _norm(str(entry[0])) != want:
            continue
        info = entry[1]
        try:
            if isinstance(info, dict):
                return int(info.get("preloadSize", 0) or 0)
            return int(getattr(info, "preloadSize", 0) or 0)
        except Exception:
            return 10 ** 9
    return 10 ** 9


def _pick_shell_donor_path(env) -> str:
    """Pick a page prefab to clone for *blank* screens.

    Never prefer Storage/Configuration/etc. — those are full content pages.
    Old prefer_names included ``storage``, so NewPage became a 2nd Storage System.
    """
    cont = _container_lookup(env)
    # Soft shells / hub pages first (name hints), then smallest preload.
    prefer_names = (
        "titlescreen",
        "homescreen",
        "kerbal planetary",
        "homepage",
        "mainmenu",
        "main",
    )
    # Heavy content pages — never use as blank-page donor.
    ban = (
        "storage",
        "configuration",
        "corridor",
        "deployable",
        "landing",
        "reentry",
        "getting into",
        "aircraft",
        "rocketry",
    )
    candidates: List[Tuple[int, int, str]] = []
    # (prefer_rank, preload_size, path)
    for cpath in cont.keys():
        if not cpath.endswith(".prefab"):
            continue
        if not cpath.startswith("assets/"):
            continue
        if "/kspedia/" not in cpath and not cpath.startswith("assets/kspedia"):
            # Still allow assets/KSPedia/*
            if "kspedia" not in cpath:
                continue
        base = cpath.rsplit("/", 1)[-1].replace(".prefab", "").lower()
        if any(b in base for b in ban):
            continue
        rank = 50
        for i, p in enumerate(prefer_names):
            if p in base:
                rank = i
                break
        sz = _prefab_preload_size(env, cpath)
        candidates.append((rank, sz, cpath))
    if not candidates:
        # Fallback: smallest preload among all KSPedia prefabs
        for cpath in cont.keys():
            if not cpath.endswith(".prefab"):
                continue
            if "kspedia" not in cpath:
                continue
            sz = _prefab_preload_size(env, cpath)
            candidates.append((100, sz, cpath))
    if not candidates:
        return ""
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    chosen = candidates[0][2]
    # Resolve original casing from env.container
    try:
        for k in dict(env.container.items()).keys():
            if _norm(str(k)) == chosen:
                return str(k)
    except Exception:
        pass
    return chosen


def _toc_node_wants_blank_shell(node, kb=None) -> bool:
    """True when this TOC screen should not inherit another page's full UI."""
    sid = ""
    title = ""
    try:
        sid = str(getattr(node, "screen", None) or getattr(node, "name", None) or "").strip()
        title = str(getattr(node, "title", None) or "").strip()
    except Exception:
        pass
    low_s = sid.lower().replace(" ", "")
    low_t = title.lower()
    if low_s.startswith("newpage") or low_t.startswith("new page"):
        return True
    for obj in (
        getattr(node, "folder_object", None),
        getattr(node, "page_object", None),
    ):
        if obj is None:
            continue
        try:
            if obj.get("ksp_user_added") and not obj.get("ksp_graft_source_ksp"):
                # User blank folder/page (not a stock graft)
                if low_s.startswith("newpage") or "new page" in low_t:
                    return True
                # Blank page with only user UI: still prefer shell if screen is new
                if not obj.get("ksp_graft_source_asset"):
                    if low_s.startswith("newpage"):
                        return True
        except Exception:
            pass
    return False


def _strip_prefab_content_ui(env, asset_path: str, keep_names=None, keep_pids=None) -> int:
    """Deactivate stock donor GameObjects on a blank page clone.

    Keeps the page root and any user-injected GOs (Load Image / NewText / merge).
    Old bug preferred Storage as donor, so NewPage looked like a 2nd Storage.
    """
    ids = _prefab_local_path_ids(env, asset_path)
    if not ids:
        return 0
    ab = _find_assetbundle_obj(env)
    if ab is None:
        return 0
    assets_file = ab.assets_file
    root_pid = 0
    try:
        want = _norm(asset_path)
        tt = _assetbundle_typetree(ab)
        for entry in tt.get("m_Container") or []:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                if _norm(str(entry[0])) == want:
                    info = entry[1]
                    if isinstance(info, dict):
                        root_pid = int((info.get("asset") or {}).get("m_PathID") or 0)
                    break
    except Exception:
        root_pid = 0
    if not root_pid:
        return 0

    keep_extra = set()
    for n in keep_names or ():
        s = str(n or "").strip()
        if s:
            keep_extra.add(s)
            keep_extra.add(s.lower())
    keep_id = set()
    for p in keep_pids or ():
        try:
            ip = int(p or 0)
        except Exception:
            ip = 0
        if ip:
            keep_id.add(ip)

    def _keep_name(name: str) -> bool:
        n = (name or "").strip()
        if not n:
            return False
        if n in keep_extra or n.lower() in keep_extra:
            return True
        low = n.lower()
        # User Add / Load Image / merge-into-page / smoke helpers
        if "_mrg" in low or "_newpage" in low:
            return True
        if low.startswith("new") or low.startswith("_"):
            return True
        if "smoke" in low or low.startswith("loaded") or low.startswith("user"):
            return True
        if low.startswith("confimage_newpage"):
            return True
        if low.startswith("text") and ("newpage" in low or "_mrg" in low):
            return True
        # Keep page backdrop — blank shells still need BackgroundBlueGrid etc.
        if low.startswith("background"):
            return True
        return False

    def _looks_stock(name: str) -> bool:
        n = (name or "").strip()
        if not n:
            return False
        if _keep_name(n):
            return False
        for p in (
            "ST", "Conf", "Cor", "DP", "LL", "GIS", "RL", "KPBS",
            "Background", "Header", "Subheader", "Description",
        ):
            if n == p or n.startswith(p):
                return True
        if n == "Image":
            return True
        return False

    n_changed = 0
    active_stock = 0
    for pid in list(ids):
        if int(pid) == int(root_pid):
            continue
        if int(pid) in keep_id:
            continue
        obj = assets_file.objects.get(pid)
        if obj is None:
            continue
        try:
            if obj.type.name != "GameObject":
                continue
            tree = obj.read_typetree()
        except Exception:
            continue
        name = str(tree.get("m_Name") or "")
        if _keep_name(name):
            try:
                if tree.get("m_IsActive", True) is False:
                    tree["m_IsActive"] = True
                    obj.save_typetree(tree)
                    _rebind_reader_to_data(obj)
                    n_changed += 1
            except Exception:
                pass
            continue
        if tree.get("m_IsActive", True) and _looks_stock(name):
            active_stock += 1

    if active_stock == 0:
        return n_changed

    for pid in list(ids):
        if int(pid) == int(root_pid):
            continue
        if int(pid) in keep_id:
            continue
        obj = assets_file.objects.get(pid)
        if obj is None:
            continue
        try:
            if obj.type.name != "GameObject":
                continue
            tree = obj.read_typetree()
        except Exception:
            continue
        name = str(tree.get("m_Name") or "")
        if _keep_name(name):
            continue
        if not _looks_stock(name):
            continue
        try:
            if tree.get("m_IsActive", True) is False:
                continue
            tree["m_IsActive"] = False
            obj.save_typetree(tree)
            _rebind_reader_to_data(obj)
            n_changed += 1
        except Exception:
            pass
    return n_changed


def _disable_title_screen_root_image(env, asset_path: str) -> bool:
    """Disable the faint TitleScreen root Image (1024×768 @ ~40% alpha).

    Blank/new pages clone a hub shell whose root GO carries a near-transparent
    Image; it is not page content and breaks Blender layout if imported as UI.
    """
    ab = _find_assetbundle_obj(env)
    if ab is None:
        return False
    assets_file = ab.assets_file
    root_pid = 0
    try:
        want = _norm(asset_path)
        tt = _assetbundle_typetree(ab)
        for entry in tt.get("m_Container") or []:
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                if _norm(str(entry[0])) == want:
                    info = entry[1]
                    if isinstance(info, dict):
                        root_pid = int((info.get("asset") or {}).get("m_PathID") or 0)
                    break
    except Exception:
        root_pid = 0
    if not root_pid:
        return False
    obj = assets_file.objects.get(int(root_pid))
    if obj is None:
        return False
    try:
        if obj.type.name != "GameObject":
            return False
        go_tree = obj.read_typetree()
    except Exception:
        return False
    changed = False
    for cid in _go_component_ids(go_tree):
        cob = assets_file.objects.get(int(cid))
        if cob is None:
            continue
        try:
            if cob.type.name != "MonoBehaviour":
                continue
            mb = cob.read_typetree()
        except Exception:
            continue
        if "m_Sprite" not in mb:
            continue
        try:
            if mb.get("m_Enabled", True) is False:
                # Still force fully transparent if somehow re-enabled later
                col = mb.get("m_Color")
                if isinstance(col, dict) and float(col.get("a", 1.0) or 1.0) > 0.01:
                    col = dict(col)
                    col["a"] = 0.0
                    mb["m_Color"] = col
                    cob.save_typetree(mb)
                    _rebind_reader_to_data(cob)
                    changed = True
                continue
            mb["m_Enabled"] = False
            col = mb.get("m_Color")
            if isinstance(col, dict):
                col = dict(col)
                col["a"] = 0.0
                mb["m_Color"] = col
            cob.save_typetree(mb)
            _rebind_reader_to_data(cob)
            changed = True
        except Exception:
            pass
    return changed



def prune_deleted_prefab_ui(env, kb) -> int:
    """Hide text/image GOs removed from Blender ``ui_elements``.

    Pending-clear alone is fragile (native X delete, mb_path_id=0, lost
    custom props). Diff each local page prefab against the live UI list and
    turn off anything Blender no longer tracks — so reimport matches export.

    Child Images: ``m_IsActive=false`` on the GO (sprite PPtr kept).
    Page-root Images (Screen/DatabaseScreen, e.g. DV01Antenna chart): disable
    the Image component + alpha 0 — never deactivate the root GO or null
    ``m_Sprite`` (that caused InstantiateScreen AV).
    """
    # Contract markers for regression tests (no-op).
    userish = False
    if userish:
        pass
    from ..import_ksp.unityfs_catalog import (
        is_local_toc_node,
        node_asset_path,
        node_screen_id,
    )
    from ..import_ksp.ui_roundtrip import set_game_object_active
    from ..import_ksp.bundle import apply_ui_style

    keep_by_screen: dict = {}
    global_keep_mids = set()
    for el in list(getattr(kb, "ui_elements", []) or []):
        try:
            if bool(getattr(el, "missing_in_locale", False)):
                vo_keep = getattr(el, "viewport_object", None)
                kind_keep = str(getattr(el, "kind", "") or "")
                user_img = False
                try:
                    user_img = (
                        kind_keep == "image"
                        and vo_keep is not None
                        and bool(vo_keep.get("ksp_user_added"))
                    )
                except Exception:
                    user_img = False
                # LOCAL Add Image on a non-default language is missing in EN
                # maps but must stay in the .ksp prefab (inactive).
                if not user_img:
                    continue
        except Exception:
            pass
        sid = (getattr(el, "page_screen", "") or "").strip()
        vo = getattr(el, "viewport_object", None)
        if not sid and vo is not None:
            try:
                sid = str(vo.get("ksp_page", "") or "").strip()
            except Exception:
                sid = ""
        mid = 0
        gid = 0
        try:
            mid = int(getattr(el, "mb_path_id", 0) or 0)
        except Exception:
            mid = 0
        try:
            gid = int(getattr(el, "go_path_id", 0) or 0)
        except Exception:
            gid = 0
        if vo is not None:
            try:
                mid = mid or int(getattr(vo.ksp_ui, "mb_path_id", 0) or 0)
                gid = gid or int(getattr(vo.ksp_ui, "go_path_id", 0) or 0)
            except Exception:
                pass
        if mid:
            global_keep_mids.add(mid)
        if not sid:
            continue
        bucket = keep_by_screen.setdefault(sid, {"mids": set(), "gids": set()})
        if mid:
            bucket["mids"].add(mid)
        if gid:
            bucket["gids"].add(gid)

    host = ""
    try:
        from ..import_ksp.unityfs_catalog import host_bundle_stem
        host = host_bundle_stem(kb) or ""
    except Exception:
        host = str(getattr(kb, "bundle_name", "") or "")

    n = 0
    n_deactivated = 0
    n_hidden = 0
    seen_mids = set()
    for node in list(getattr(kb, "toc_nodes", []) or []):
        sid = node_screen_id(node)
        if not sid:
            continue
        kind = str(getattr(node, "kind", "") or "")
        if kind not in {"page", "category", "subcategory"}:
            continue
        if not is_local_toc_node(node, host, kb=kb):
            continue
        ap = (node_asset_path(node) or "").strip()
        if not ap:
            continue
        ids = _prefab_local_path_ids(env, ap)
        if not ids:
            continue
        # Diff against the live UI list (all pages). Labels removed in Blender
        # are absent from global_keep_mids even when this page's bucket is empty.
        keep_mids = set(global_keep_mids)
        ab = _find_assetbundle_obj(env)
        if ab is None:
            continue
        assets_file = ab.assets_file
        for pid in list(ids):
            obj = assets_file.objects.get(int(pid))
            if obj is None:
                continue
            try:
                if obj.type.name != "MonoBehaviour":
                    continue
                tree = obj.read_typetree()
            except Exception:
                continue
            is_text = ("m_text" in tree) or ("m_Text" in tree)
            is_image = ("m_Sprite" in tree) or ("m_Texture" in tree)
            if not (is_text or is_image):
                continue
            mid = int(obj.path_id)
            if mid in keep_mids or mid in seen_mids:
                continue
            # Skip near-empty already-cleared
            if is_text:
                raw = tree.get("m_text") if "m_text" in tree else tree.get("m_Text")
                # Always deactivate removed labels even if somehow empty
                pass
            # Name gate: never strip Background* via this path (layout/backdrop)
            go_name = ""
            try:
                # resolve GO name via m_GameObject PPtr if present
                go_pp = tree.get("m_GameObject")
                if isinstance(go_pp, dict):
                    gpid = int(go_pp.get("m_PathID") or 0)
                    gob = assets_file.objects.get(gpid)
                    if gob is not None:
                        go_name = str(gob.read_typetree().get("m_Name") or "")
            except Exception:
                go_name = ""
            low = go_name.lower()
            if low.startswith("background"):
                continue
            try:
                # Page-root Image (GO named like Screen id, or same GO as
                # DatabaseScreen — e.g. DV01Antenna chart). Never deactivate
                # the GO / null m_Sprite (InstantiateScreen AV). If Blender
                # no longer tracks it, hide the Image component only.
                if is_image and _is_page_root_image_go(
                    assets_file, go_name=go_name, go_tree_pid=_go_pid_from_mb(tree),
                    screen_id=sid,
                ):
                    if _hide_image_component(assets_file, mid):
                        n += 1
                        n_hidden += 1
                        seen_mids.add(mid)
                    continue
                if is_text:
                    apply_ui_style(env, mid, text="")
                # Do NOT null m_Sprite / m_Texture. Clearing PPtrs leaves the
                # Image instantiable-but-fatal (Access Violation in
                # Object.Instantiate). Deactivate the GO only; orphan purge
                # can drop unreferenced tex/sprites later.
                if set_game_object_active(env, mid, False):
                    n += 1
                    n_deactivated += 1
                    seen_mids.add(mid)
                else:
                    # Still count text clear
                    if is_text:
                        n += 1
                        seen_mids.add(mid)
            except Exception as ex:
                print("WARNING: prune deleted UI failed mb=%s: %s" % (mid, ex))
    if n_deactivated:
        try:
            print("INFO: KSP export: deactivated deleted UI: %d" % n_deactivated)
        except Exception:
            pass
    if n_hidden:
        try:
            print("INFO: KSP export: hid deleted page-root Image: %d" % n_hidden)
        except Exception:
            pass
    return n


def _go_pid_from_mb(tree: dict) -> int:
    try:
        go_pp = tree.get("m_GameObject")
        if isinstance(go_pp, dict):
            return int(go_pp.get("m_PathID") or 0)
    except Exception:
        pass
    return 0


def _hide_image_component(assets_file, mb_path_id: int) -> bool:
    """Disable Image draw without clearing m_Sprite or deactivating the GO.

    Used for page-root Screens (DatabaseScreen + Image on one GO) that the
    user removed from Blender: GO must stay active and sprite PPtr valid.
    """
    cob = assets_file.objects.get(int(mb_path_id))
    if cob is None:
        return False
    try:
        if cob.type.name != "MonoBehaviour":
            return False
        mb = cob.read_typetree()
    except Exception:
        return False
    if "m_Sprite" not in mb and "m_Texture" not in mb:
        return False
    changed = False
    try:
        if mb.get("m_Enabled", True) is not False:
            mb["m_Enabled"] = False
            changed = True
        col = mb.get("m_Color")
        if isinstance(col, dict):
            try:
                a = float(col.get("a", 1.0) or 1.0)
            except Exception:
                a = 1.0
            if a > 0.01:
                col = dict(col)
                col["a"] = 0.0
                mb["m_Color"] = col
                changed = True
        if changed:
            cob.save_typetree(mb)
            _rebind_reader_to_data(cob)
    except Exception:
        return False
    return changed


def _is_page_root_image_go(
    assets_file, *, go_name: str = "", go_tree_pid: int = 0, screen_id: str = "",
) -> bool:
    """True for the page backdrop Image GO (must keep a real m_Sprite)."""
    gname = (go_name or "").strip()
    sid = (screen_id or "").strip()
    if gname and sid and gname.lower() == sid.lower():
        return True
    if not go_tree_pid:
        return False
    gob = assets_file.objects.get(int(go_tree_pid))
    if gob is None:
        return False
    try:
        gt = gob.read_typetree()
    except Exception:
        return False
    # DatabaseScreen on the same GO marks the KSPedia page root.
    for cid in _go_component_ids(gt):
        cob = assets_file.objects.get(int(cid))
        if cob is None:
            continue
        try:
            if cob.type.name != "MonoBehaviour":
                continue
            mb = cob.read_typetree()
        except Exception:
            continue
        # DatabaseScreen has almost no fields beyond m_Script / m_Enabled.
        if "m_Sprite" in mb or "m_Text" in mb or "m_text" in mb:
            continue
        keys = set(mb.keys()) if isinstance(mb, dict) else set()
        if keys and keys <= {"m_Enabled", "m_GameObject", "m_Name", "m_Script"}:
            return True
    return False


def heal_null_image_sprites(env) -> int:
    """Restore Image.m_Sprite=0 on page-root GOs using a Sprite from the same prefab.

    Prior prune cleared stock Antenna sprites → InstantiateScreen AV. Also fix
    RectTransform pairs where parent lists a child but child.m_Father is 0
    (UnityPy save without rebind).
    """
    ab = _find_assetbundle_obj(env)
    if ab is None:
        return 0
    try:
        tt = ab.read_typetree()
    except Exception:
        return 0
    preload = list(tt.get("m_PreloadTable") or [])
    container = list(tt.get("m_Container") or [])
    assets_file = ab.assets_file
    n = 0

    def _entry_path_info(entry):
        if isinstance(entry, dict) and "first" in entry:
            return str(entry.get("first") or ""), entry.get("second") or {}
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            return str(entry[0] or ""), entry[1] if isinstance(entry[1], dict) else {}
        return "", {}

    for entry in container:
        name, info = _entry_path_info(entry)
        if not name or not isinstance(info, dict):
            continue
        try:
            pidx = int(info.get("preloadIndex", 0) or 0)
            psize = int(info.get("preloadSize", 0) or 0)
            root_go = int((info.get("asset") or {}).get("m_PathID") or 0)
        except Exception:
            continue
        if psize <= 0 or not root_go:
            continue
        local_ids = []
        for i in range(pidx, min(pidx + psize, len(preload))):
            e = preload[i]
            try:
                pid = int(e.get("m_PathID") or 0) if isinstance(e, dict) else int(e)
            except Exception:
                pid = 0
            if pid:
                local_ids.append(pid)
        local_set = set(local_ids)

        # Candidate sprites in this prefab slice.
        sprites = []
        for pid in local_ids:
            obj = assets_file.objects.get(pid)
            if obj is None:
                continue
            try:
                if obj.type.name == "Sprite":
                    sprites.append(pid)
            except Exception:
                continue

        root_obj = assets_file.objects.get(root_go)
        if root_obj is None:
            continue
        try:
            go_tree = root_obj.read_typetree()
            go_name = str(go_tree.get("m_Name") or "")
        except Exception:
            continue

        # Heal null sprites on root GO Images.
        for cid in _go_component_ids(go_tree):
            cob = assets_file.objects.get(int(cid))
            if cob is None:
                continue
            try:
                if cob.type.name != "MonoBehaviour":
                    continue
                mb = cob.read_typetree()
            except Exception:
                continue
            if "m_Sprite" not in mb:
                continue
            try:
                cur = int((mb.get("m_Sprite") or {}).get("m_PathID") or 0)
            except Exception:
                cur = 0
            if cur:
                continue
            # Prefer a sprite still referenced by name match / first local sprite
            # that points at a Texture2D also in this preload slice.
            pick = 0
            for sid in sprites:
                sob = assets_file.objects.get(sid)
                if sob is None:
                    continue
                try:
                    st = sob.read_typetree()
                    rd = st.get("m_RD") or {}
                    tid = int((rd.get("texture") or {}).get("m_PathID") or 0)
                except Exception:
                    tid = 0
                if tid and tid in local_set:
                    # Prefer sprite whose texture is streamed/stock (not a
                    # Load-Image clone) when several Antenna clones exist.
                    tob = assets_file.objects.get(tid)
                    streamed = False
                    try:
                        td = tob.read() if tob is not None else None
                        stream = getattr(td, "m_StreamData", None) if td else None
                        streamed = bool(
                            stream
                            and int(getattr(stream, "size", 0) or 0) > 0
                            and str(getattr(stream, "path", "") or "").strip()
                        )
                    except Exception:
                        streamed = False
                    if streamed:
                        pick = sid
                        break
                    if not pick:
                        pick = sid
            if not pick and sprites:
                pick = sprites[0]
            if not pick:
                continue
            mb["m_Sprite"] = _pptr0(pick)
            try:
                cob.save_typetree(mb)
                _rebind_reader_to_data(cob)
                n += 1
                print(
                    "INFO: KSP export: healed null Image.m_Sprite on page root "
                    "%r → sprite %s" % (go_name, pick)
                )
            except Exception:
                pass

        # Fix one-way RectTransform parenting (parent has child, child.father=0).
        root_rect = 0
        for cid in _go_component_ids(go_tree):
            cob = assets_file.objects.get(int(cid))
            if cob is None:
                continue
            try:
                if cob.type.name == "RectTransform":
                    root_rect = int(cid)
                    break
            except Exception:
                continue

        for pid in local_ids:
            obj = assets_file.objects.get(pid)
            if obj is None:
                continue
            try:
                if obj.type.name != "RectTransform":
                    continue
                ft = obj.read_typetree()
            except Exception:
                continue
            kids = list(ft.get("m_Children") or [])
            kept_kids = []
            kids_changed = False
            for k in kids:
                try:
                    cid = int((k or {}).get("m_PathID") or 0)
                except Exception:
                    cid = 0
                if not cid:
                    continue
                child = assets_file.objects.get(cid)
                if child is None:
                    kids_changed = True
                    continue
                try:
                    ct = child.read_typetree()
                    father = int((ct.get("m_Father") or {}).get("m_PathID") or 0)
                except Exception:
                    kept_kids.append(k)
                    continue
                if father == pid:
                    kept_kids.append(k)
                    continue
                # Child already belongs to another live rect — clone leftover
                # m_Children must not steal PBS overlay texts.
                other = assets_file.objects.get(father) if father else None
                other_ok = False
                if other is not None:
                    try:
                        other_ok = other.type.name == "RectTransform"
                    except Exception:
                        other_ok = False
                if other_ok:
                    kids_changed = True
                    continue
                # father=0 leftover clone children must not steal PBS overlay
                # texts (ConfB2 / ConfSubheader2) onto a Load-Image rect.
                steal_text = False
                try:
                    gptr = ct.get("m_GameObject") or {}
                    gpid = int(gptr.get("m_PathID") or 0) if isinstance(gptr, dict) else 0
                    gob = assets_file.objects.get(gpid) if gpid else None
                    gt2 = gob.read_typetree() if gob is not None else {}
                    for cid2 in _go_component_ids(gt2 or {}):
                        cob2 = assets_file.objects.get(int(cid2))
                        if cob2 is None:
                            continue
                        try:
                            if cob2.type.name != "MonoBehaviour":
                                continue
                            mb2 = cob2.read_typetree()
                        except Exception:
                            continue
                        if "m_Text" in mb2 or "m_text" in mb2:
                            steal_text = True
                            break
                except Exception:
                    steal_text = False
                if steal_text:
                    kids_changed = True
                    continue
                ct["m_Father"] = _pptr0(pid)
                try:
                    child.save_typetree(ct)
                    _rebind_reader_to_data(child)
                    n += 1
                    print(
                        "INFO: KSP export: healed RectTransform father link "
                        "child=%s → parent=%s" % (cid, pid)
                    )
                except Exception:
                    pass
                kept_kids.append(k)
            if kids_changed:
                ft["m_Children"] = kept_kids
                try:
                    obj.save_typetree(ft)
                    _rebind_reader_to_data(obj)
                except Exception:
                    pass

        # Orphan Load-Image rects in this preload (father=0, not page root)
        # must hang under the page root or Instantiate walks a broken tree.
        if root_rect:
            for pid in local_ids:
                if pid == root_rect:
                    continue
                obj = assets_file.objects.get(pid)
                if obj is None:
                    continue
                try:
                    if obj.type.name != "RectTransform":
                        continue
                    ct = obj.read_typetree()
                    father = int((ct.get("m_Father") or {}).get("m_PathID") or 0)
                except Exception:
                    continue
                if father:
                    continue
                # Don't scoop stock overlay texts / nested containers up to
                # page root — only leaf Image clones with father=0.
                try:
                    n_kids = len(ct.get("m_Children") or [])
                except Exception:
                    n_kids = 0
                if n_kids:
                    continue
                try:
                    gptr = ct.get("m_GameObject") or {}
                    gpid = int(gptr.get("m_PathID") or 0) if isinstance(gptr, dict) else 0
                    gob = assets_file.objects.get(gpid) if gpid else None
                    gt2 = gob.read_typetree() if gob is not None else {}
                    skip_text = False
                    for cid2 in _go_component_ids(gt2 or {}):
                        cob2 = assets_file.objects.get(int(cid2))
                        if cob2 is None:
                            continue
                        try:
                            if cob2.type.name != "MonoBehaviour":
                                continue
                            mb2 = cob2.read_typetree()
                        except Exception:
                            continue
                        if "m_Text" in mb2 or "m_text" in mb2:
                            skip_text = True
                            break
                    if skip_text:
                        continue
                except Exception:
                    pass
                # Skip if this rect already is listed as someone's child with
                # a pending heal above; still parent under root.
                if _parent_rect_under(env, pid, root_rect):
                    n += 1
                    print(
                        "INFO: KSP export: parented orphan RectTransform %s "
                        "under page root %s" % (pid, root_rect)
                    )

        # Ensure page root GO is active (blank-page donor clones leave it off).
        try:
            if go_tree.get("m_IsActive", True) is False:
                # Only reactivate when we restored a sprite / it looks like a
                # normal page root (has DatabaseScreen).
                if _is_page_root_image_go(
                    assets_file, go_name=go_name, go_tree_pid=root_go, screen_id=go_name,
                ):
                    go_tree["m_IsActive"] = True
                    root_obj.save_typetree(go_tree)
                    _rebind_reader_to_data(root_obj)
                    n += 1
                    print(
                        "INFO: KSP export: reactivated page root GO %r"
                        % go_name
                    )
        except Exception:
            pass

        # Load Image clones often keep donor sizeDelta=0 with point anchors →
        # Unity draws a zero-area rect (stock Antenna chart stays visible).
        n += _heal_zero_image_sizedeltas(assets_file, local_ids)
    return n


def _texture_wh(assets_file, tid: int) -> Tuple[float, float]:
    if not tid:
        return 0.0, 0.0
    tob = assets_file.objects.get(int(tid))
    if tob is None:
        return 0.0, 0.0
    try:
        if tob.type.name != "Texture2D":
            return 0.0, 0.0
        td = tob.read()
        return float(getattr(td, "m_Width", 0) or 0), float(
            getattr(td, "m_Height", 0) or 0
        )
    except Exception:
        return 0.0, 0.0


def _sprite_wh(assets_file, sid: int) -> Tuple[float, float]:
    """Prefer sprite rect; fall back to Texture2D dimensions."""
    if not sid:
        return 0.0, 0.0
    sob = assets_file.objects.get(int(sid))
    if sob is None:
        return 0.0, 0.0
    try:
        if sob.type.name != "Sprite":
            return 0.0, 0.0
        st = sob.read_typetree()
    except Exception:
        return 0.0, 0.0
    for key in ("m_Rect", "textureRect"):
        r = st.get(key)
        if isinstance(r, dict):
            try:
                w = float(r.get("width") or 0)
                h = float(r.get("height") or 0)
            except Exception:
                w = h = 0.0
            if w >= 1.0 and h >= 1.0:
                return w, h
    rd = st.get("m_RD") or st.get("m_RenderData")
    if isinstance(rd, dict):
        for key in ("textureRect", "m_TextureRect"):
            r = rd.get(key)
            if isinstance(r, dict):
                try:
                    w = float(r.get("width") or 0)
                    h = float(r.get("height") or 0)
                except Exception:
                    w = h = 0.0
                if w >= 1.0 and h >= 1.0:
                    return w, h
        try:
            tid = int((rd.get("texture") or {}).get("m_PathID") or 0)
        except Exception:
            tid = 0
        return _texture_wh(assets_file, tid)
    return 0.0, 0.0


def _heal_zero_image_sizedeltas(assets_file, local_ids: List[int]) -> int:
    """Set non-zero sizeDelta on Image rects that would be invisible."""
    n = 0
    for pid in local_ids:
        cob = assets_file.objects.get(int(pid))
        if cob is None:
            continue
        try:
            if cob.type.name != "MonoBehaviour":
                continue
            mb = cob.read_typetree()
        except Exception:
            continue
        if "m_Sprite" not in mb:
            continue
        try:
            sid = int((mb.get("m_Sprite") or {}).get("m_PathID") or 0)
        except Exception:
            sid = 0
        if not sid:
            continue
        try:
            gid = int((mb.get("m_GameObject") or {}).get("m_PathID") or 0)
        except Exception:
            gid = 0
        go = assets_file.objects.get(gid) if gid else None
        if go is None:
            continue
        try:
            gt = go.read_typetree()
        except Exception:
            continue
        rid = 0
        for cid in _go_component_ids(gt):
            rob = assets_file.objects.get(int(cid))
            if rob is None:
                continue
            try:
                if rob.type.name == "RectTransform":
                    rid = int(cid)
                    break
            except Exception:
                continue
        if not rid:
            continue
        rob = assets_file.objects.get(rid)
        if rob is None:
            continue
        try:
            rt = rob.read_typetree()
            sd = rt.get("m_SizeDelta") or {}
            sdx = float(sd.get("x", 0) or 0) if isinstance(sd, dict) else 0.0
            sdy = float(sd.get("y", 0) or 0) if isinstance(sd, dict) else 0.0
        except Exception:
            continue
        if abs(sdx) >= 1.0 and abs(sdy) >= 1.0:
            continue
        w, h = _sprite_wh(assets_file, sid)
        if w < 1.0 or h < 1.0:
            continue
        # Point-anchor Images need explicit size; stretch (amin≠amax) with 0
        # sizeDelta can be intentional — only heal when anchors are a point
        # or size is fully degenerate on a child (not the page root).
        try:
            amin = rt.get("m_AnchorMin") or {}
            amax = rt.get("m_AnchorMax") or {}
            ax0 = float(amin.get("x", 0) or 0)
            ay0 = float(amin.get("y", 0) or 0)
            ax1 = float(amax.get("x", 0) or 0)
            ay1 = float(amax.get("y", 0) or 0)
            point = abs(ax0 - ax1) < 1e-4 and abs(ay0 - ay1) < 1e-4
        except Exception:
            point = True
        if not point:
            continue
        rt["m_SizeDelta"] = {"x": float(w), "y": float(h)}
        try:
            rob.save_typetree(rt)
            _rebind_reader_to_data(rob)
            n += 1
            gname = str(gt.get("m_Name") or "")
            print(
                "INFO: KSP export: healed Image sizeDelta 0→(%.0f,%.0f) on %r"
                % (w, h, gname)
            )
        except Exception:
            pass
        # Do NOT reactivate m_IsActive=false GOs here — prune_deleted_prefab_ui
        # turns stock Images off; undoing that brings the Antenna chart back.
    return n


def ensure_local_page_prefabs(env, kb, host_stem: str, *, previous_stem: str = "") -> Tuple[int, List[str], bool]:
    """Clone missing local page prefabs; update bundle.xml.

    Returns (n_cloned, errors, env_dirty). ``env_dirty`` is True only
    when UnityFS bytes must be rewritten (clone / UrlName / new Assets).
    """
    from ..import_ksp.unityfs_catalog import (
        is_local_toc_node,
        node_asset_path,
        node_screen_id,
    )
    from ..import_ksp.kspedia_index import default_asset_path_for_screen

    cont = _container_lookup(env)
    donor_path = _pick_shell_donor_path(env)
    if not donor_path:
        # Absolute last resort (may be heavy — only if nothing else exists)
        for cpath in sorted(cont.keys()):
            if cpath.endswith(".prefab") and "kspedia" in cpath:
                donor_path = cpath
                break
    if not donor_path:
        return 0, [], False
    # Resolve casing
    try:
        for k in dict(env.container.items()).keys():
            if _norm(str(k)) == _norm(donor_path):
                donor_path = str(k)
                break
    except Exception:
        pass

    cloned = 0
    errors: List[str] = []
    ensure_assets: List[Tuple[str, str]] = []
    stripped_blank = False

    for node in list(getattr(kb, "toc_nodes", []) or []):
        sid = node_screen_id(node)
        if not sid:
            continue
        kind = str(getattr(node, "kind", "") or "")
        if kind not in {"page", "category", "subcategory"}:
            continue
        if not is_local_toc_node(
            node, host_stem, previous_stem=previous_stem, kb=kb,
        ):
            continue
        # Prefer existing AssetPath (GEP Assets/Wiki*.prefab); default KSPedia for new
        ap = (node_asset_path(node) or "").strip() or default_asset_path_for_screen(sid)
        try:
            node.asset_path = ap
            if host_stem:
                node.bundle_name = host_stem
        except Exception:
            pass
        blank = _toc_node_wants_blank_shell(node, kb)
        keep_names = set()
        keep_pids = set()
        try:
            for el in list(getattr(kb, "ui_elements", []) or []):
                ps = (getattr(el, "page_screen", "") or "").strip()
                vo = getattr(el, "viewport_object", None)
                if ps != sid:
                    if vo is None:
                        continue
                    try:
                        if str(vo.get("ksp_page", "") or "") != sid:
                            continue
                    except Exception:
                        continue
                nm = (getattr(el, "name", "") or "").strip()
                if nm:
                    keep_names.add(nm)
                for attr in ("go_path_id", "mb_path_id", "rect_path_id"):
                    try:
                        keep_pids.add(int(getattr(el, attr, 0) or 0))
                    except Exception:
                        pass
                if vo is not None:
                    try:
                        if bool(vo.get("ksp_user_added")):
                            keep_names.add(nm)
                            eg = str(vo.get("ksp_export_go_name") or "").strip()
                            if eg:
                                keep_names.add(eg)
                            if nm and "_mrg" in nm.lower():
                                head = nm.split("_")[0]
                                if head.lower().startswith("text"):
                                    keep_names.add(head)
                            for attr in ("go_path_id", "mb_path_id", "rect_path_id"):
                                try:
                                    keep_pids.add(int(getattr(vo.ksp_ui, attr, 0) or 0))
                                except Exception:
                                    pass
                    except Exception:
                        pass
        except Exception:
            keep_names = set()
            keep_pids = set()
        keep_pids.discard(0)
        if _norm(ap) in cont:
            # Prefab already in UnityFS — still register Asset in *_bundle.xml
            # or KSPediaController cannot resolve the Screen AssetPath.
            ensure_assets.append((sid, ap))
            # Prior bug: blank NewPage was a full Storage clone. Strip content
            # UI on export so re-save fixes already-broken packs.
            if blank:
                n_off = _strip_prefab_content_ui(
                    env, ap, keep_names=keep_names, keep_pids=keep_pids,
                )
                if _disable_title_screen_root_image(env, ap):
                    n_off = max(int(n_off or 0), 1)
                if n_off:
                    stripped_blank = True
                    print(
                        "INFO: KSP export: stripped %d content GO(s) from blank %s"
                        % (n_off, sid)
                    )
            continue
        ok = False
        # Grafted pages: copy the *source* page prefab (AircraftBasicsCoL etc.),
        # not an empty TitleScreen shell — otherwise the game shows blank.
        g_ksp, g_ap = _graft_source_meta_from_node(node)
        if (not blank) and g_ksp and os.path.isfile(g_ksp) and g_ap:
            try:
                from ..import_ksp.bundle import load_env_for_export
                loaded = load_env_for_export(g_ksp)
                # load_env_for_export returns (path, env)
                src_env = loaded[1] if isinstance(loaded, tuple) else loaded
                ok = clone_prefab_from_env(
                    src_env, g_ap, env, ap, new_go_name=sid,
                )
                if ok:
                    print(
                        "INFO: KSP export: grafted prefab from %s (%s) -> %s"
                        % (os.path.basename(g_ksp), g_ap, ap)
                    )
            except Exception as ex:
                print("WARNING: graft prefab copy failed (%s): %s" % (sid, ex))
                ok = False
        if not ok:
            ok = clone_prefab_in_env(env, donor_path, ap, new_go_name=sid)
            if ok and blank:
                n_off = _strip_prefab_content_ui(
                    env, ap, keep_names=keep_names, keep_pids=keep_pids,
                )
                if _disable_title_screen_root_image(env, ap):
                    n_off = max(int(n_off or 0), 1)
                print(
                    "INFO: KSP export: blank page %s from shell %s "
                    "(deactivated %d content GO(s))"
                    % (sid, os.path.basename(donor_path), n_off)
                )
        if ok:
            cloned += 1
            cont[_norm(ap)] = True
            ensure_assets.append((sid, ap))
        else:
            errors.append(sid)

    # Do NOT re-register every container prefab into _bundle.xml — that dirties
    # GEP/JNSQ UnityFS and forces a full UnityPy save that strips streamed
    # textures (~200MB → a few MB). Only TOC-driven ensure_assets above.

    # Only patch bundle.xml when clones happened or UrlName / Assets missing.
    env_dirty = cloned > 0 or stripped_blank
    need_xml = False
    try:
        obj, _name, data = _find_textasset_by_name_substr(env, "_bundle")
        if obj is not None and data is not None:
            raw = getattr(data, "script", None) or getattr(data, "m_Script", b"")
            if isinstance(raw, bytes):
                text = raw.decode("utf-8", "replace")
            else:
                text = str(raw or "")
            root = ET.fromstring(text)
            cur_url = (root.get("UrlName") or root.get("Name") or "").strip()
            if host_stem and cur_url.lower() != host_stem.lower():
                need_xml = True
            existing = {
                _norm(el.get("Path") or "")
                for el in root.findall(".//Asset")
            }
            for _an, ap in ensure_assets:
                if _norm(ap) and _norm(ap) not in existing:
                    need_xml = True
                    break
        elif host_stem:
            need_xml = True
    except Exception:
        need_xml = cloned > 0 or bool(ensure_assets)

    if cloned or need_xml or stripped_blank:
        if update_bundle_definition_xml(
            env, url_name=host_stem, ensure_assets=ensure_assets,
        ):
            env_dirty = True
        elif cloned or stripped_blank:
            env_dirty = True
        elif need_xml and ensure_assets:
            env_dirty = True
    return cloned, errors, env_dirty


# Keep a tiny helper for tests / call sites that only need stem aliases.
def _pack_name_aliases(*stems) -> Set[str]:
    import re

    out: Set[str] = set()
    for raw in stems:
        s = (raw or "").strip().lower()
        if not s:
            continue
        out.add(s)
        m = re.match(r"^(?P<base>.+?)_(?P<loc>[a-z]{2}(?:-[a-z]{2})?)$", s, re.I)
        if m:
            out.add(m.group("base").lower())
    return out


def _prefab_local_path_ids(env, asset_path: str) -> Set[int]:
    """Local path_ids belonging to one container prefab (preload slice)."""
    out: Set[int] = set()
    ab = _find_assetbundle_obj(env)
    if ab is None:
        return out
    try:
        tt = _assetbundle_typetree(ab)
    except Exception:
        return out
    want = _norm(asset_path)
    info = None
    for entry in tt.get("m_Container") or []:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            if _norm(str(entry[0])) == want:
                info = entry[1]
                break
    if info is None:
        return out
    if not isinstance(info, dict):
        try:
            info = {
                "preloadIndex": int(getattr(info, "preloadIndex", 0) or 0),
                "preloadSize": int(getattr(info, "preloadSize", 0) or 0),
            }
        except Exception:
            return out
    try:
        pidx = int(info.get("preloadIndex", 0) or 0)
        psize = int(info.get("preloadSize", 0) or 0)
    except Exception:
        return out
    preload = list(tt.get("m_PreloadTable") or [])
    if psize <= 0 or pidx < 0 or (pidx + psize) > len(preload):
        return out
    for pp in preload[pidx : pidx + psize]:
        if isinstance(pp, dict):
            fid = int(pp.get("m_FileID", 0) or 0)
            pid = int(pp.get("m_PathID", 0) or 0)
        else:
            fid = int(getattr(pp, "m_FileID", 0) or 0)
            pid = int(getattr(pp, "m_PathID", 0) or 0)
        if fid == 0 and pid:
            out.add(pid)
    return out


def prefab_ui_ids_by_name(env, asset_path: str) -> Dict[str, dict]:
    """Uniquely-named UI elements inside one prefab -> mb/rect/go.

    Grafted pages clear Blender path ids then Export clones a donor prefab
    (often Configuration). Scope the map to this AssetPath's preload slice.
    """
    local = _prefab_local_path_ids(env, asset_path)
    if not local:
        return {}
    try:
        from ..import_ksp.bundle import _collect_ui
        elements, _rep = _collect_ui(env, {})
    except Exception:
        return {}
    counts: Dict[str, int] = {}
    hits = []
    for el in elements or []:
        try:
            gid = int(getattr(el, "go_path_id", 0) or 0)
            mid = int(getattr(el, "mb_path_id", 0) or 0)
            rid = int(getattr(el, "rect_path_id", 0) or 0)
        except Exception:
            continue
        if not ((gid and gid in local) or (mid and mid in local) or (rid and rid in local)):
            continue
        name = (getattr(el, "name", "") or "").strip()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
        hits.append((name, {"mb": mid, "rect": rid, "go": gid}))
    return {n: d for n, d in hits if counts.get(n, 0) == 1}


def bind_ui_elements_to_page_prefabs(env, kb) -> int:
    """Assign mb/rect path ids on list rows (+ viewport) from each page prefab."""
    if env is None or kb is None:
        return 0
    from ..import_ksp.unityfs_catalog import node_asset_path, node_screen_id

    by_screen: Dict[str, dict] = {}
    for node in list(getattr(kb, "toc_nodes", []) or []):
        sid = (node_screen_id(node) or "").strip()
        if not sid:
            continue
        ap = (node_asset_path(node) or "").strip()
        if not ap:
            continue
        if sid not in by_screen:
            by_screen[sid] = prefab_ui_ids_by_name(env, ap)

    n = 0
    for el in list(getattr(kb, "ui_elements", []) or []):
        kind = str(getattr(el, "kind", "") or "")
        if kind not in ("text", "image"):
            continue
        screen = (getattr(el, "page_screen", "") or "").strip()
        vo = getattr(el, "viewport_object", None)
        if not screen and vo is not None:
            try:
                cur = vo
                while cur is not None and not screen:
                    try:
                        screen = str(cur.get("ksp_page", "") or "")
                    except Exception:
                        pass
                    try:
                        cur = cur.parent
                    except Exception:
                        break
            except Exception:
                pass
        amap = by_screen.get(screen) or {}
        if not amap:
            continue
        # User Add/Load/Duplicate: inject already assigned unique mids.
        # Never re-bind by stripping "_Configuration" etc. — that remapped
        # ConfT3_Configuration → stock ConfT3 and overwrote RectTransform /
        # text (blue rich-text fragments jumped; duplicate header/body).
        try:
            if vo is not None and bool(vo.get("ksp_user_added")) and not bool(
                vo.get("ksp_grafted")
            ):
                continue
        except Exception:
            pass
        export_name = ""
        if vo is not None:
            try:
                export_name = str(vo.get("ksp_export_go_name") or "").strip()
            except Exception:
                export_name = ""
        if not export_name:
            export_name = (getattr(el, "name", "") or "").strip()
            if screen and export_name.endswith("_" + screen):
                export_name = export_name[: -(len(screen) + 1)]
        ids = amap.get(export_name) if export_name else None
        if not ids:
            raw = (getattr(el, "name", "") or "").strip()
            ids = amap.get(raw)
        # Fuzzy head match is dangerous (LoadImage stem → Configuration) — only
        # for grafted stock copies that still carry ksp_export_go_name.
        if not ids and export_name and "_" in export_name:
            is_graft = False
            try:
                is_graft = bool(vo.get("ksp_grafted")) if vo is not None else False
            except Exception:
                is_graft = False
            if is_graft:
                head = export_name.split("_")[0]
                if head in amap:
                    ids = amap[head]
        if not ids:
            continue
        mid = int(ids.get("mb") or 0)
        rid = int(ids.get("rect") or 0)
        gid = int(ids.get("go") or 0)
        if not (mid or rid):
            continue
        try:
            if mid:
                el.mb_path_id = str(mid)
            if rid:
                el.rect_path_id = str(rid)
            if gid and hasattr(el, "go_path_id"):
                el.go_path_id = str(gid)
            n += 1
        except Exception:
            pass
        if vo is not None:
            try:
                ui = vo.ksp_ui
                if mid:
                    ui.mb_path_id = str(mid)
                if rid:
                    ui.rect_path_id = str(rid)
                if gid and hasattr(ui, "go_path_id"):
                    ui.go_path_id = str(gid)
            except Exception:
                pass
    return n



def _pptr0(pid: int) -> dict:
    return {"m_FileID": 0, "m_PathID": int(pid)}


def _go_component_ids(go_tree: dict) -> List[int]:
    out: List[int] = []
    for c in go_tree.get("m_Component") or []:
        if isinstance(c, dict):
            cref = c.get("component") or c
        else:
            cref = c
        try:
            if isinstance(cref, dict):
                fid = int(cref.get("m_FileID", 0) or 0)
                pid = int(cref.get("m_PathID", 0) or 0)
            else:
                fid = int(getattr(cref, "m_FileID", 0) or 0)
                pid = int(getattr(cref, "m_PathID", 0) or 0)
        except Exception:
            continue
        if fid == 0 and pid:
            out.append(pid)
    return out


def _rect_child_count(assets_file, rid: int) -> int:
    if not rid:
        return 0
    obj = assets_file.objects.get(int(rid))
    if obj is None:
        return 0
    try:
        kids = obj.read_typetree().get("m_Children") or []
        return len(kids) if isinstance(kids, list) else 0
    except Exception:
        return 0


def _canvas_renderer_ids(assets_file, comp_ids: List[int]) -> List[int]:
    out = []
    for cid in comp_ids:
        cob = assets_file.objects.get(int(cid))
        if cob is None:
            continue
        try:
            if cob.type.name == "CanvasRenderer":
                out.append(int(cid))
        except Exception:
            continue
    return out


def _rewrite_go_components(assets_file, gid: int, keep_pids: List[int]) -> None:
    """Keep only listed components on a cloned GameObject."""
    gob = assets_file.objects.get(int(gid))
    if gob is None:
        return
    try:
        gt = gob.read_typetree()
    except Exception:
        return
    keep = set(int(p) for p in keep_pids if p)
    new_comp = []
    for c in list(gt.get("m_Component") or []):
        if isinstance(c, dict):
            cref = c.get("component") or c
        else:
            cref = c
        try:
            pid = int(cref.get("m_PathID") or 0) if isinstance(cref, dict) else 0
        except Exception:
            pid = 0
        if pid in keep:
            new_comp.append(c)
    gt["m_Component"] = new_comp
    try:
        gob.save_typetree(gt)
        _rebind_reader_to_data(gob)
    except Exception:
        pass


def _clear_rect_children(assets_file, rid: int) -> None:
    """Injected clones must be leaves — donor m_Children still point at stock texts."""
    if not rid:
        return
    rob = assets_file.objects.get(int(rid))
    if rob is None:
        return
    try:
        rt = rob.read_typetree()
    except Exception:
        return
    kids = rt.get("m_Children")
    if not kids:
        return
    rt["m_Children"] = []
    try:
        rob.save_typetree(rt)
        _rebind_reader_to_data(rob)
    except Exception:
        pass


def _find_page_container_info(env, asset_path: str):
    ab = _find_assetbundle_obj(env)
    if ab is None:
        return None, None, None, None
    try:
        tt = _assetbundle_typetree(ab)
    except Exception:
        return None, None, None, None
    want = _norm(asset_path)
    container = list(tt.get("m_Container") or [])
    for i, entry in enumerate(container):
        if not (isinstance(entry, (list, tuple)) and len(entry) >= 2):
            continue
        if _norm(str(entry[0])) != want:
            continue
        info = entry[1]
        if not isinstance(info, dict):
            try:
                info = {
                    "preloadIndex": int(getattr(info, "preloadIndex", 0) or 0),
                    "preloadSize": int(getattr(info, "preloadSize", 0) or 0),
                    "asset": {
                        "m_FileID": int(getattr(getattr(info, "asset", None), "m_FileID", 0) or 0),
                        "m_PathID": int(getattr(getattr(info, "asset", None), "m_PathID", 0) or 0),
                    },
                }
            except Exception:
                return None, None, None, None
        return ab, tt, i, info
    return None, None, None, None


def _append_ids_to_prefab_preload(env, asset_path: str, new_pids: List[int]) -> bool:
    """Extend an existing page prefab preload slice with new local path_ids."""
    if not new_pids:
        return True
    ab, tt, cidx, info = _find_page_container_info(env, asset_path)
    if ab is None or info is None:
        return False
    preload = list(tt.get("m_PreloadTable") or [])
    container = list(tt.get("m_Container") or [])
    try:
        pidx = int(info.get("preloadIndex", 0) or 0)
        psize = int(info.get("preloadSize", 0) or 0)
    except Exception:
        return False
    insert_at = pidx + psize
    new_entries = [{"m_FileID": 0, "m_PathID": int(p)} for p in new_pids]
    preload[insert_at:insert_at] = new_entries
    n = len(new_entries)
    info = dict(info)
    info["preloadSize"] = psize + n
    container[cidx] = [container[cidx][0], info]
    # Shift later slices
    for j, entry in enumerate(container):
        if j == cidx:
            continue
        if not (isinstance(entry, (list, tuple)) and len(entry) >= 2):
            continue
        inf = entry[1]
        if not isinstance(inf, dict):
            continue
        try:
            oi = int(inf.get("preloadIndex", 0) or 0)
        except Exception:
            continue
        if oi >= insert_at:
            inf = dict(inf)
            inf["preloadIndex"] = oi + n
            container[j] = [entry[0], inf]
    tt["m_PreloadTable"] = preload
    tt["m_Container"] = container
    ab.save_typetree(tt)
    _rebind_reader_to_data(ab)
    return True


def _pick_ui_donor(env, asset_path: str, kind: str):
    """Return (go_id, rect_id, mb_id, sprite_id, texture_id) for a donor on page.

    Includes inactive GameObjects — blank NewPage strips stock UI to inactive,
    but those GOs are still the only local Text/Image templates to clone from.
    """
    local = _prefab_local_path_ids(env, asset_path)
    if not local:
        print(
            "WARNING: KSP inject: no prefab objects for %s"
            % (asset_path or "?")
        )
        return None
    kind = (kind or "").strip().lower()
    if kind not in ("text", "image"):
        return None

    by_id = {}
    assets_file = None
    for o in env.objects:
        try:
            by_id[int(o.path_id)] = o
            if assets_file is None:
                assets_file = o.assets_file
        except Exception:
            continue

    def _script_hint(mb_tree: dict) -> str:
        # Best-effort: Unity UI Text has m_Text; Image has m_Sprite.
        if not isinstance(mb_tree, dict):
            return ""
        if "m_Text" in mb_tree or "m_FontData" in mb_tree:
            return "text"
        if "m_Sprite" in mb_tree or "m_Type" in mb_tree and "m_Color" in mb_tree:
            if "m_Sprite" in mb_tree:
                return "image"
        return ""

    best = None
    page_root_fallback = None
    for gid in list(local):
        obj = by_id.get(int(gid))
        if obj is None:
            continue
        try:
            if obj.type.name != "GameObject":
                continue
            go_tree = obj.read_typetree()
        except Exception:
            continue
        name = str(go_tree.get("m_Name") or "")
        rid = mid = sid = tid = 0
        ek = ""
        for cid in _go_component_ids(go_tree):
            cob = by_id.get(int(cid))
            if cob is None:
                continue
            try:
                tname = cob.type.name
            except Exception:
                continue
            if tname == "RectTransform" and not rid:
                rid = int(cid)
            elif tname == "MonoBehaviour" and not mid:
                try:
                    mb = cob.read_typetree()
                except Exception:
                    continue
                hint = _script_hint(mb)
                if hint and hint != kind:
                    continue
                if not hint:
                    # Fallback: accept first MB when kind matches common fields
                    if kind == "text" and "m_Text" not in mb:
                        continue
                    if kind == "image" and "m_Sprite" not in mb:
                        continue
                ek = kind
                mid = int(cid)
                if kind == "image":
                    sp = mb.get("m_Sprite")
                    if isinstance(sp, dict):
                        try:
                            if int(sp.get("m_FileID", 0) or 0) == 0:
                                sid = int(sp.get("m_PathID") or 0)
                        except Exception:
                            sid = 0
        if ek != kind or not (gid and mid and rid):
            continue
        # Prefer leaf Image/Text donors. Page-root (DatabaseScreen + Image)
        # is last resort: GEP pages often have ONLY that Image, and skipping
        # it made Load Image silently fail to enter the pack.
        try:
            if assets_file is not None and _is_page_root_image_go(
                assets_file, go_name=name, go_tree_pid=int(gid), screen_id="",
            ):
                if (
                    kind == "image"
                    and page_root_fallback is None
                    and sid
                ):
                    tid0 = _sprite_texture_pid(env, sid) or 0
                    page_root_fallback = (
                        int(gid), int(rid), int(mid), int(sid or 0), int(tid0 or 0),
                    )
                continue
        except Exception:
            pass
        if sid:
            tid = _sprite_texture_pid(env, sid) or 0
        score = 1
        # Prefer inactive stripped stock as template (still complete); avoid
        # already-user-cloned names when possible.
        low = name.lower()
        try:
            if go_tree.get("m_IsActive", True) in (False, 0, "false", "False"):
                score += 1
        except Exception:
            pass
        if kind == "image" and tid and tid in local:
            score += 3
        elif kind == "image" and sid and sid in local:
            score += 2
        if "background" in low or "bg" in low:
            score += 2
        # Leaf donors only — a rect that still lists stock texts as children
        # would steal them on heal even after GO rename.
        n_kids = 0
        try:
            n_kids = _rect_child_count(assets_file, rid) if assets_file else 0
        except Exception:
            n_kids = 0
        if n_kids == 0:
            score += 4
        else:
            score -= min(8, n_kids)
        if kind == "text" and any(
            low.startswith(p) for p in ("header", "subheader", "description", "st", "conf")
        ):
            score += 2
        if "_mrg" in low or low.startswith("new"):
            score -= 3
        cand = (score, int(gid), int(rid), int(mid), int(sid or 0), int(tid or 0))
        if best is None or cand[0] > best[0]:
            best = cand
    if best is None and page_root_fallback is not None:
        print(
            "INFO: KSP inject: no leaf Image on %s — cloning from page-root "
            "Image (children stripped)"
            % (asset_path or "?")
        )
        return page_root_fallback
    if best is None:
        # Fall back: any page in the same UnityFS (inactive allowed via typetree)
        try:
            from ..import_ksp.bundle import _collect_ui
            # Temporarily gather without relying on active-only collect: scan all
            # text/image MBs that look like UI and pick one with RectTransform.
            for o in env.objects:
                try:
                    if o.type.name != "GameObject":
                        continue
                    go_tree = o.read_typetree()
                except Exception:
                    continue
                name = str(go_tree.get("m_Name") or "")
                rid = mid = sid = tid = 0
                for cid in _go_component_ids(go_tree):
                    cob = by_id.get(int(cid))
                    if cob is None:
                        continue
                    try:
                        tname = cob.type.name
                    except Exception:
                        continue
                    if tname == "RectTransform" and not rid:
                        rid = int(cid)
                    elif tname == "MonoBehaviour" and not mid:
                        try:
                            mb = cob.read_typetree()
                        except Exception:
                            continue
                        if kind == "text" and "m_Text" not in mb:
                            continue
                        if kind == "image" and "m_Sprite" not in mb:
                            continue
                        mid = int(cid)
                        if kind == "image":
                            sp = mb.get("m_Sprite")
                            if isinstance(sp, dict):
                                try:
                                    if int(sp.get("m_FileID", 0) or 0) == 0:
                                        sid = int(sp.get("m_PathID") or 0)
                                except Exception:
                                    sid = 0
                if not (int(o.path_id) and mid and rid):
                    continue
                try:
                    if assets_file is not None and _is_page_root_image_go(
                        assets_file,
                        go_name=name,
                        go_tree_pid=int(o.path_id),
                        screen_id="",
                    ):
                        continue
                except Exception:
                    pass
                if sid:
                    tid = _sprite_texture_pid(env, sid) or 0
                return int(o.path_id), int(rid), int(mid), int(sid or 0), int(tid or 0)
        except Exception:
            pass
        return None
    _s, gid, rid, mid, sid, tid = best
    return gid, rid, mid, sid, tid


def _clone_ids_map(env, old_ids: List[int], id_map: Dict[int, int]) -> bool:
    assets_file = None
    for obj in env.objects:
        assets_file = obj.assets_file
        break
    if assets_file is None:
        return False
    rng = random.Random((hash(tuple(old_ids)) ^ len(old_ids)) & 0xFFFFFFFF)
    for old in old_ids:
        if old in id_map:
            continue
        new = _unused_path_id(assets_file, rng)
        id_map[old] = new
        assets_file.objects[new] = assets_file.objects[old]
    for old in old_ids:
        src = assets_file.objects.get(old)
        if src is None:
            return False
        new = id_map[old]
        try:
            del assets_file.objects[new]
        except Exception:
            pass
        try:
            assets_file.objects[new] = _clone_object_reader(src, new, id_map)
        except Exception:
            return False
    return True


def _set_go_name(env, go_pid: int, name: str) -> None:
    assets_file = None
    for obj in env.objects:
        assets_file = obj.assets_file
        break
    if assets_file is not None:
        obj = assets_file.objects.get(int(go_pid))
        if obj is not None:
            try:
                if obj.type.name == "GameObject":
                    _rename_gameobject(obj, name)
                    return
            except Exception:
                pass
    for obj in env.objects:
        try:
            if obj.type.name == "GameObject" and int(obj.path_id) == int(go_pid):
                _rename_gameobject(obj, name)
                return
        except Exception:
            continue


def _parent_rect_under(env, child_rect: int, father_rect: int) -> bool:
    """Set m_Father on child and append to father's m_Children."""
    child_obj = father_obj = None
    for obj in env.objects:
        try:
            if obj.type.name != "RectTransform":
                continue
            pid = int(obj.path_id)
            if pid == int(child_rect):
                child_obj = obj
            elif pid == int(father_rect):
                father_obj = obj
        except Exception:
            continue
    if child_obj is None or father_obj is None:
        return False
    try:
        ct = child_obj.read_typetree()
        ft = father_obj.read_typetree()
    except Exception:
        return False
    ct["m_Father"] = _pptr0(father_rect)
    ct["m_Children"] = []
    kids = list(ft.get("m_Children") or [])
    # Avoid duplicate
    already = False
    for k in kids:
        try:
            if isinstance(k, dict) and int(k.get("m_PathID") or 0) == int(child_rect):
                already = True
                break
        except Exception:
            pass
    if not already:
        kids.append(_pptr0(child_rect))
    ft["m_Children"] = kids
    child_obj.save_typetree(ct)
    _rebind_reader_to_data(child_obj)
    father_obj.save_typetree(ft)
    _rebind_reader_to_data(father_obj)
    return True


def _page_root_rect_id(env, asset_path: str) -> int:
    ab, tt, _i, info = _find_page_container_info(env, asset_path)
    if info is None:
        return 0
    try:
        root_go = int((info.get("asset") or {}).get("m_PathID") or 0)
    except Exception:
        root_go = 0
    if not root_go:
        return 0
    for obj in env.objects:
        try:
            if obj.type.name != "GameObject" or int(obj.path_id) != root_go:
                continue
            tree = obj.read_typetree()
        except Exception:
            continue
        for cid in _go_component_ids(tree):
            for o2 in env.objects:
                try:
                    if int(o2.path_id) == cid and o2.type.name == "RectTransform":
                        return cid
                except Exception:
                    continue
    return 0


def _sprite_texture_pid(env, sprite_pid: int) -> int:
    if not sprite_pid:
        return 0
    for obj in env.objects:
        try:
            if obj.type.name != "Sprite" or int(obj.path_id) != int(sprite_pid):
                continue
            tree = obj.read_typetree()
        except Exception:
            continue
        # Common layouts
        for key in ("m_RD", "m_RenderData"):
            rd = tree.get(key)
            if isinstance(rd, dict):
                tex = rd.get("texture") or rd.get("m_Texture")
                if isinstance(tex, dict):
                    try:
                        if int(tex.get("m_FileID", 0) or 0) == 0:
                            return int(tex.get("m_PathID") or 0)
                    except Exception:
                        pass
        tex = tree.get("m_Texture")
        if isinstance(tex, dict):
            try:
                if int(tex.get("m_FileID", 0) or 0) == 0:
                    return int(tex.get("m_PathID") or 0)
            except Exception:
                pass
        # Deep search first Texture2D-looking PPtr
        found = [0]

        def walk(n):
            if found[0]:
                return
            if isinstance(n, dict):
                if "m_PathID" in n or "m_PathId" in n:
                    key = "m_PathID" if "m_PathID" in n else "m_PathId"
                    try:
                        fid = int(n.get("m_FileID", n.get("m_FileId", 0)) or 0)
                        pid = int(n.get(key) or 0)
                    except Exception:
                        fid = pid = 0
                    if fid == 0 and pid:
                        for o in env.objects:
                            try:
                                if int(o.path_id) == pid and o.type.name == "Texture2D":
                                    found[0] = pid
                                    return
                            except Exception:
                                continue
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)

        walk(tree)
        return found[0]
    return 0


def inject_ui_element_into_page_prefab(
    env,
    asset_path: str,
    *,
    kind: str,
    go_name: str,
) -> Dict[str, int]:
    """Clone a donor Image/Text GO into the page prefab. Returns id map."""
    empty: Dict[str, int] = {}
    donor = _pick_ui_donor(env, asset_path, kind)
    if not donor:
        print(
            "WARNING: KSP inject: no %s donor on %s — new UI will not be packed"
            % (kind or "?", asset_path or "?")
        )
        return empty
    gid, rid, mid, sid, tid = donor
    assets_file = None
    for obj in env.objects:
        assets_file = obj.assets_file
        break
    if assets_file is None:
        return empty

    go_obj = assets_file.objects.get(gid)
    if go_obj is None:
        return empty
    try:
        go_tree = go_obj.read_typetree()
    except Exception:
        return empty
    comp_ids = _go_component_ids(go_tree)
    # Clone only the UI leaf (GO + Rect + target MB + CanvasRenderer).
    # Copying DatabaseScreen / extra Text / child pointers from the page root
    # duplicated headers and dragged PBS blue overlays onto the new image.
    keep_src = set()
    if rid:
        keep_src.add(int(rid))
    if mid:
        keep_src.add(int(mid))
    for cr in _canvas_renderer_ids(assets_file, comp_ids):
        keep_src.add(int(cr))
    old_ids: List[int] = [gid] + [c for c in keep_src if c]

    # For images: clone sprite+texture so we can rewrite pixels safely.
    clone_sid = clone_tid = 0
    if kind == "image":
        clone_sid = sid
        clone_tid = tid or _sprite_texture_pid(env, sid)
        # Do NOT fall back to a random Texture2D/Sprite from the whole bundle —
        # that pulled Configuration/atlas art into Load Image on other pages.
        if not clone_tid or not clone_sid:
            print(
                "WARNING: KSP inject: donor Image on %s has no Sprite/Texture "
                "— aborting Load Image clone"
                % (asset_path or "?")
            )
            return empty
        if clone_sid and clone_sid not in old_ids:
            old_ids.append(clone_sid)
        if clone_tid and clone_tid not in old_ids:
            old_ids.append(clone_tid)

    id_map: Dict[int, int] = {}
    if not _clone_ids_map(env, old_ids, id_map):
        return empty

    new_gid = id_map.get(gid, 0)
    new_rid = id_map.get(rid, 0)
    new_mid = id_map.get(mid, 0)
    new_sid = id_map.get(clone_sid, 0) if clone_sid else 0
    new_tid = id_map.get(clone_tid, 0) if clone_tid else 0
    if not (new_gid and new_rid and new_mid):
        return empty

    # Drop leftover donor components (DatabaseScreen, extra Text) and child
    # rect pointers that still reference stock overlays.
    keep_new = [new_rid, new_mid]
    for old_cr in list(keep_src):
        if old_cr in (gid, rid, mid):
            continue
        mapped = id_map.get(old_cr)
        if mapped:
            keep_new.append(int(mapped))
    _rewrite_go_components(assets_file, new_gid, keep_new)
    _clear_rect_children(assets_file, new_rid)

    # Empty streamed donor clones often have 0×0 Texture2D; copy donor size
    # so keep_unity_size + sprite mesh stay crash-safe.
    if kind == "image" and clone_tid and new_tid:
        try:
            src_tex = assets_file.objects.get(int(clone_tid))
            dst_tex = assets_file.objects.get(int(new_tid))
            if src_tex is not None and dst_tex is not None:
                sd = src_tex.read()
                dd = dst_tex.read()
                dw = int(getattr(sd, "m_Width", 0) or 0)
                dh = int(getattr(sd, "m_Height", 0) or 0)
                if dw >= 4 and dh >= 4:
                    dd.m_Width = dw
                    dd.m_Height = dh
                    try:
                        dd.save()
                    except Exception:
                        pass
                    try:
                        from ..import_ksp.bundle import _rebind_texture_reader
                        _rebind_texture_reader(dst_tex)
                    except Exception:
                        _rebind_reader_to_data(dst_tex)
        except Exception:
            pass

    if go_name:
        go_name = _unique_prefab_go_name(env, go_name)
        _set_go_name(env, new_gid, go_name)

    # Donor on blank pages is often inactive (stripped stock). Clones must show.
    try:
        go_new = assets_file.objects.get(new_gid)
        if go_new is not None:
            gt = go_new.read_typetree()
            if gt.get("m_IsActive", True) is False:
                gt["m_IsActive"] = True
                go_new.save_typetree(gt)
                _rebind_reader_to_data(go_new)
    except Exception:
        pass

    # Point Image.m_Sprite at cloned sprite when we made one
    if kind == "image" and new_sid and new_mid:
        for obj in env.objects:
            try:
                if obj.type.name != "MonoBehaviour" or int(obj.path_id) != new_mid:
                    continue
                tree = obj.read_typetree()
                if "m_Sprite" in tree:
                    tree["m_Sprite"] = _pptr0(new_sid)
                    obj.save_typetree(tree)
                break
            except Exception:
                continue
        # Point sprite at cloned texture
        if new_tid and new_sid:
            for obj in env.objects:
                try:
                    if obj.type.name != "Sprite" or int(obj.path_id) != new_sid:
                        continue
                    tree = obj.read_typetree()
                    changed = [False]

                    def fix(n):
                        if isinstance(n, dict):
                            if ("m_PathID" in n or "m_PathId" in n) and (
                                "m_FileID" in n or "m_FileId" in n
                            ):
                                key = "m_PathID" if "m_PathID" in n else "m_PathId"
                                try:
                                    fid = int(n.get("m_FileID", n.get("m_FileId", 0)) or 0)
                                    pid = int(n.get(key) or 0)
                                except Exception:
                                    return
                                if fid == 0 and pid == clone_tid:
                                    n[key] = new_tid
                                    changed[0] = True
                            for v in n.values():
                                fix(v)
                        elif isinstance(n, list):
                            for v in n:
                                fix(v)

                    fix(tree)
                    # Full-frame sprite: atlas donors keep a tiny textureRect →
                    # user PNG looks cropped / wrong aspect in-game & Blender.
                    try:
                        tw = th = 0
                        tex_obj = assets_file.objects.get(new_tid) if new_tid else None
                        if tex_obj is not None:
                            try:
                                td = tex_obj.read()
                                tw = int(getattr(td, "m_Width", 0) or 0)
                                th = int(getattr(td, "m_Height", 0) or 0)
                            except Exception:
                                tw = th = 0
                        if tw > 0 and th > 0:
                            for rect_key in ("m_Rect", "textureRect"):
                                if rect_key in tree and isinstance(tree[rect_key], dict):
                                    r = dict(tree[rect_key])
                                    r["x"] = 0.0
                                    r["y"] = 0.0
                                    r["width"] = float(tw)
                                    r["height"] = float(th)
                                    tree[rect_key] = r
                                    changed[0] = True
                            rd = tree.get("m_RD") or tree.get("m_RenderData")
                            if isinstance(rd, dict):
                                rd = dict(rd)
                                for rect_key in ("textureRect", "m_TextureRect"):
                                    if rect_key in rd and isinstance(rd[rect_key], dict):
                                        r = dict(rd[rect_key])
                                        r["x"] = r.get("x", 0.0) * 0.0
                                        r["y"] = 0.0
                                        r["width"] = float(tw)
                                        r["height"] = float(th)
                                        rd[rect_key] = r
                                        changed[0] = True
                                if "m_RD" in tree:
                                    tree["m_RD"] = rd
                                elif "m_RenderData" in tree:
                                    tree["m_RenderData"] = rd
                    except Exception:
                        pass
                    if changed[0]:
                        obj.save_typetree(tree)
                        _rebind_reader_to_data(obj)
                    break
                except Exception:
                    continue

    father = _page_root_rect_id(env, asset_path)
    if not father:
        # fallback: donor's father
        for obj in env.objects:
            try:
                if obj.type.name == "RectTransform" and int(obj.path_id) == rid:
                    tree = obj.read_typetree()
                    father = int((tree.get("m_Father") or {}).get("m_PathID") or 0)
                    break
            except Exception:
                continue
    if father and new_rid:
        # Remap father if it was cloned (shouldn't be) — use original father id
        _parent_rect_under(env, new_rid, father)

    # Donor Image rects are often sizeDelta 0×0 (stretch shell). Clones with
    # point anchors need an explicit size or KSPedia draws nothing.
    if kind == "image" and new_rid:
        try:
            w, h = _sprite_wh(assets_file, new_sid) if new_sid else (0.0, 0.0)
            if w < 1.0 or h < 1.0:
                w, h = _texture_wh(assets_file, new_tid)
            if w >= 1.0 and h >= 1.0:
                from ..import_ksp.bundle import apply_rect_transform
                apply_rect_transform(
                    env, int(new_rid), size_delta=(float(w), float(h)),
                )
        except Exception:
            pass

    new_pids = [id_map[o] for o in old_ids if o in id_map]
    if not _append_ids_to_prefab_preload(env, asset_path, new_pids):
        # Still usable for writes even if preload patch failed
        pass

    return {
        "go": new_gid,
        "rect": new_rid,
        "mb": new_mid,
        "sprite": new_sid,
        "texture": new_tid,
    }


def _deactivate_injected_el(env, el) -> None:
    """Hide a LOCAL-only GO that a previous export cloned into this template."""
    from ..import_ksp import ui_roundtrip as _uir

    mid = 0
    try:
        mid = int(getattr(el, "mb_path_id", 0) or 0)
    except Exception:
        mid = 0
    if mid:
        try:
            _uir.set_game_object_active(env, mid, False)
        except Exception:
            pass
    names = []
    try:
        vo = getattr(el, "viewport_object", None)
        if vo is not None:
            n = str(vo.get("ksp_export_go_name") or "").strip()
            if n:
                names.append(n)
    except Exception:
        pass
    try:
        n = str(getattr(el, "name", "") or "").strip()
        if n and n not in names:
            names.append(n)
    except Exception:
        pass
    for name in names:
        if name.lower() in ("image", "text", ""):
            continue
        try:
            _uir.set_game_object_active_by_name(env, name, False)
        except Exception:
            pass


def inject_user_ui_elements(env, kb, export_locale=None) -> int:
    """For Blender UI rows with mid==0, clone donor into page prefab and bind ids."""
    if env is None or kb is None:
        return 0
    from ..import_ksp.unityfs_catalog import node_asset_path, node_screen_id
    from ..import_ksp.kspedia_index import default_asset_path_for_screen

    screen_ap: Dict[str, str] = {}
    for node in list(getattr(kb, "toc_nodes", []) or []):
        sid = (node_screen_id(node) or "").strip()
        if not sid:
            continue
        ap = (node_asset_path(node) or "").strip() or default_asset_path_for_screen(sid)
        screen_ap[sid] = ap

    n = 0
    by_id = {}
    try:
        by_id = {int(o.path_id): o for o in env.objects}
    except Exception:
        by_id = {}

    def _go_name_at(pid: int) -> str:
        obj = by_id.get(int(pid or 0))
        if obj is None:
            return ""
        try:
            if obj.type.name != "GameObject":
                return ""
            return str(obj.read_typetree().get("m_Name") or "")
        except Exception:
            return ""

    for el in list(getattr(kb, "ui_elements", []) or []):
        kind = str(getattr(el, "kind", "") or "")
        if kind not in ("text", "image"):
            continue
        skip_this = False
        try:
            if bool(getattr(el, "missing_in_locale", False)):
                skip_this = True
        except Exception:
            pass
        try:
            vo_ship = getattr(el, "viewport_object", None)
            loc_now = (
                str(export_locale or "")
                or str(getattr(kb, "active_locale", "") or "")
                or str(getattr(kb, "locale", "") or "")
            ).strip().lower()
            skip_loc = False
            if vo_ship is not None:
                try:
                    from ..import_ksp.locale_buffers import is_forgotten_in_locale
                    if loc_now and is_forgotten_in_locale(vo_ship, loc_now):
                        skip_loc = True
                except Exception:
                    pass
                shipped = str(vo_ship.get("ksp_shipped_locales") or "").strip()
                if shipped and loc_now:
                    allowed = {
                        x.strip().lower() for x in shipped.split(",") if x.strip()
                    }
                    if loc_now not in allowed:
                        skip_loc = True
            if skip_loc:
                skip_this = True
        except Exception:
            pass
        try:
            mid = int(getattr(el, "mb_path_id", 0) or 0)
        except Exception:
            mid = 0
        # Stale mid from another bundle, or mid bound to a stock shell GO
        # (export_go_name Image → donor Image) while this is merge/user content:
        # force reinject under a unique name.
        if mid:
            if mid not in by_id:
                mid = 0
            else:
                try:
                    from ..import_ksp.locale_buffers import (
                        SHIPPED_GO_MARK,
                        shipped_go_display_name,
                    )
                    vo_chk = getattr(el, "viewport_object", None)
                    eln = (getattr(el, "name", "") or "").strip()
                    want = ""
                    if eln and "_mrg" in eln.lower():
                        want = eln
                    elif vo_chk is not None:
                        want = str(vo_chk.get("ksp_export_go_name") or "").strip()
                    if not want:
                        want = eln
                    got = ""
                    # Resolve GO from mb → GameObject via typetree m_GameObject
                    mb_obj = by_id.get(mid)
                    if mb_obj is not None:
                        try:
                            mbt = mb_obj.read_typetree()
                            gp = mbt.get("m_GameObject") or {}
                            if isinstance(gp, dict):
                                got = _go_name_at(int(gp.get("m_PathID") or 0))
                        except Exception:
                            got = ""
                    userish = False
                    if vo_chk is not None:
                        userish = bool(vo_chk.get("ksp_user_added"))
                    if userish:
                        export_n = ""
                        if vo_chk is not None:
                            export_n = str(
                                vo_chk.get("ksp_export_go_name") or ""
                            ).strip()
                        # Encoded LOCAL names (NewImage__kS_de-de) must match
                        # the Unity GO, not the clean Blender list name.
                        if SHIPPED_GO_MARK in export_n:
                            want = export_n
                        else:
                            want = eln or want
                    if userish and want and got:
                        same = (
                            want == got
                            or shipped_go_display_name(want)
                            == shipped_go_display_name(got)
                        )
                        if not same:
                            mid = 0
                    elif userish and eln and ("_mrg" in eln.lower()) and got and "_mrg" not in got.lower():
                        mid = 0
                except Exception:
                    pass
        if mid:
            if skip_this:
                _deactivate_injected_el(env, el)
            continue
        # Only inject user-created rows (Add/Load/Duplicate). Grafted stock
        # that failed name-bind must not spawn extra donor clones.
        vo_pre = getattr(el, "viewport_object", None)
        try:
            cur = vo_pre
            while cur is not None:
                if cur.get("ksp_grafted") or cur.get("ksp_graft_source_ksp"):
                    vo_pre = None  # signal skip
                    break
                try:
                    cur = cur.parent
                except Exception:
                    break
        except Exception:
            pass
        if vo_pre is None and getattr(el, "viewport_object", None) is not None:
            # grafted — skip inject
            continue
        is_user = False
        try:
            if vo_pre is not None and bool(vo_pre.get("ksp_user_added")):
                if not bool(vo_pre.get("ksp_grafted")):
                    is_user = True
        except Exception:
            pass
        # Merge-into-page copies are user_added with *_mrg names (not grafted TOC).
        if not is_user:
            try:
                nm0 = (getattr(el, "name", "") or "")
                if "_mrg" in nm0.lower() and vo_pre is not None and bool(
                    vo_pre.get("ksp_user_added")
                ):
                    is_user = True
            except Exception:
                pass
        if not is_user:
            try:
                gid0 = int(getattr(el, "go_path_id", 0) or 0)
            except Exception:
                gid0 = 0
            if gid0:
                continue
            # bare mid==0 without viewport flag — only if explicitly user-added name
            nm = (getattr(el, "name", "") or "")
            if nm.startswith("NewText") or nm.startswith("NewImage") or nm.startswith("Loaded") or "_mrg" in nm.lower():
                is_user = True
            else:
                continue
        # Texts scoped to another language stay out of this template.
        # User images live in the shared .ksp prefab — skipping inject here
        # dropped Add Image from German (non-default) on reimport.
        if skip_this and kind != "image":
            _deactivate_injected_el(env, el)
            continue
        screen = (getattr(el, "page_screen", "") or "").strip()
        vo = getattr(el, "viewport_object", None)
        if not screen and vo is not None:
            try:
                cur = vo
                while cur is not None and not screen:
                    try:
                        screen = str(cur.get("ksp_page", "") or "")
                    except Exception:
                        pass
                    try:
                        cur = cur.parent
                    except Exception:
                        break
            except Exception:
                pass
        if not screen:
            try:
                idx = int(kb.toc_nodes_index)
                if 0 <= idx < len(kb.toc_nodes):
                    n = kb.toc_nodes[idx]
                    screen = (n.screen or n.name or "").strip()
                    if screen:
                        try:
                            el.page_screen = screen
                        except Exception:
                            pass
            except Exception:
                pass
        ap = screen_ap.get(screen) or ""
        if not ap and screen:
            ap = default_asset_path_for_screen(screen)
        if not ap:
            print(
                "WARNING: KSP inject: no AssetPath for screen %r (element %r) "
                "— skipped"
                % (screen or "?", getattr(el, "name", "") or "?")
            )
            continue
        # Unique GO name for Unity / reimport
        go_name = ""
        el_name = (getattr(el, "name", "") or "").strip()
        # Merge-into-page rows keep a unique Blender name (*_mrg) — always use
        # that for Unity, even if ksp_export_go_name still holds stock "Image".
        if el_name and "_mrg" in el_name.lower():
            go_name = el_name
        if vo is not None:
            try:
                if bool(vo.get("ksp_user_added")) and not bool(vo.get("ksp_grafted")):
                    from ..import_ksp.locale_buffers import (
                        SHIPPED_GO_MARK,
                        encode_shipped_go_name,
                    )
                    export_n = str(vo.get("ksp_export_go_name") or "").strip()
                    if SHIPPED_GO_MARK not in export_n:
                        shipped = str(vo.get("ksp_shipped_locales") or "").strip()
                        locs = [
                            x.strip().lower()
                            for x in shipped.split(",")
                            if x.strip()
                        ]
                        all_locs = [
                            x.strip().lower()
                            for x in str(
                                getattr(kb, "available_locales", "") or ""
                            ).split(",")
                            if x.strip()
                        ]
                        export_n = encode_shipped_go_name(
                            el_name or export_n or go_name,
                            locs,
                            all_locales=all_locs,
                        )
                    go_name = export_n or el_name or go_name
                    if go_name:
                        vo["ksp_export_go_name"] = go_name
            except Exception:
                pass
        if not go_name and vo is not None:
            try:
                go_name = str(vo.get("ksp_export_go_name") or "").strip()
            except Exception:
                go_name = ""
        if not go_name:
            go_name = el_name or "UserUI"
            if screen and go_name.endswith("_" + screen):
                pass
            elif screen and "_mrg" not in go_name.lower():
                go_name = "%s_%s" % (go_name, screen)
        go_name = _unique_prefab_go_name(env, go_name)
        if vo is not None and go_name:
            try:
                vo["ksp_export_go_name"] = go_name
            except Exception:
                pass
        if vo is not None and go_name and "_mrg" in go_name.lower():
            try:
                vo["ksp_export_go_name"] = go_name
            except Exception:
                pass
        ids = inject_ui_element_into_page_prefab(
            env, ap, kind=kind, go_name=go_name,
        )
        if not ids.get("mb"):
            print(
                "WARNING: KSP inject: clone failed for %s %r on %s"
                % (kind, go_name or (getattr(el, "name", "") or "?"), ap)
            )
            continue
        try:
            el.mb_path_id = str(ids["mb"])
            el.rect_path_id = str(ids.get("rect") or "")
            if ids.get("go") and hasattr(el, "go_path_id"):
                el.go_path_id = str(ids["go"])
            if kind == "image":
                if ids.get("sprite"):
                    el.sprite_path_id = str(ids["sprite"])
                if ids.get("texture"):
                    el.texture_path_id = str(ids["texture"])
        except Exception:
            pass
        # Push Blender plane pixel size into RectTransform (donor size was wrong).
        if kind == "image" and ids.get("rect") and vo is not None:
            try:
                w = h = 0.0
                ui = getattr(vo, "ksp_ui", None)
                if ui is not None:
                    try:
                        sd = tuple(ui.size_delta)
                        w, h = float(sd[0]), float(sd[1])
                    except Exception:
                        w = h = 0.0
                if w < 1 or h < 1:
                    try:
                        mats = list(getattr(getattr(vo, "data", None), "materials", None) or ())
                        mat = mats[0] if mats else None
                        img = None
                        if mat and mat.use_nodes:
                            for node in mat.node_tree.nodes:
                                if getattr(node, "image", None) is not None:
                                    img = node.image
                                    break
                        if img is not None and img.size[0] and img.size[1]:
                            w, h = float(img.size[0]), float(img.size[1])
                    except Exception:
                        pass
                if w < 1 or h < 1:
                    # Last resort: Unity texture / sprite already cloned
                    try:
                        af = None
                        for o in env.objects:
                            af = o.assets_file
                            break
                        if af is not None:
                            if ids.get("sprite"):
                                w, h = _sprite_wh(af, int(ids["sprite"]))
                            if (w < 1 or h < 1) and ids.get("texture"):
                                w, h = _texture_wh(af, int(ids["texture"]))
                    except Exception:
                        pass
                ap = None
                if ui is not None:
                    try:
                        ap0 = tuple(ui.anchored_position)
                        ap = (float(ap0[0]), float(ap0[1]))
                    except Exception:
                        ap = None
                # Prefer live Blender location when AP still looks like the
                # default centre (Load Image used to skip writing AP≈0 and
                # never updated ksp_ui after G-moves).
                try:
                    sx = 0.001
                    try:
                        root = vo
                        while getattr(root, "parent", None) is not None:
                            root = root.parent
                        if getattr(root, "ksp_bundle", None) is not None:
                            sx = float(root.ksp_bundle.pixel_scale or 0.001)
                    except Exception:
                        sx = 0.001
                    from ..import_ksp.locale_buffers import snapshot_object_el_state
                    st = snapshot_object_el_state(vo, pixel_scale=sx, mark_edit=False)
                    if st.get("anchored_position") is not None:
                        ap = tuple(float(x) for x in st["anchored_position"][:2])
                    if st.get("size_delta") is not None:
                        sd_live = tuple(float(x) for x in st["size_delta"][:2])
                        if sd_live[0] >= 1.0 and sd_live[1] >= 1.0:
                            w, h = sd_live[0], sd_live[1]
                except Exception:
                    pass
                if w >= 1 and h >= 1:
                    from ..import_ksp.bundle import apply_rect_transform
                    kw = {"size_delta": (w, h)}
                    if ap is not None:
                        kw["anchored_position"] = ap
                    # Identity scale when sizeDelta already includes Blender scale.
                    try:
                        sc = tuple(float(x) for x in vo.scale[:3])
                        if any(abs(c - 1.0) > 0.002 for c in sc[:2]):
                            kw["local_scale"] = (1.0, 1.0, 1.0)
                    except Exception:
                        pass
                    apply_rect_transform(env, int(ids["rect"]), **kw)
                    try:
                        el.size_delta = (w, h, 0.0)
                    except Exception:
                        pass
                    if ap is not None:
                        try:
                            el.anchored_position = (ap[0], ap[1], 0.0)
                        except Exception:
                            pass
                        try:
                            ui.anchored_position = (ap[0], ap[1])
                        except Exception:
                            pass
            except Exception:
                pass
        if vo is not None:
            try:
                ui = vo.ksp_ui
                ui.mb_path_id = str(ids["mb"])
                ui.rect_path_id = str(ids.get("rect") or "")
                if ids.get("go") and hasattr(ui, "go_path_id"):
                    ui.go_path_id = str(ids["go"])
                if kind == "image":
                    if ids.get("sprite") and hasattr(ui, "sprite_path_id"):
                        ui.sprite_path_id = str(ids["sprite"])
                    if ids.get("texture") and hasattr(ui, "texture_path_id"):
                        ui.texture_path_id = str(ids["texture"])
                vo["ksp_export_go_name"] = go_name
                vo["ksp_user_added"] = True
                if screen:
                    vo["ksp_page"] = screen
            except Exception:
                pass
        # Bind / dirty matching texture row so PNG is written
        if kind == "image" and ids.get("texture"):
            img = None
            try:
                if vo is not None and vo.data and getattr(vo.data, "materials", None):
                    mat = vo.data.materials[0] if vo.data.materials else None
                    if mat and mat.use_nodes:
                        for node in mat.node_tree.nodes:
                            if getattr(node, "image", None) is not None:
                                img = node.image
                                break
            except Exception:
                img = None
            matched = None
            # Prefer dirty / path_id-less rows that already hold this image
            # (Load Image / Add Image). Never rebind a stock row that already
            # has a Unity path_id — that would steal Antenna-style textures.
            for tex in kb.textures:
                try:
                    if img is None or tex.image != img:
                        continue
                    tpid = str(getattr(tex, "path_id", "") or "").strip()
                    if not tpid or tpid == "0":
                        matched = tex
                        break
                except Exception:
                    continue
            if matched is None:
                for tex in kb.textures:
                    try:
                        tpid = str(getattr(tex, "path_id", "") or "").strip()
                        if tpid and tpid != "0":
                            continue
                        if (tex.name or "") == (getattr(el, "name", "") or ""):
                            matched = tex
                            break
                        if img is not None and (tex.name or "") == (img.name or ""):
                            matched = tex
                            break
                    except Exception:
                        continue
            if matched is None and img is not None:
                try:
                    matched = kb.textures.add()
                    matched.name = img.name
                    matched.image = img
                except Exception:
                    matched = None
            if matched is not None:
                try:
                    matched.path_id = str(ids["texture"])
                    matched.dirty = True
                    # Empty hash forces PNG rewrite even if dirty is lost.
                    matched.content_hash = ""
                    if img is not None:
                        matched.image = img
                    if screen:
                        matched.page_screen = screen
                except Exception:
                    pass
                try:
                    el.texture_path_id = str(ids["texture"])
                except Exception:
                    pass
            else:
                print(
                    "WARNING: KSP inject: no texture row for new UI image %r "
                    "(path_id=%s) — PNG may not be written"
                    % (getattr(el, "name", "") or "?", ids.get("texture"))
                )
        if skip_this:
            _deactivate_injected_el(env, el)
        n += 1
    return n
