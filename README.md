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

Further Reading
===============

[There's a wiki](https://github.com/taniwha/io_object_mu/wiki) covering topics
including [installation](https://github.com/taniwha/io_object_mu/wiki/Installation).

The KSP Forum with discussions about this is located here:
* https://forum.kerbalspaceprogram.com/index.php?/topic/40056-12-14-blender-mu-importexport-addon/&

