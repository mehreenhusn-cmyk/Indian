import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../screens/app_problems_screen.dart';
import '../theme/app_motion2.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'dashboard_bits.dart';
import 'live_status_chip.dart';
import 'owl_number.dart';
import 'owl_pressable.dart';
import 'owl_route.dart';
import 'owl_row.dart';

/// Part P-D: ONE status header on the Dashboard. It replaces the three loose lines under the title (bot pill + BE / WS / ms, LIVE chip + coins watched, last catch-up).
///   Line 1  "Dashboard" + the BOT ON / OFF pill (the same MasterTradingTogglePill, nothing about it changed).
///   Line 2  ONE tappable row of small facts: BE dot, WS dot, ms (green / amber / red / grey), the live-feed chip, N coins; while LIVE trading is on, an amber LIVE TRADING dot that pulses slowly (2 s).
///   Tap     a sheet opens in 280 ms (at most about 56% of the screen, no scroll) with four rows: BOT, CONNECTION, DATA (+ the last catch-up in IST), PROBLEMS (count, tap = App Problems).
/// Read only: no setting is written here except the existing bot pill. Colours come from the palette; red / green only mean status. Dart NOT compiled.
class OwlStatusHeader extends StatelessWidget {
  final Map<String, dynamic> status;

  const OwlStatusHeader({super.key, required this.status});

  void _openSheet(BuildContext context) {
    final p = context.palette;
    final nav = Navigator.of(context);
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: p.surface,
      showDragHandle: true,
      sheetAnimationStyle: AnimationStyle(duration: OwlMotion.sheet, curve: OwlMotion.smooth),
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(AppSpacing.radiusLarge))),
      builder: (sheetCtx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, 0, AppSpacing.l, AppSpacing.l),
          child: Consumer<AppProvider>(builder: (context, pr, _) => _Details(pr: pr, onProblems: () {
            Navigator.of(sheetCtx).pop();
            nav.push(OwlRoute(builder: (_) => const AppProblemsScreen()));
          })),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final pr = context.read<AppProvider>();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text('Dashboard', style: context.type.section.copyWith(fontSize: 22, fontWeight: FontWeight.w800)),
        MasterTradingTogglePill(
          enabled: (pr.settings['trading_enabled'] as bool?) ?? true,
          onToggle: (next) => pr.updateSettings({'trading_enabled': next}).then((r) => r != null && r['trading_enabled'] == next),
        ),
      ]),
      const SizedBox(height: AppSpacing.s),
      OWLPressable(
        pressedScale: 0.99,
        onTap: () => _openSheet(context),
        child: Selector<AppProvider, int>(
          selector: (_, p) => Object.hash(p.error == null, p.wsConnected, p.wsLatencyMs, p.settings['live_trading_enabled']),
          builder: (context, _, __) => _DotRow(pr: context.read<AppProvider>(), coins: ((status['symbols_tracked'] ?? 0) as num).toInt()),
        ),
      ),
    ]);
  }
}

class _DotRow extends StatelessWidget {
  final AppProvider pr;
  final int coins;

  const _DotRow({required this.pr, required this.coins});

  Widget _fact(BuildContext context, String label, Color dot) => Row(mainAxisSize: MainAxisSize.min, children: [
        Text(label, style: context.type.metadata.copyWith(color: context.palette.textSecondary, fontWeight: FontWeight.w700)),
        const SizedBox(width: 4),
        Container(width: 7, height: 7, decoration: BoxDecoration(color: dot, shape: BoxShape.circle)),
      ]);

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final ms = pr.wsConnected ? pr.wsLatencyMs : null;
    final liveTrading = pr.settings['live_trading_enabled'] == true;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.s),
      child: Row(children: [
        Expanded(
          child: Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 12, runSpacing: 4, children: [
            _fact(context, 'BE', pr.error == null ? p.profit : p.loss),
            _fact(context, 'WS', pr.wsConnected ? p.profit : p.loss),
            Text(ms == null ? '-- ms' : '$ms ms', style: context.type.number.copyWith(fontSize: 12, fontWeight: FontWeight.w600, color: OwlLook.ping(p, ms))),
            const LiveStatusChip(),
            Text('$coins coins', style: context.type.metadata),
            if (liveTrading) _LiveTradingDot(color: OwlLook.live(p)),
          ]),
        ),
        Icon(Icons.expand_less_rounded, size: 18, color: p.textMuted),
      ]),
    );
  }
}

/// The amber "LIVE TRADING" mark: its dot breathes slowly (2 s) so real money is never mistaken for paper. Only built while live trading is on.
class _LiveTradingDot extends StatefulWidget {
  final Color color;

  const _LiveTradingDot({required this.color});

  @override
  State<_LiveTradingDot> createState() => _LiveTradingDotState();
}

class _LiveTradingDotState extends State<_LiveTradingDot> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 2))..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Row(mainAxisSize: MainAxisSize.min, children: [
      FadeTransition(
        opacity: Tween<double>(begin: 0.3, end: 1.0).animate(CurvedAnimation(parent: _c, curve: Curves.easeInOut)),
        child: Container(width: 8, height: 8, decoration: BoxDecoration(color: widget.color, shape: BoxShape.circle)),
      ),
      const SizedBox(width: 5),
      Text('LIVE TRADING', style: context.type.metadata.copyWith(color: widget.color, fontWeight: FontWeight.w800, letterSpacing: 0.6, fontSize: 11)),
    ]);
  }
}

/// The sheet body: four one-line rows in ONE card, then the catch-up line. No scroll: it is short on purpose.
class _Details extends StatelessWidget {
  final AppProvider pr;
  final VoidCallback onProblems;

  const _Details({required this.pr, required this.onProblems});

  @override
  Widget build(BuildContext context) {
    final botOn = (pr.settings['trading_enabled'] as bool?) ?? true;
    final live = pr.settings['live_trading_enabled'] == true;
    final beOk = pr.error == null;
    final wsMs = pr.wsConnected ? pr.wsLatencyMs : null;
    final exchange = ((pr.settings['active_exchange'] as String?) ?? 'binance').toUpperCase();
    final feed = pr.liveState;
    final coins = ((pr.status['symbols_tracked'] ?? 0) as num).toInt();
    final connTone = !beOk ? 'bad' : (pr.wsConnected ? 'good' : 'warn');
    final connWord = !beOk ? 'BE DOWN' : (pr.wsConnected ? 'OK' : 'WS DOWN');
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
      OwlListCard(children: [
        OwlRow(title: 'Bot', sub: live ? 'LIVE trading (real money)' : 'PAPER (practice money)', trailing: OwlPill(botOn ? 'ON' : 'OFF', tone: botOn ? 'good' : 'warn')),
        OwlRow(title: 'Connection', sub: 'BE ${beOk ? 'ok' : 'down'} · WS ${wsMs == null ? '--' : '$wsMs ms'} · $exchange', trailing: OwlPill(connWord, tone: connTone)),
        OwlRow(title: 'Data', sub: '$coins coins watched', trailing: OwlPill(feed == 'live' ? 'LIVE' : (feed == 'delayed' ? 'DELAYED' : 'OFFLINE'), tone: feed == 'live' ? 'good' : (feed == 'delayed' ? 'warn' : 'bad'))),
        _ProblemsRow(onTap: onProblems),
      ]),
      if (pr.status['last_reconcile'] is Map) CatchUpLine(Map<String, dynamic>.from(pr.status['last_reconcile'] as Map)),
    ]);
  }
}

/// PROBLEMS row: asks GET /api/v2/app_problems once when the sheet opens (same call the Dashboard Diagnostics section uses); tap opens the full App Problems page.
class _ProblemsRow extends StatefulWidget {
  final VoidCallback onTap;

  const _ProblemsRow({required this.onTap});

  @override
  State<_ProblemsRow> createState() => _ProblemsRowState();
}

class _ProblemsRowState extends State<_ProblemsRow> {
  Map<String, dynamic>? _d;

  @override
  void initState() {
    super.initState();
    context.read<AppProvider>().fetchAppProblems().then((r) {
      if (mounted) setState(() => _d = r);
    });
  }

  @override
  Widget build(BuildContext context) {
    final d = _d;
    final st = d == null ? '' : '${d['state']}';
    final c = d?['counts'];
    final bad = c is Map ? ((c['BAD'] ?? 0) as num).toInt() : 0;
    final warn = c is Map ? ((c['WARN'] ?? 0) as num).toInt() : 0;
    final ok = st == 'OK' || st == 'PROBLEMS';
    final word = d == null ? '...' : (!ok ? 'N/A' : (bad > 0 ? '$bad BAD' : (warn > 0 ? '$warn WARN' : 'NONE')));
    final tone = !ok ? '' : (bad > 0 ? 'bad' : (warn > 0 ? 'warn' : 'good'));
    final sub = d == null ? 'Loading...' : (!ok ? 'Not available from this backend right now' : '$bad bad · $warn warn · tap for the full list');
    return OwlRow(title: 'Problems', sub: sub, trailing: OwlPill(word, tone: tone), onTap: widget.onTap);
  }
}
