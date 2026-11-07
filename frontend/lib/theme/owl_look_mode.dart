import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'app_theme.dart';

/// E11: the card LOOK the owner can switch in Settings > Appearance: Classic (as before), Glass or Gradient.
/// One saved number (shared_preferences key owl_look_mode_v1). OWLCard (and with it OwlSectionCard and most screens) and the Positions card read it, so they change at once.
/// Honest limit: Glass here is a see-through sheen + bright rim + soft shadow (no real blur of what is behind: blur inside long live lists is slow). A screen that draws its own plain Container instead of OWLCard keeps the Classic look.
class OwlLookMode {
  OwlLookMode._();

  static const int classic = 0, glass = 1, gradient = 2;
  static const String _key = 'owl_look_mode_v1';
  static final ValueNotifier<int> mode = ValueNotifier<int>(classic);
  static SharedPreferences? _prefs;

  static void load(SharedPreferences prefs) {
    _prefs = prefs;
    final v = prefs.getInt(_key) ?? classic;
    mode.value = (v >= classic && v <= gradient) ? v : classic;
  }

  static void set(int v) {
    mode.value = v;
    _prefs?.setInt(_key, v);
  }

  static String name(int m) => m == glass ? 'Glass' : (m == gradient ? 'Gradient' : 'Classic');

  /// null = the caller keeps its own Classic decoration. [edge] / [glow] keep their meaning (green = good, red = bad) in every look.
  static BoxDecoration? decoration(AppPalette p, int m, {required double radius, Color? edge, Color? glow}) {
    if (m != glass && m != gradient) return null;
    final dark = p.brightness == Brightness.dark;
    final rim = glow != null ? glow.withOpacity(0.45) : (edge != null ? edge.withOpacity(0.6) : null);
    if (m == glass) {
      return BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: dark
              ? [Colors.white.withOpacity(0.11), Colors.white.withOpacity(0.03)]
              : [Colors.white.withOpacity(0.92), Colors.white.withOpacity(0.55)],
        ),
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(color: rim ?? (dark ? Colors.white.withOpacity(0.18) : Colors.white), width: 1.1),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(dark ? 0.30 : 0.07), blurRadius: 18, offset: const Offset(0, 6))],
      );
    }
    return BoxDecoration(
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [
          Color.alphaBlend(p.accent.withOpacity(dark ? 0.22 : 0.14), p.surfaceElevated),
          Color.alphaBlend(p.purple.withOpacity(dark ? 0.14 : 0.08), p.surfaceElevated),
        ],
      ),
      borderRadius: BorderRadius.circular(radius),
      border: Border.all(color: rim ?? p.accent.withOpacity(0.30), width: 1),
      boxShadow: [BoxShadow(color: p.accent.withOpacity(dark ? 0.10 : 0.12), blurRadius: 16, offset: const Offset(0, 4))],
    );
  }
}
