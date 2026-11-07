import 'package:flutter/material.dart';
import '../navigation/app_routes.dart';
import '../theme/app_motion2.dart';
import '../theme/app_theme.dart';
import 'owl_nav_icons.dart';
import 'owl_pressable.dart';

/// Bottom navigation - same public API as before (currentIndex + onTap, both are SCREEN indexes of main.dart).
/// E9: the bubble no longer rises above the bar (see build). Older note: Part P-B (new look): a FLOATING rounded bar. The lit tab was a round bubble lifted over the bar (accent gradient, filled icon, a ring in the page colour so it looks cut out),
/// the label shows ONLY under the lit tab, the bubble slides to the next tab in 250 ms (small spring). Idle tabs = outline icon only. Dark + Light both follow the palette.
/// No shadow: the bar has ONE hairline border like every card. Tabs: Home, Positions, Sniper, Study Lab, More (see OwlNavIcon). Each tab has a Semantics label (the label text is hidden when idle).
/// Part 13: a page that has no button (Market, Brain, Signals, Dual Bot, AI, Diagnostics) lights the MORE tab, because it opens from there. Dart NOT compiled.
class BottomNavBar extends StatefulWidget {
  final int currentIndex;
  final ValueChanged<int> onTap;

  const BottomNavBar({
    super.key,
    required this.currentIndex,
    required this.onTap,
  });

  @override
  State<BottomNavBar> createState() => _BottomNavBarState();
}

class _BottomNavBarState extends State<BottomNavBar> {
  // The visible tab -> the screen index it opens (7 = Brain screen, 6 = More).
  static final List<int> _screens = AppRoutes.barScreens; // Part 27: from the route map

  static const List<String> _labels = ['Home', 'Positions', 'Sniper', 'Study Lab', 'More'];

  int _last = 0; // the bubble stays where it was while no tab is lit

  // Which visible tab is lit (-1 = none).
  int get _lit {
    final i = _screens.indexOf(widget.currentIndex);
    if (i >= 0) return i;
    final r = AppRoutes.fromScreenIndex(widget.currentIndex);
    return r != null && AppRoutes.underGear.contains(r) ? _screens.length - 1 : -1;
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final lit = _lit;
    if (lit >= 0) _last = lit;
    // E9: a FLAT bar. The lit tab is a gradient pill INSIDE the bar (icon + name), idle tabs are icons. Nothing rises above the bar, so no space is lost on any screen.
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(AppSpacing.barSide, 0, AppSpacing.barSide, 8),
        child: Container(
          height: AppSpacing.barHeight,
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 7),
          decoration: BoxDecoration(color: p.surfaceElevated, borderRadius: BorderRadius.circular(AppSpacing.radiusBar), border: Border.all(color: p.border, width: 1)),
          child: Row(children: [for (var i = 0; i < _labels.length; i++) Expanded(flex: lit == i ? 5 : 3, child: _tab(p, i, lit == i))]),
        ),
      ),
    );
  }

  Widget _tab(AppPalette p, int index, bool selected) {
    return Semantics(
      button: true,
      selected: selected,
      label: _labels[index],
      child: OWLPressable(
        // Tapping the open tab again is passed on too: the app scrolls it to the top.
        onTap: () => widget.onTap(_screens[index]),
        child: AnimatedContainer(
          duration: OwlMotion.slide,
          curve: OwlMotion.spring,
          margin: const EdgeInsets.symmetric(horizontal: 2),
          decoration: BoxDecoration(
            gradient: selected ? OwlLook.accentGradient(p) : null,
            borderRadius: BorderRadius.circular(AppSpacing.radiusBar),
          ),
          child: Center(
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              OwlNavIcon(index: index, lit: selected, color: selected ? Colors.white : p.textMuted, size: 22),
              if (selected) ...[
                const SizedBox(width: 5),
                Flexible(child: Text(_labels[index], maxLines: 1, overflow: TextOverflow.clip, style: AppTypography.metadata.copyWith(fontSize: 11.5, color: Colors.white, fontWeight: FontWeight.w800))),
              ],
            ]),
          ),
        ),
      ),
    );
  }
}
