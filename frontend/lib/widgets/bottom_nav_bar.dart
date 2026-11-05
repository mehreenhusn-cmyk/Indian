import 'package:flutter/material.dart';
import '../navigation/app_routes.dart';
import '../theme/app_motion2.dart';
import '../theme/app_theme.dart';
import 'owl_nav_icons.dart';
import 'owl_pressable.dart';

/// Bottom navigation - same public API as before (currentIndex + onTap, both are SCREEN indexes of main.dart).
/// Part P-B (new look): a FLOATING rounded bar. The lit tab is a round bubble lifted over the bar (accent gradient, filled icon, a ring in the page colour so it looks cut out),
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
    const lift = AppSpacing.barLift;
    const bubble = AppSpacing.barBubble;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(AppSpacing.barSide, 0, AppSpacing.barSide, 8),
        child: SizedBox(
          height: lift + AppSpacing.barHeight,
          child: LayoutBuilder(builder: (context, c) {
            final tabW = c.maxWidth / _labels.length;
            return Stack(clipBehavior: Clip.none, children: [
              // the bar
              Positioned(
                left: 0,
                right: 0,
                top: lift,
                height: AppSpacing.barHeight,
                child: Container(decoration: BoxDecoration(color: p.surfaceElevated, borderRadius: BorderRadius.circular(AppSpacing.radiusBar), border: Border.all(color: p.border, width: 1))),
              ),
              // the lit bubble (slides)
              AnimatedPositioned(
                duration: OwlMotion.slide,
                curve: OwlMotion.spring,
                left: _last * tabW + (tabW - bubble) / 2,
                top: 0,
                width: bubble,
                height: bubble,
                child: AnimatedOpacity(
                  duration: OwlMotion.fade,
                  opacity: lit >= 0 ? 1 : 0,
                  child: DecoratedBox(
                    decoration: BoxDecoration(shape: BoxShape.circle, gradient: OwlLook.accentGradient(p), border: Border.all(color: p.bg, width: 4)),
                    child: Center(child: OwlNavIcon(index: _last, lit: true, color: Colors.white, size: 22)),
                  ),
                ),
              ),
              // tabs: icon (idle) or label (lit), full height tap area
              Row(children: [for (var i = 0; i < _labels.length; i++) Expanded(child: _tab(p, i, lit == i))]),
            ]);
          }),
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
        child: SizedBox(
          height: AppSpacing.barLift + AppSpacing.barHeight,
          child: Stack(alignment: Alignment.center, children: [
            // idle icon sits in the middle of the bar; it fades out when its tab is lit (the bubble holds the icon then)
            Positioned(
              top: AppSpacing.barLift + (AppSpacing.barHeight - 24) / 2,
              child: AnimatedOpacity(duration: OwlMotion.fade, opacity: selected ? 0 : 1, child: OwlNavIcon(index: index, lit: false, color: p.textMuted)),
            ),
            // label only under the lit bubble
            Positioned(
              top: AppSpacing.barBubble + 3,
              child: AnimatedOpacity(
                duration: OwlMotion.fade,
                opacity: selected ? 1 : 0,
                child: Text(_labels[index], maxLines: 1, overflow: TextOverflow.clip, style: AppTypography.metadata.copyWith(fontSize: 11, color: p.textPrimary, fontWeight: FontWeight.w700)),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}
