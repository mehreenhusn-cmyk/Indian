import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_pressable.dart';
import 'ledger_screen.dart';
import 'positions_live_view.dart';
import 'results_screen.dart';

/// Round 14: the Positions TAB. Three parts behind one segmented bar (UI rules 1 and 7):
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
  static const List<String> _hints = [
    'Open trades: close, take profit, stop loss',
    'What the research found, with sample sizes (read-only)',
    'Which groups of closed trades make or lose money (read-only)',
  ];

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

  Widget _segment(BuildContext context, int i) {
    final p = context.palette;
    final on = i == _tab;
    return Expanded(
      child: OWLPressable(
        pressedScale: 0.97,
        onTap: () => _select(i),
        child: Container(
          alignment: Alignment.center,
          padding: const EdgeInsets.symmetric(vertical: 8),
          decoration: BoxDecoration(
            color: on ? p.accent.withOpacity(0.16) : Colors.transparent,
            borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
            border: Border.all(color: on ? p.accent : Colors.transparent),
          ),
          child: i == 0
              ? Selector<AppProvider, int>(
                  selector: (_, x) => x.positions.length,
                  builder: (context, n, _) => Text(n > 0 ? 'Live ($n)' : 'Live', style: _label(context, on)),
                )
              : Text(_names[i], style: _label(context, on)),
        ),
      ),
    );
  }

  TextStyle _label(BuildContext context, bool on) {
    final p = context.palette;
    return context.type.primary.copyWith(fontWeight: on ? FontWeight.w800 : FontWeight.w600, color: on ? p.accent : p.textSecondary);
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
              child: Container(
                padding: const EdgeInsets.all(3),
                decoration: BoxDecoration(
                  color: p.surface,
                  borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 3),
                  border: Border.all(color: p.border),
                ),
                child: Row(children: [for (var i = 0; i < _names.length; i++) _segment(context, i)]),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.xs, AppSpacing.l, AppSpacing.xs),
            child: Text(_hints[_tab], maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata),
          ),
          Expanded(child: IndexedStack(index: _tab, children: [for (var i = 0; i < _names.length; i++) _page(i)])),
        ],
      ),
    );
  }
}
