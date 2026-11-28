import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Part 21 (FILE 40): ONE tap Light <-> Dark, live (no restart), in the top bar. It reads the theme that is really on screen
/// (so it also works when the mode is 'System') and saves the other one through AppProvider.setThemeMode (same store as Settings).
/// Colours come only from the palette, so it looks right in both themes. Dart NOT compiled.
class ThemeSwitchButton extends StatelessWidget {
  const ThemeSwitchButton({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final isLight = p.brightness == Brightness.light;
    return IconButton(
      tooltip: isLight ? 'Switch to Dark' : 'Switch to Light',
      visualDensity: VisualDensity.compact,
      icon: Icon(isLight ? Icons.dark_mode_outlined : Icons.light_mode_outlined, size: 22, color: p.textMuted),
      onPressed: () => context.read<AppProvider>().setThemeMode(isLight ? ThemeMode.dark : ThemeMode.light),
    );
  }
}
