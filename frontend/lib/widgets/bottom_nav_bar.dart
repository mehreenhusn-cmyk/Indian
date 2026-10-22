import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import 'owl_pressable.dart';

/// Bottom navigation - same public API as before (currentIndex + onTap) and
/// 7 tabs (AI sits at index 4, after Signals; Dash/Market/Pos/Signals keep
/// their indexes so AppProvider.goToTab keeps working). Only the look changed: flat solid bar,
/// hairline top border, accent pill + dot on the active tab.
class BottomNavBar extends StatelessWidget {
  final int currentIndex;
  final ValueChanged<int> onTap;

  const BottomNavBar({
    super.key,
    required this.currentIndex,
    required this.onTap,
  });

  static const List<IconData> _icons = [
    Icons.grid_view_rounded,
    Icons.trending_up_rounded,
    Icons.layers_rounded,
    Icons.sensors_rounded,
    Icons.auto_awesome_rounded,
    Icons.notifications_none_rounded,
    Icons.settings_rounded,
    Icons.bolt_rounded,
  ];

  static const List<String> _labels = [
    'Dash',
    'Market',
    'Pos',
    'Sig',
    'AI',
    'Alert',
    'Set',
    'Ping',
  ];

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      decoration: BoxDecoration(
        color: p.surfacePrimary,
        border: Border(top: BorderSide(color: p.border, width: 1)),
        // Soft accent glow fading up from the bar's top edge (premium depth,
        // purely decorative - does not change layout or hit-testing).
        boxShadow: [BoxShadow(color: p.accent.withOpacity(0.07), blurRadius: 14, offset: const Offset(0, -3))],
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.xs,
            vertical: AppSpacing.s,
          ),
          child: Row(
            children: [
              for (var i = 0; i < _icons.length; i++)
                Expanded(child: _item(p, i)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _item(AppPalette p, int index) {
    final selected = currentIndex == index;
    final color = selected ? p.accent : p.textMuted;

    return OWLPressable(
      // Tapping the open tab again is passed on too: the app scrolls it to the top.
      onTap: () => onTap(index),
      child: AnimatedContainer(
        duration: AppMotion.base,
        margin: const EdgeInsets.symmetric(horizontal: 0),
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs + 1),
        decoration: BoxDecoration(
          color: selected ? p.accent.withOpacity(0.10) : Colors.transparent,
          borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AnimatedScale(
              scale: selected ? 1.14 : 1.0,
              duration: AppMotion.base,
              curve: Curves.easeOutBack,
              child: Icon(_icons[index], size: 18, color: color),
            ),
            const SizedBox(height: 3),
            Text(
              _labels[index],
              maxLines: 1,
              overflow: TextOverflow.clip,
              style: AppTypography.metadata.copyWith(
                fontSize: 8.5,
                color: color,
                fontWeight: selected ? FontWeight.w700 : FontWeight.w400,
              ),
            ),
            const SizedBox(height: 3),
            AnimatedContainer(
              duration: AppMotion.base,
              width: selected ? 4 : 0,
              height: 4,
              decoration: BoxDecoration(color: p.accent, shape: BoxShape.circle),
            ),
          ],
        ),
      ),
    );
  }
}
