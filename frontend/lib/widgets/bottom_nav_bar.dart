import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import 'owl_pressable.dart';

/// Bottom navigation - same public API as before (currentIndex + onTap) and
/// 7 tabs: Dash, Market, Pos, Signals (Signals + Alerts), Dual Bot, AI, More.
/// Dash/Market/Pos/Signals keep indexes 0-3 so AppProvider.goToTab keeps working. Floating
/// rounded glass bar, accent pill on the active tab.
class BottomNavBar extends StatelessWidget {
  final int currentIndex;
  final ValueChanged<int> onTap;

  const BottomNavBar({
    super.key,
    required this.currentIndex,
    required this.onTap,
  });

  // Outlined icon when idle, filled when selected. AI = CPU chip (no more sparkle).
  static const List<IconData> _icons = [
    Icons.space_dashboard_outlined,
    Icons.query_stats_outlined,
    Icons.account_balance_wallet_outlined,
    Icons.sensors_outlined,
    Icons.smart_toy_outlined,
    Icons.memory_outlined,
    Icons.widgets_outlined,
  ];

  static const List<IconData> _iconsOn = [
    Icons.space_dashboard_rounded,
    Icons.query_stats_rounded,
    Icons.account_balance_wallet_rounded,
    Icons.sensors_rounded,
    Icons.smart_toy_rounded,
    Icons.memory_rounded,
    Icons.widgets_rounded,
  ];

  static const List<String> _labels = [
    'Dash',
    'Market',
    'Pos',
    'Signals',
    'Dual Bot',
    'AI',
    'More',
  ];

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final dark = p.brightness == Brightness.dark;
    // Floating rounded bar, inset from the screen edges. Solid fill (no
    // blur) so it stays smooth on mid-range phones.
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(10, 4, 10, 8),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
          decoration: BoxDecoration(
            color: dark ? p.surfaceElevated : p.surface,
            borderRadius: BorderRadius.circular(22),
            border: Border.all(
              color: dark ? Colors.white.withOpacity(0.08) : p.border,
              width: 1,
            ),
            boxShadow: [
              BoxShadow(
                color: dark
                    ? p.accent.withOpacity(0.10)
                    : p.accent.withOpacity(0.12),
                blurRadius: 22,
                offset: const Offset(0, 6),
              ),
            ],
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
        curve: AppMotion.standard,
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs + 2),
        decoration: BoxDecoration(
          color: selected ? p.accent.withOpacity(0.14) : Colors.transparent,
          borderRadius: BorderRadius.circular(16),
          boxShadow: selected ? [BoxShadow(color: p.accent.withOpacity(0.18), blurRadius: 12, offset: const Offset(0, 3))] : null,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AnimatedScale(
              scale: selected ? 1.12 : 1.0,
              duration: AppMotion.base,
              curve: Curves.easeOutBack,
              child: Icon(selected ? _iconsOn[index] : _icons[index], size: 22, color: color),
            ),
            const SizedBox(height: 3),
            Text(
              _labels[index],
              maxLines: 1,
              overflow: TextOverflow.clip,
              style: AppTypography.metadata.copyWith(
                fontSize: 9,
                color: color,
                fontWeight: selected ? FontWeight.w700 : FontWeight.w400,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
