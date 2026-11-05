import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_motion2.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'font_switch_row.dart';
import 'owl_sentence.dart';

/// Part P-C: ONE small menu button at the top-left (replaces the lone Light / Dark button). It opens a sheet in 280 ms with the quiet settings: Theme (Light / Dark), Font (the old switch row),
/// and the Strategy timeframe as a read-only line (the 15m chip is no longer on the top bar; the setting itself is changed in Settings and tools, nothing here changes it).
/// Colours only from the palette. Dart NOT compiled.
class OwlTopMenuButton extends StatelessWidget {
  const OwlTopMenuButton({super.key});

  void _open(BuildContext context) {
    final p = context.palette;
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: p.surface,
      showDragHandle: true,
      sheetAnimationStyle: AnimationStyle(duration: OwlMotion.sheet, curve: OwlMotion.smooth),
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(AppSpacing.radiusLarge))),
      builder: (_) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, 0, AppSpacing.l, AppSpacing.l),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            const OwlSectionLabel('Look'),
            _ThemeRow(),
            const FontSwitchRow(),
            const OwlSectionLabel('Trading'),
            Consumer<AppProvider>(
              builder: (context, pr, _) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Text('Strategy timeframe: ${pr.settings['timeframe'] ?? '5m'} (change it in Settings and tools, More tab)', style: context.type.secondary),
              ),
            ),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return IconButton(
      tooltip: 'Menu',
      visualDensity: VisualDensity.compact,
      icon: Icon(Icons.tune_rounded, size: 22, color: p.textMuted),
      onPressed: () => _open(context),
    );
  }
}

class _ThemeRow extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final light = p.brightness == Brightness.light;
    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.s),
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.cardPad, vertical: AppSpacing.s),
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
      child: Row(children: [
        Icon(light ? Icons.light_mode_outlined : Icons.dark_mode_outlined, size: 22, color: p.textPrimary),
        const SizedBox(width: 12),
        Expanded(child: Text(light ? 'Light theme' : 'Dark theme', style: context.type.primary.copyWith(fontWeight: FontWeight.w600))),
        Switch(value: !light, onChanged: (dark) => context.read<AppProvider>().setThemeMode(dark ? ThemeMode.dark : ThemeMode.light)),
      ]),
    );
  }
}
