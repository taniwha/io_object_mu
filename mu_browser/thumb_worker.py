# vim:ts=4:et
# <pep8 compliant>
"""Background Blender worker for MU thumbnail generation.

Invoked by the main Blender instance as::

    blender --background --factory-startup --python-exit-code 1 \\
        --python <this_file> -- \\
        --addon <addon_root> --gamedata <GameData> \\
        --jobfile <jobs.txt> --progress <progress.txt> [--force]

Job file format (UTF-8, one entry per line)::

    <mu_path>\\t<part_name>

Progress file is rewritten after every item::

    current\\ttotal\\tstatus_message

Exit 0 on success (even if some thumbs failed). Exit 1 on fatal bootstrap error.
"""
from __future__ import annotations

import os
import sys
import traceback


def _argv_after_dashdash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def _arg_value(argv, flag, default=""):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def _has_flag(argv, flag):
    return flag in argv


def _write_progress(path, current, total, message=""):
    """Write progress. *current* may be fractional (e.g. 3.4 = item 3 + 40%).

    Format (UTF-8, single line)::
        <current>\\t<total>\\t<status_message>

    current is written with one decimal place so the UI can show smooth
    sub-item progress without measurable overhead (tiny file rewrite only).
    """
    try:
        cur = float(current)
        # One decimal is enough for stage granularity; avoids float noise.
        text = "%.1f\t%d\t%s\n" % (cur, int(total), message or "")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        pass


def _bootstrap(addon_dir):
    addon_dir = os.path.abspath(addon_dir)
    if addon_dir not in sys.path:
        sys.path.insert(0, addon_dir)
    parent = os.path.dirname(addon_dir)
    if parent and parent not in sys.path:
        sys.path.insert(0, parent)
    # Prefer the addon's own bootstrap helper (same as test_anim_roundtrip).
    try:
        from _addon_bootstrap import ensure_addon_enabled, import_addon_module
        ensure_addon_enabled()
        return import_addon_module
    except Exception:
        pass
    # Fallback: enable by module name if already on path
    try:
        import bpy
        # Try common package names
        for name in ("io_object_mu", "mu", "ksp_mu"):
            try:
                bpy.ops.preferences.addon_enable(module=name)
            except Exception:
                pass
    except Exception:
        pass

    def import_addon_module(rel):
        # rel like "mu_browser.thumbnails" or "import_mu"
        import importlib
        # Discover top-level package that contains mu_browser
        for root in sys.path:
            mb = os.path.join(root, "mu_browser")
            if os.path.isdir(mb):
                pkg = os.path.basename(root.rstrip("/\\"))
                if pkg and pkg not in ("", "."):
                    full = pkg + "." + rel if not rel.startswith(pkg) else rel
                    try:
                        return importlib.import_module(full)
                    except Exception:
                        pass
                try:
                    return importlib.import_module(rel)
                except Exception:
                    pass
        return importlib.import_module(rel)

    return import_addon_module


def main():
    argv = _argv_after_dashdash()
    addon_dir = _arg_value(argv, "--addon")
    gamedata = _arg_value(argv, "--gamedata")
    jobfile = _arg_value(argv, "--jobfile")
    progress = _arg_value(argv, "--progress")
    force = _has_flag(argv, "--force")
    show_attach_points = _has_flag(argv, "--show-attach-points")

    if not addon_dir or not jobfile:
        print("[mu_thumb_worker] missing --addon or --jobfile", flush=True)
        sys.exit(1)

    jobs = []
    try:
        with open(jobfile, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "\t" in line:
                    path, name = line.split("\t", 1)
                else:
                    path, name = line, ""
                jobs.append((path.strip(), name.strip()))
    except Exception as e:
        print("[mu_thumb_worker] cannot read jobfile:", e, flush=True)
        sys.exit(1)

    total = len(jobs)
    _write_progress(progress, 0, total, "")

    try:
        import_addon_module = _bootstrap(addon_dir)
    except Exception:
        traceback.print_exc()
        _write_progress(progress, 0, total, "")
        sys.exit(1)

    # GameData preference (textures / paths)
    if gamedata:
        try:
            prefs = import_addon_module("preferences.preferences").Preferences()
            prefs.GameData = gamedata
        except Exception as e:
            print("[mu_thumb_worker] GameData pref:", e, flush=True)

    try:
        thumbs = import_addon_module("mu_browser.thumbnails")
    except Exception:
        try:
            # When mu_browser is the package root on sys.path
            import importlib
            thumbs = importlib.import_module("thumbnails")
        except Exception:
            traceback.print_exc()
            _write_progress(progress, 0, total, "")
            sys.exit(1)

    generate = getattr(thumbs, "generate_thumbnail", None)
    if generate is None:
        _write_progress(progress, 0, total, "")
        sys.exit(1)

    done = 0
    failed = 0
    dev = bool(getattr(thumbs, "DEV_LOG_LEVEL", 0)) or bool(getattr(thumbs, "DEV_OVERLAY", 0))
    for i, (path, name) in enumerate(jobs):
        label = name or os.path.basename(path) or "?"

        def _stage(frac, msg="", _i=i, _label=label):
            # frac in [0, 1) within this item → overall current = i + frac
            try:
                f = max(0.0, min(0.99, float(frac)))
            except Exception:
                f = 0.0
            _write_progress(progress, _i + f, total, msg or _label)

        _stage(0.0, "start %s" % label)
        try:
            # progress_cb is optional; older generate_thumbnail ignores it.
            try:
                result = generate(
                    path, name, force=force, show_attach_points=show_attach_points,
                    progress_cb=_stage,
                )
            except TypeError:
                result = generate(path, name, force=force, show_attach_points=show_attach_points)
            if result:
                done += 1
            elif dev:
                failed += 1
                print("[mu_thumb_worker][DEV] GENERATION RETURNED NONE | %s | %s" % (path, name), flush=True)
        except Exception as e:
            failed += 1
            if dev:
                print("[mu_thumb_worker][DEV] GENERATION EXCEPTION | %s | %s | %s: %s" % (path, name, type(e).__name__, e), flush=True)
                traceback.print_exc()
        _write_progress(progress, i + 1, total, "done %s" % label)

    if dev and failed:
        print("[mu_thumb_worker][DEV] DONE: success=%d failed=%d total=%d" % (done, failed, total), flush=True)
    _write_progress(progress, total, total, "")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
