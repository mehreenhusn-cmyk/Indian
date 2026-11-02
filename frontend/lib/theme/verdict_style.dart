import 'package:flutter/material.dart';
import 'app_theme.dart';

/// Round 7a: ONE look for every verdict word, in both the dark and the light theme.
/// Colours come only from the active palette (context.palette), never hard-coded.
///   EDGE             green   steady profit proven (100+ cases, same sign in both halves)
///   LOSING           red     net after fee is negative with 100+ cases
///   NO_EDGE          grey    tested, nothing clearly better than baseline
///   DIAGNOSIS_ONLY   blue    describes what happened; NOT a filter, NOT proof (never green)
///   NOT_ENOUGH_DATA  amber   cannot decide yet (the card says what is missing)
class VerdictStyle {
  final String word;
  final String label;
  final Color color;
  final IconData icon;

  const VerdictStyle({required this.word, required this.label, required this.color, required this.icon});

  /// Background tint for a badge or card header.
  Color get tint => color.withOpacity(0.14);

  static const List<String> words = ['EDGE', 'NO_EDGE', 'LOSING', 'NOT_ENOUGH_DATA', 'DIAGNOSIS_ONLY'];

  /// Unknown or empty words fall back to NOT_ENOUGH_DATA, so a screen never shows a wrong colour.
  static String clean(String? raw) {
    final w = (raw ?? '').trim().toUpperCase().replaceAll(' ', '_');
    return words.contains(w) ? w : 'NOT_ENOUGH_DATA';
  }

  static VerdictStyle of(AppPalette p, String? raw) {
    final w = clean(raw);
    switch (w) {
      case 'EDGE':
        return VerdictStyle(word: w, label: 'EDGE', color: p.profit, icon: Icons.check_circle_outline_rounded);
      case 'LOSING':
        return VerdictStyle(word: w, label: 'LOSING', color: p.loss, icon: Icons.trending_down_rounded);
      case 'NO_EDGE':
        return VerdictStyle(word: w, label: 'NO EDGE', color: p.textSecondary, icon: Icons.remove_circle_outline_rounded);
      case 'DIAGNOSIS_ONLY':
        return VerdictStyle(word: w, label: 'DIAGNOSIS', color: p.accent, icon: Icons.science_outlined);
      default:
        return VerdictStyle(word: 'NOT_ENOUGH_DATA', label: 'NOT ENOUGH DATA', color: p.warning, icon: Icons.hourglass_empty_rounded);
    }
  }

  /// Convenience for widgets: VerdictStyle.ofContext(context, 'LOSING').
  static VerdictStyle ofContext(BuildContext context, String? raw) => of(context.palette, raw);
}
