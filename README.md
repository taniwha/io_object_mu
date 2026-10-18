io_object_mu
==========

Blender addon for importing and exporting KSP .mu files.

**Supported:** Blender **5.2 LTS** with Kerbal Space Program **1.12.x**.
Legacy shader CFG node types (`SeparateRGB` / `MixRGB` / `EeveeSpecular`) are
remapped automatically for Blender 4+/5.x.

NOTE: the import/export functionality is still under heavy development, but
importing is mostly working for static meshes (minus normals and tangents).

mu.py is the main workhorse: it reads and writes .mu files. It is independent
of blender and works with both versions 2 and 3 of python. Some notes on mu.py:
* vectors and quaternions are converted from Unities LHS to Blender's RHS on
load and back again when writing.
* vertex tangents are broken (they are incorrectly treated as quaternions), but
will be preserved if mu.py is used to copy a .mu file. This is a bug.
* mu.py always writes version 5 .mu files.
* it may still break, back up your work.

Version 1.0.0 includes:
* full animation support
* sound support (.wav .ogg)
* .ksp .lang .cfg file support
* fonts, part thumbs support
* new menu called KSP and MU
* better import / export .mu support (included variant support)

Further Reading
===============

[There's a wiki](https://github.com/taniwha/io_object_mu/wiki) covering topics
including [installation](https://github.com/taniwha/io_object_mu/wiki/Installation).

The KSP Forum with discussions about this is located here:
https://forum.kerbalspaceprogram.com/index.php?/topic/40056-12-14-blender-mu-importexport-addon/& 

Bugs / status
===============

Blender **5.2 LTS** fixes (shaders + Action API + armature/animation round-trip)
are in place. Smoke regression covers HeatShield, turboJet, GrapplingArm, solar panels.

Note: `.mu` has no constraint chunk (PartTools bakes hierarchy). Blender uses
`COPY_TRANSFORMS` on bindPose for skinned meshes; collection instances export
via existing hierarchy flatten when there is a single group root.

**All stock parts should import/export without crashes (702 parts in test GameData).**


MU panel:
* Magnet function doesn't work.
* Sometimes textures/sound get messed up. For editing, use File → Import → KSP Mu (.mu).
* Investigate why importing through the MU panel is worse than the normal import (rendering is bad, e.g. coordinates).

.mu:
* Bump maps only work on default variants.

.ksp .lang:
* Adding new pages / screens from the menu results in “Asset load failed.”
* Editing a child’s text causes part of its content to disappear.

.craft:
* Still need to tweak part import

TODO
================

* Merge "assets", "boundle_stock", "flags", "import_ksp/backgrounds", "import_ksp/data", "import_ksp/fonts", "import_ksp/samples" folder in to one.
* Add dynamic search from all categories with suggestions to the MU panel.
* Add an “FX” category to the MU panel (flames, etc.).
* Add Delete Selected to the MU panel. Backend: delete audio, animations, and leftover data (e.g. imported/generated thumbnails).
* Add an option to import .craft files as multiple parts (e.g. for 3D-printing shrouds / fairing selectors). Take rotations from .cfg into account.
* Add integrity checks to variant names (decode, embed, and verify them against GameData\Squad\Parts\VariantThemes.cfg).
* Add support for loading original thumbnails if they exist in GameData; the Thumbs → Regenerate button should regenerate them (e.g. for modded ReStock).
* Add a loading progress bar when generating thumbnails (similar to .mu file import/export).
* Refresh variants (the list of all active variants) after selecting an object imported via the MU panel.
* Add a debug button that prints all textures, sounds, and files used by a .mu file to the console, both before and after import.
* Update the .ksp examples.
* Use numpy → pixels.foreach_set instead of list comprehensions.
* Skip PNG files in the middle of the process (DXT → RGBA → Blender).
* Decode only textures used by the UI.
* Build the active page first; load the rest in the background.
* Refresh the loading progress bar less frequently (e.g. once per second).
