import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../providers/app_provider.dart';
import '../config_flags.dart';
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

  static const List<String> _labels = kLite ? ['Home', 'Positions', 'Signals', 'Pump/Dump', 'More'] : ['Home', 'Positions', 'Sniper', 'Study Lab', 'More']; // PHONE LITE: 5 tabs (Pump/Dump added 26 Nov 2026)

  int _last = 0; // the bubble stays where it was while no tab is lit

  // Round F1 (26 Nov 2026): the owner can change the bar look. Long-press the bar -> choose Pill / Dock / Minimal. Saved on the phone.
  static const String _prefKey = 'owl_bar_style';
  String _style = 'dock';

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((pr) {
      final v = pr.getString(_prefKey);
      if (v != null && (v == 'pill' || v == 'dock' || v == 'minimal') && mounted) setState(() => _style = v);
    }).catchError((_) {});
  }

  Future<void> _setStyle(String v) async {
    setState(() => _style = v);
    try {
      final pr = await SharedPreferences.getInstance();
      await pr.setString(_prefKey, v);
    } catch (_) {}
  }

  void _customize() {
    final p = context.palette;
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: p.surfaceElevated,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(18))),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Customize bottom bar', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 4),
            Text('Pick how the bar looks. Saved on this phone.', style: TextStyle(fontSize: 12, color: p.textMuted)),
            const SizedBox(height: 10),
            for (final o in const [
              ['dock', 'Dock', 'Icon and name on every tab, a glowing line on the open tab'],
              ['pill', 'Pill', 'The open tab is a coloured pill with its name'],
              ['minimal', 'Minimal', 'Icons only, a small dot under the open tab'],
            ])
              ListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                title: Text(o[1], style: TextStyle(fontWeight: FontWeight.w700, color: p.textPrimary)),
                subtitle: Text(o[2], style: TextStyle(fontSize: 11.5, color: p.textMuted)),
                trailing: Icon(_style == o[0] ? Icons.radio_button_checked : Icons.radio_button_off, color: _style == o[0] ? p.accent : p.textMuted),
                onTap: () {
                  _setStyle(o[0]);
                  Navigator.of(ctx).pop();
                },
              ),
          ]),
        ),
      ),
    );
  }

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
    final dock = _style == 'dock';
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(AppSpacing.barSide, 0, AppSpacing.barSide, 8),
        child: GestureDetector(
          onLongPress: _customize,
          child: Container(
            height: dock ? 62.0 : AppSpacing.barHeight,
            padding: EdgeInsets.symmetric(horizontal: 6, vertical: dock ? 5 : 7),
            decoration: BoxDecoration(
              color: p.surfaceElevated,
              borderRadius: BorderRadius.circular(AppSpacing.radiusBar),
              border: Border.all(color: p.border, width: 1),
              boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.22), blurRadius: 14, offset: const Offset(0, 4))],
            ),
            child: Row(children: [
              for (var i = 0; i < _labels.length; i++)
                Expanded(flex: _style == 'pill' && lit == i ? (kLite ? 7 : 5) : 3, child: _style == 'pill' ? _tab(p, i, lit == i) : _tabDock(p, i, lit == i, dock)),
            ]),
          ),
        ),
      ),
    );
  }

  /// Dock and Minimal looks (Round F1). Dock: icon + name on every tab, the open tab in the accent colour with a glowing line on top.
  /// Minimal: icons only, a small dot under the open tab.
  Widget _tabDock(AppPalette p, int index, bool selected, bool withLabel) {
    final c = selected ? p.accent : p.textMuted;
    return Semantics(
      button: true,
      selected: selected,
      label: _labels[index],
      child: OWLPressable(
        onTap: () => widget.onTap(_screens[index]),
        // Part 11: a soft accent tint sits behind the open tab (Dock look only); the glowing line on top stays.
        child: AnimatedContainer(
          duration: OwlMotion.slide,
          margin: const EdgeInsets.symmetric(horizontal: 2),
          decoration: BoxDecoration(color: selected && withLabel ? p.accent.withOpacity(0.10) : Colors.transparent, borderRadius: BorderRadius.circular(18)),
          child: Stack(alignment: Alignment.center, children: [
          if (selected && withLabel)
            Positioned(
              top: 0,
              child: Container(width: 22, height: 3, decoration: BoxDecoration(color: p.accent, borderRadius: BorderRadius.circular(3), boxShadow: [BoxShadow(color: p.accent.withOpacity(0.7), blurRadius: 8)])),
            ),
          Column(mainAxisSize: MainAxisSize.min, children: [
            _pdBadge(index, selected, p, OwlNavIcon(index: index, lit: selected, color: c, size: 22)),
            if (withLabel) ...[
              const SizedBox(height: 2),
              Text(_labels[index], maxLines: 1, overflow: TextOverflow.clip, style: TextStyle(fontSize: 10.5, height: 1.1, color: c, fontWeight: selected ? FontWeight.w800 : FontWeight.w600)),
            ] else ...[
              const SizedBox(height: 4),
              AnimatedContainer(duration: OwlMotion.slide, width: selected ? 14 : 0, height: 3, decoration: BoxDecoration(color: p.accent, borderRadius: BorderRadius.circular(3))),
            ],
          ]),
        ])),
      ),
    );
  }

  /// A small dot on the Pump/Dump tab when a new START alert came while another tab was open (the count is cleared when that tab opens).
  Widget _pdBadge(int index, bool selected, AppPalette p, Widget icon) {
    if (!kLite || _screens[index] != AppRoutes.screenIndex(AppRoute.pumpDump) || selected) return icon;
    final n = context.select<AppProvider, int>((v) => v.pdNewCount);
    if (n <= 0) return icon;
    return Stack(clipBehavior: Clip.none, children: [
      icon,
      Positioned(right: -3, top: -3, child: Container(width: 9, height: 9, decoration: BoxDecoration(color: p.loss, shape: BoxShape.circle, border: Border.all(color: p.surfaceElevated, width: 1.5)))),
    ]);
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
              _pdBadge(index, selected, p, OwlNavIcon(index: index, lit: selected, color: selected ? Colors.white : p.textMuted, size: 22)),
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
