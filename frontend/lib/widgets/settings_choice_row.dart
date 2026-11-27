import 'package:flutter/material.dart';

import '../theme/app_motion.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'owl_kit_extras.dart';

/// Part 16 (D5a, 28 Nov 2026): a settings choice = a bold title, an optional short muted line and a row of kit pick chips (one is lit).
/// Used inside a SettingsGroup for "one of a few" choices (Light / Dark / System, Classic / Glass / Gradient). [onSelect] gets the tapped index.
/// Plain widget, no provider. Dart NOT compiled in the sandbox: the GitHub APK build is the first compile.
class SettingsChoiceRow extends StatelessWidget {
  final String title;
  final String caption;
  final List<String> labels;
  final int selected;
  final ValueChanged<int> onSelect;

  const SettingsChoiceRow({
    super.key,
    required this.title,
    this.caption = '',
    required this.labels,
    required this.selected,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.s),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
        if (caption.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2), child: Text(caption, style: TextStyle(fontSize: 11.5, color: p.textMuted))),
        const SizedBox(height: AppSpacing.s),
        OwlPickChipRow(
          labels: labels,
          selected: selected < 0 ? 0 : selected,
          onSelect: (i) {
            if (i != selected) AppHaptics.light();
            onSelect(i);
          },
        ),
      ]),
    );
  }
}
