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

Bugs
===============


for now im only notice two bugs:
1. the size is twice as original file.
2. we need to fix some animations on some parts that is connecting with armature and armature_obj. 
<br />
<br />All stock parts will export and import now (702 parts). 
<br />List parts with bugged exported animations (some could work either):
<br />HeatShield.mu, turboJet.mu, turboRamJet.mu, AeroSpike.mu, Ant.mu, Spider.mu, TerrierV2.mu, liquidEngineLV-N
liquidEngineLV-T45, LqdEnginePoodle_v2.mu, skipper_v2.mu, SSME.mu, solidBoosterS2-17.mu, solidBoosterS2-33.mu
SolidBoosterF3S0.mu, SolidBoosterFM1.mu, MiniDrill.mu, commDish88-88, mediumDishAntenna.mu, GrapplingArm.mu
launchClamp1, light_08.mu, light_12.mu, TriBitDrillInt.mu
<br />
<br />Squad Expansion:
<br />GoExOb.mu, IonExperiment.mu, seismicSensor.mu, WeatherStation.mu, ROCArm_01.mu, ROCArm_02.mu, ROCArm_03.mu
<br />
<br />No more exceptions or crashes during import / export 😊
