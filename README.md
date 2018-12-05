io_object_mu
==========

Blender addon for importing and exporting KSP .mu files.

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

Installation Instructions
=========================

1. Clone the github repo
2. Copy the entire folder (io_object_mu) into Blender's scripts/addons folder
3. Start Blender
4. Go to File ->  User Preferences... -> Add-ons tab -> Import-Export category
5. Find "Import-Export: Mu model format (KSP)" in the list
6. Check the checkbox next to it
7. Click "Save User Settings"

If you go to the File -> Import menu, it now has "KSP Mu" and "KSP Craft" in the list.

The KSP Forum with discussions about this is located here:
* https://forum.kerbalspaceprogram.com/index.php?/topic/40056-12-14-blender-mu-importexport-addon/&

