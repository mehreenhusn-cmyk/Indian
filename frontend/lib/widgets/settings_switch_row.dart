import 'package:flutter/material.dart';

import '../theme/app_motion.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';

/// Part 16 (D5a, 28 Nov 2026): one on / off row for a SettingsGroup: title, one muted line under it and a switch on the right.
/// [onChanged] null = the row is greyed out and the switch cannot be tapped (for example a sound option while the master switch is off).
/// Same look as the old _voiceRow of the settings screen, now one shared widget. Plain widget, no provider. Dart NOT compiled in the sandbox.
class SettingsSwitchRow extends StatelessWidget {
  final String title;
  final String subtitle;
  final bool value;
  final ValueChanged<bool>? onChanged;

  const SettingsSwitchRow({super.key, required this.title, this.subtitle = '', required this.value, this.onChanged});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final off = onChanged == null;
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.s),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: off ? p.textMuted : p.textPrimary)),
            if (subtitle.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2), child: Text(subtitle, style: TextStyle(fontSize: 11.5, color: p.textMuted))),
          ]),
        ),
        Switch(
          value: value,
          activeColor: p.accent,
          onChanged: off
              ? null
              : (v) {
                  AppHaptics.light();
                  onChanged!(v);
                },
        ),
      ]),
    );
  }
}
