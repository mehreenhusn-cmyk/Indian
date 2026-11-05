import 'package:flutter/material.dart';
import '../theme/app_font.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';

/// Part 11b: ONE row with a switch for the font (Settings and tools). ON = new look (IBM Plex: Sans for sentences, Mono for numbers and labels), OFF = the old Inter font.
/// Both stay in the app; nothing is deleted. The theme updates at once; every screen shows the new font after an app restart (said in the row). Saved by AppFont (SharedPreferences). Dart NOT compiled.
class FontSwitchRow extends StatelessWidget {
  const FontSwitchRow({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return ValueListenableBuilder<bool>(
      valueListenable: AppFont.useNew,
      builder: (context, on, _) => Container(
        margin: const EdgeInsets.only(bottom: AppSpacing.s),
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.cardPad, vertical: AppSpacing.s),
        decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
        child: Row(children: [
          Icon(Icons.text_fields_rounded, size: 22, color: p.textPrimary),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('New font (IBM Plex)', style: context.type.primary.copyWith(fontWeight: FontWeight.w600)),
              const SizedBox(height: 2),
              Text(on ? 'On. Switch off to go back to the old font (Inter). Restart the app to see it everywhere.' : 'Off: the old font (Inter) is in use. Switch on for the new look. Restart the app to see it everywhere.', style: context.type.metadata),
            ]),
          ),
          Switch(value: on, onChanged: (v) => AppFont.set(v)),
        ]),
      ),
    );
  }
}
