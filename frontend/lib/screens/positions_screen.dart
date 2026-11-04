import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_pressable.dart';
import 'ledger_screen.dart';
import 'positions_live_view.dart';
import 'results_screen.dart';

/// R22a: no hint line, no count in the tab name, tabs 14 sp. Round 14: the Positions TAB. Three parts behind one segmented bar (UI rules 1 and 7):
///   Live     the open trades with close, close-all, panic, TP and SL (the old Positions screen, moved word for word to positions_live_view.dart)
///   Ledger   the Knowledge Ledger: what the research found, with sample sizes (read-only, same screen as in the gear page)
///   Results  which groups of closed trades make or lose money (read-only, same screen as in the gear page)
/// A part is built the first time it is opened and then kept alive, so Ledger and Results load nothing until you tap them,
/// and switching back to Live never rebuilds the list. The gear page keeps its own Ledger and Results rows (nothing removed).
class PositionsScreen extends StatefulWidget {
  const PositionsScreen({super.key});

  @override
  State<PositionsScreen> createState() => _PositionsScreenState();
}

class _PositionsScreenState extends State<PositionsScreen> {
  static const List<String> _names = ['Live', 'Ledger', 'Results'];

  int _tab = 0;
  final Set<int> _seen = {0};

  void _select(int i) {
    if (i == _tab) return;
    setState(() {
      _tab = i;
      _seen.add(i);
    });
  }

  Widget _page(int i) {
    if (!_seen.contains(i)) return const SizedBox.shrink();
    switch (i) {
      case 0:
        return const PositionsLiveView();
      case 1:
        return const LedgerScreen();
      default:
        return const ResultsScreen();
    }
  }

  // R25: plain text tabs: selected = bold + a short underline, the others grey. No box, no border, no tint.
  Widget _segment(BuildContext context, int i) {
    final p = context.palette;
    final on = i == _tab;
    return Expanded(
      child: OWLPressable(
        pressedScale: 0.97,
        onTap: () => _select(i),
        child: Container(
          alignment: Alignment.center,
          padding: const EdgeInsets.only(top: 8, bottom: 6),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_names[i], style: _label(context, on)),
              const SizedBox(height: 5),
              Container(height: 2.5, width: 22, decoration: BoxDecoration(color: on ? p.textPrimary : Colors.transparent, borderRadius: BorderRadius.circular(2))),
            ],
          ),
        ),
      ),
    );
  }

  TextStyle _label(BuildContext context, bool on) {
    final p = context.palette;
    return context.type.primary.copyWith(fontSize: 16, fontWeight: on ? FontWeight.w700 : FontWeight.w500, color: on ? p.textPrimary : p.textMuted);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Material(
      type: MaterialType.transparency,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SafeArea(
            bottom: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 0),
              child: Row(children: [for (var i = 0; i < _names.length; i++) _segment(context, i)]),
            ),
          ),
          const SizedBox(height: AppSpacing.xs), // R22a: the grey hint line under the tabs is gone (it repeated the tab name)
          Expanded(child: IndexedStack(index: _tab, children: [for (var i = 0; i < _names.length; i++) _page(i)])),
        ],
      ),
    );
  }
}
