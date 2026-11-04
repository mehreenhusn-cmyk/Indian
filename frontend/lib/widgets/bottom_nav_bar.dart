import 'package:flutter/material.dart';
import '../navigation/app_routes.dart';
import '../theme/app_theme.dart';
import 'owl_pressable.dart';

/// Bottom navigation - same public API as before (currentIndex + onTap, both are SCREEN indexes of main.dart).
/// Round 11: 5 visible tabs: Dashboard, Positions, Sniper, Study Lab, Diagnostics. Market, Brain, Signals, Dual Bot, AI and the Settings page keep
/// their screen index (so AppProvider.goToTab keeps working) but open from the top-bar gear; while one of them is open NO bar tab is lit.
/// R25: flat bar like a standard exchange app (see build()).
class BottomNavBar extends StatelessWidget {
  final int currentIndex;
  final ValueChanged<int> onTap;

  const BottomNavBar({
    super.key,
    required this.currentIndex,
    required this.onTap,
  });

  // Outlined icon when idle, filled when selected. AI = CPU chip (no more sparkle).
  // The visible tab -> the screen index it opens (7 = Brain screen, 6 = More).
  static final List<int> _screens = AppRoutes.barScreens;   // Part 27: from the route map

  static const List<IconData> _icons = [
    Icons.space_dashboard_outlined,
    Icons.account_balance_wallet_outlined,
    Icons.gps_fixed,
    Icons.fact_check_outlined,
    Icons.monitor_heart_outlined,
  ];

  static const List<IconData> _iconsOn = [
    Icons.space_dashboard_rounded,
    Icons.account_balance_wallet_rounded,
    Icons.gps_fixed_rounded,
    Icons.fact_check_rounded,
    Icons.monitor_heart_rounded,
  ];

  static const List<String> _labels = [
    'Dashboard',
    'Positions',
    'Sniper',
    'Study Lab',
    'Diagnostics',
  ];

  // Which visible tab is lit: a gear page (Market, Brain, Signals, Dual Bot, AI, Settings) lights none (-1); the gear in the top bar lights instead.
  int get _lit => _screens.indexOf(currentIndex);

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    // R25: flat full-width bar, one thin line on top, 5 icons with small labels. Selected = filled icon + bold dark/white label, the rest grey.
    // No floating card, no shadow, no coloured pill.
    return Container(
      decoration: BoxDecoration(color: p.bg, border: Border(top: BorderSide(color: p.border, width: 1))),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(4, 6, 4, 4),
          child: Row(
            children: [
              for (var i = 0; i < _icons.length; i++) Expanded(child: _item(p, i)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _item(AppPalette p, int index) {
    final selected = _lit == index;
    final color = selected ? p.textPrimary : p.textMuted;
    return OWLPressable(
      // Tapping the open tab again is passed on too: the app scrolls it to the top.
      onTap: () => onTap(_screens[index]),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(selected ? _iconsOn[index] : _icons[index], size: 24, color: color),
            const SizedBox(height: 3),
            Text(
              _labels[index],
              maxLines: 1,
              overflow: TextOverflow.clip,
              style: AppTypography.metadata.copyWith(fontSize: 11, color: color, fontWeight: selected ? FontWeight.w700 : FontWeight.w500),
            ),
          ],
        ),
      ),
    );
  }
}
