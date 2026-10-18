Bundled stock assets (fallback when user GameData lacks Unity-embedded files).

Source: AssetRipper dump of KSP (sharedassets / Resources), not loose GameData.
Layout:
  Sounds/  - stock AudioClips (sound_jet_deep, sound_vent_*, etc.)
  Fonts/   - stock UI fonts (Calibri family, HEADINGFONT, ...)

Resolution order for audio: Preferences GameData -> sibling GameData -> this folder.
Do not commit Unity .meta / .cs / full ExportedProject here.
