import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_motion2.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import '../widgets/owl_number.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_row.dart';
import '../widgets/sniper_positions.dart';
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
  static const List<String> _names = ['Live', 'Sniper', 'Ledger', 'Results']; // R29b: Sniper = the open Sniper paper trades + chart

  int _tab = 0;
  int _liveReq = -1; // Plan C: last seen AppProvider.positionsLiveReq
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
        return const SniperPositions();
      case 2:
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
          padding: const EdgeInsets.only(top: 6, bottom: 4),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_names[i], style: _label(context, on)),
              const SizedBox(height: 5),
              AnimatedContainer(duration: OwlMotion.slide, curve: OwlMotion.smooth, height: 2.5, width: on ? 22 : 8, decoration: BoxDecoration(color: on ? p.textPrimary : Colors.transparent, borderRadius: BorderRadius.circular(2))),
            ],
          ),
        ),
      ),
    );
  }

  TextStyle _label(BuildContext context, bool on) {
    final p = context.palette;
    return context.type.primary.copyWith(fontSize: 15, fontWeight: on ? FontWeight.w700 : FontWeight.w500, color: on ? p.textPrimary : p.textMuted);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    // Plan C: arriving from the Dashboard (Open P&L / Positions tile) always lands on the Live tab.
    final req = context.select<AppProvider, int>((x) => x.positionsLiveReq);
    if (_liveReq == -1) {
      _liveReq = req;
    } else if (req != _liveReq) {
      _liveReq = req;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _select(0);
      });
    }
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
          // P-F: pinned summary line (Live tab): the source is named (Main bot, paper or live), then how many are open and the open P&L.
          if (_tab == 0)
            Selector<AppProvider, String>(
              selector: (_, x) => '${(x.openPnl * 100).round()}|${x.status['open_count']}|${x.statsMode}|${x.settings['inr_rate']}',
              builder: (context, _, __) {
                final x = context.read<AppProvider>();
                final n = ((x.status['open_count'] ?? 0) as num).toInt();
                final o = x.openPnl;
                return OwlSummaryLine(source: x.statsMode == 'live' ? 'Main bot - live' : 'Main bot - paper', facts: [OwlStat('$n', 'open'), OwlStat(fmtSigned(o), 'USDT open P&L', tone: o > 0 ? 'good' : (o < 0 ? 'bad' : '')), if (fmtInr(o, (x.settings['inr_rate'] as num?)?.toDouble() ?? 0.0) != null) OwlStat(fmtInr(o, (x.settings['inr_rate'] as num?)?.toDouble() ?? 0.0)!, 'approx.')]);
              },
            ),
          Expanded(child: IndexedStack(index: _tab, children: [for (var i = 0; i < _names.length; i++) _page(i)])),
        ],
      ),
    );
  }
}
