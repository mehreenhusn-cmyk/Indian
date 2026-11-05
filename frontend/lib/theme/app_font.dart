import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// R31a / Part 11b: the font switch. NEW look = IBM Plex (Sans for sentences and titles, Mono for numbers, labels and small headings, like the exchange page the owner liked).
/// OLD look = Inter. Nothing was deleted: the Inter files stay in assets/fonts and in pubspec.yaml, so the owner can go back with ONE switch (Settings and tools > "New font").
/// Default = new. Saved in SharedPreferences (key owl_font_new). The theme reads it on every build; screens that read AppTypography.* pick it up when they rebuild, all of them after an app restart.
/// IBM Plex Mono files are bundled. IBM Plex Sans files are NOT bundled yet (add them as the README4 MERGE-TIME block says): until then the Sans role falls back to Inter (fontFamilyFallback), so nothing breaks.
class AppFont {
  AppFont._();

  static const String oldFamily = 'Inter';
  static const String sans = 'IBMPlexSans';
  static const String mono = 'IBMPlexMono';
  static const String _key = 'owl_font_new';

  static final ValueNotifier<bool> useNew = ValueNotifier<bool>(true);
  static SharedPreferences? _prefs;

  /// Call once before runApp. A missing / broken store keeps the default (new).
  static void load(SharedPreferences? prefs) {
    _prefs = prefs;
    try {
      useNew.value = prefs?.getBool(_key) ?? true;
    } catch (_) {}
  }

  static Future<void> set(bool v) async {
    useNew.value = v;
    try {
      await _prefs?.setBool(_key, v);
    } catch (_) {}
  }

  /// Family for sentences, titles, row text.
  static String get body => useNew.value ? sans : oldFamily;

  /// Family for numbers, labels, small headings (Inter in the old look).
  static String get numeric => useNew.value ? mono : oldFamily;

  /// Used when a Plex file is missing: Inter, so a missing file never shows a blank or a box.
  static List<String>? get fallback => useNew.value ? const [oldFamily] : null;
}
