import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../widgets/signal_tile.dart';
import '../widgets/owl_card.dart';
import '../utils/signal_status.dart';
import '../utils/format.dart';
import '../widgets/owl_empty_state.dart';
import '../widgets/owl_skeleton.dart';
import '../widgets/owl_refresh.dart';
import '../theme/app_theme.dart';

/// Trading-day date 'YYYY-MM-DD' for "now" minus N days. A day runs 5:30 AM IST to 5:30 AM IST = 00:00 UTC,
/// so the UTC date is the trading day (same as the Dashboard Today ring).
String _istDay(int daysBack) {
  final d = DateTime.now().toUtc().subtract(Duration(days: daysBack));
  return '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
}

String _dayTitle(String? ymd) {
  if (ymd == null || ymd.isEmpty) return 'Older';
  if (ymd == _istDay(0)) return 'Today';
  if (ymd == _istDay(1)) return 'Yesterday';
  const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  final parts = ymd.split('-');
  if (parts.length != 3) return ymd;
  final mi = int.tryParse(parts[1]) ?? 1;
  return '${int.tryParse(parts[2]) ?? parts[2]} ${m[(mi - 1).clamp(0, 11)]}';
}

/// One signal together with what became of it.
class _Item {
  final Map<String, dynamic> sg;
  final SignalOutcome out;
  final String? day;
  final String key;
  const _Item(this.sg, this.out, this.day, this.key);
}

/// Totals for a group of signals.
class _Totals {
  int total = 0;
  int opened = 0;
  int wins = 0;
  int losses = 0;
  int skipped = 0;
  double net = 0;

  void add(_Item it) {
    total++;
    if (it.sg['opened'] == true) opened++;
    switch (it.out.kind) {
      case SignalOutcomeKind.win:
        wins++;
        break;
      case SignalOutcomeKind.loss:
        losses++;
        break;
      case SignalOutcomeKind.skipped:
        skipped++;
        break;
      default:
        break;
    }
    final v = it.out.pnl;
    if (v != null) net += v;
  }

  int get decided => wins + losses;
  double? get winRate => decided == 0 ? null : wins * 100 / decided;
}

class _SummaryRow {
  final _Totals today;
  final _Totals all;
  const _SummaryRow(this.today, this.all);
}

class _ChipsRow {
  final Map<String, int> counts;
  const _ChipsRow(this.counts);
}

class SignalsScreen extends StatefulWidget {
  const SignalsScreen({super.key});

  @override
  State<SignalsScreen> createState() => _SignalsScreenState();
}

class _SignalsScreenState extends State<SignalsScreen> {
  String _filter = 'all'; // all | open | won | lost | skipped
  final Set<String> _expanded = {};

  bool _match(SignalOutcomeKind k) {
    switch (_filter) {
      case 'open':
        return k == SignalOutcomeKind.open || k == SignalOutcomeKind.opened;
      case 'won':
        return k == SignalOutcomeKind.win;
      case 'lost':
        return k == SignalOutcomeKind.loss;
      case 'skipped':
        return k == SignalOutcomeKind.skipped;
      default:
        return true;
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = context.type;

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.l),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Selector<AppProvider, int>(
                selector: (_, p) => p.signalsRev,
                builder: (context, _rev, child) {
                  final provider = context.read<AppProvider>();
                  return Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text('Signals', style: t.section.copyWith(fontSize: 22, fontWeight: FontWeight.bold)),
                      if (provider.signals.isNotEmpty) Text('${provider.signals.length} total', style: t.metadata),
                    ],
                  );
                },
              ),
              const SizedBox(height: AppSpacing.m),
              Expanded(
                child: OWLRefresh(
                  onRefresh: () => context.read<AppProvider>().fetchSignals(),
                  child: Selector<AppProvider, int>(
                    selector: (_, p) => Object.hash(
                      p.signalsRev,
                      p.alertsRev,
                      p.status.isEmpty,
                      p.error,
                      Object.hashAll(p.positions.map((x) => x is Map ? '${x['symbol']}${x['action']}' : '')),
                    ),
                    builder: (context, _rev, child) => _body(context),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _body(BuildContext context) {
    final t = context.type;
    final provider = context.read<AppProvider>();
    final signals = provider.signals.whereType<Map>().map((e) => e.cast<String, dynamic>()).toList();
    if (signals.isEmpty && provider.status.isEmpty && provider.error == null) {
      // First load only: grey placeholder cards.
      return ListView(
        physics: owlPullPhysics,
        children: List.generate(
          4,
          (_) => const Padding(
            padding: EdgeInsets.only(bottom: AppSpacing.s),
            child: OWLSkeleton.card(height: 96),
          ),
        ),
      );
    }
    if (signals.isEmpty) {
      return const OWLPullEmpty(
        child: OWLEmptyState(
          icon: Icons.sensors_off_rounded,
          title: 'No signals yet',
          subtitle: 'New signals will show up here when the strategy fires.',
        ),
      );
    }

    // 1) Work out the day and the result of every signal ONCE.
    final items = <_Item>[];
    String? curDay;
    for (var i = 0; i < signals.length; i++) {
      final sg = signals[i];
      final ds = sg['date_str'];
      final day = (ds is String && ds.isNotEmpty) ? ds : curDay;
      curDay = day ?? curDay;
      final out = resolveSignalOutcome(sg, provider.alerts, provider.positions);
      items.add(_Item(sg, out, day, 'sig_${sg['signal_no']}_${sg['symbol']}_${sg['ist_time_str']}_$i'));
    }

    // 2) Totals for the summary card and the filter chips.
    final today = _Totals();
    final all = _Totals();
    final todayKey = _istDay(0);
    final counts = <String, int>{'all': items.length, 'open': 0, 'won': 0, 'lost': 0, 'skipped': 0};
    for (final it in items) {
      all.add(it);
      if (it.day == todayKey) today.add(it);
      switch (it.out.kind) {
        case SignalOutcomeKind.open:
        case SignalOutcomeKind.opened:
          counts['open'] = counts['open']! + 1;
          break;
        case SignalOutcomeKind.win:
          counts['won'] = counts['won']! + 1;
          break;
        case SignalOutcomeKind.loss:
          counts['lost'] = counts['lost']! + 1;
          break;
        case SignalOutcomeKind.skipped:
          counts['skipped'] = counts['skipped']! + 1;
          break;
        default:
          break;
      }
    }

    // 3) Rows: summary, chips, then the signals grouped by day.
    final rows = <dynamic>[_SummaryRow(today, all), _ChipsRow(counts)];
    final shown = items.where((e) => _match(e.out.kind)).toList();
    String? lastDay = '\u0000';
    for (var i = 0; i < shown.length; i++) {
      final dkey = shown[i].day;
      if (dkey != lastDay) {
        final g = _Totals();
        for (var j = i; j < shown.length && shown[j].day == dkey; j++) {
          g.add(shown[j]);
        }
        final netTxt = g.decided == 0 ? '' : '  ·  ${fmtSigned(g.net)} USDT';
        rows.add('${_dayTitle(dkey)}  ·  ${g.total} signals  ·  ${g.wins} won  ·  ${g.losses} lost$netTxt');
        lastDay = dkey;
      }
      rows.add(shown[i]);
    }
    if (shown.isEmpty) {
      rows.add('No signals match this filter.');
    }

    return ListView.builder(
      physics: owlPullPhysics,
      itemCount: rows.length,
      itemBuilder: (context, index) {
        final row = rows[index];
        if (row is _SummaryRow) return _summaryCard(context, row);
        if (row is _ChipsRow) return _chips(context, row.counts);
        if (row is String) {
          return Padding(
            padding: const EdgeInsets.only(top: 10, bottom: 6),
            child: Text(row, style: t.label.copyWith(fontWeight: FontWeight.w800)),
          );
        }
        final it = row as _Item;
        final open = _expanded.contains(it.key);
        return Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.s),
          child: open ? _expandedCard(context, it) : _compact(context, it),
        );
      },
    );
  }

  // ---------------------------------------------------------------- summary

  Widget _summaryCard(BuildContext context, _SummaryRow s) {
    final p = context.palette;
    final t = context.type;
    final td = s.today;
    final netColor = td.net > 0 ? p.profit : (td.net < 0 ? p.loss : p.textSecondary);
    final wr = td.winRate;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.s),
      child: OWLCard(
        padding: const EdgeInsets.all(AppSpacing.m),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text('TODAY', style: t.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 1.2)),
                const Spacer(),
                Text('${fmtSigned(td.net)} USDT',
                    style: t.primary.copyWith(color: netColor, fontWeight: FontWeight.w800, fontSize: 20)),
              ],
            ),
            const SizedBox(height: AppSpacing.m),
            Row(
              children: [
                _stat(t, p, 'Signals', '${td.total}', p.textPrimary),
                _stat(t, p, 'Opened', '${td.opened}', p.accent),
                _stat(t, p, 'Won', '${td.wins}', p.profit),
                _stat(t, p, 'Lost', '${td.losses}', p.loss),
                _stat(t, p, 'Skipped', '${td.skipped}', p.textMuted),
              ],
            ),
            const SizedBox(height: AppSpacing.s + 2),
            Text(
              [
                if (wr != null) 'Win rate today: ${wr.toStringAsFixed(0)}%' else 'No closed trade today yet',
                'All loaded: ${s.all.total} signals, ${s.all.wins} won, ${s.all.losses} lost, net ${fmtSigned(s.all.net)} USDT',
              ].join('\n'),
              style: t.metadata.copyWith(height: 1.4),
            ),
          ],
        ),
      ),
    );
  }

  Widget _stat(AppText t, AppPalette p, String label, String value, Color color) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: t.label.copyWith(fontSize: 10)),
          const SizedBox(height: 2),
          Text(value, style: t.primary.copyWith(color: color, fontWeight: FontWeight.w800, fontSize: 17)),
        ],
      ),
    );
  }

  Widget _chips(BuildContext context, Map<String, int> counts) {
    const labels = {'all': 'All', 'open': 'Open', 'won': 'Won', 'lost': 'Lost', 'skipped': 'Skipped'};
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            for (final e in labels.entries)
              Padding(
                padding: const EdgeInsets.only(right: AppSpacing.s),
                child: ChoiceChip(
                  label: Text('${e.value} ${counts[e.key] ?? 0}'),
                  selected: _filter == e.key,
                  showCheckmark: false,
                  onSelected: (_) => setState(() => _filter = e.key),
                  selectedColor: p.accent.withOpacity(0.25),
                  backgroundColor: p.surfaceElevated,
                  side: BorderSide(color: _filter == e.key ? p.accent : p.border),
                  labelStyle: AppTypography.secondaryData.copyWith(
                    color: _filter == e.key ? p.accent : p.textSecondary,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                  visualDensity: VisualDensity.compact,
                ),
              ),
          ],
        ),
      ),
    );
  }

  // ------------------------------------------------------------------- rows

  /// Result in plain words.
  String _plain(SignalOutcome o) {
    final l = o.label;
    if (l == 'SL HIT') return 'Stopped out';
    if (l == 'TRAIL SL') return 'Trailing stop hit';
    if (l == 'TP % HIT') return 'Profit target hit';
    if (l == 'TP HIT') return 'Target hit';
    if (l.endsWith(' HIT') && l.startsWith('TP')) return 'Target ${l.substring(2, l.length - 4)} hit';
    if (l.contains('→ SL')) return '${l.split(' ').first} done, then stopped';
    if (l == 'REVERSED') return 'Closed by reverse signal';
    if (l == 'MANUAL') return 'Closed by you';
    if (l == 'SKIPPED') return 'Skipped';
    if (l == 'NEW') return 'New';
    if (l == 'OPENED') return 'Opened';
    if (l == 'OLD') return 'Older signal';
    if (l.startsWith('OPEN')) return l.contains('TP') ? 'Open · ${l.split('·').last.trim()} done' : 'Open';
    if (l == 'CLOSED') return 'Closed';
    return l;
  }

  Color _kindColor(AppPalette p, SignalOutcomeKind k) {
    switch (k) {
      case SignalOutcomeKind.fresh:
        return p.owlEye;
      case SignalOutcomeKind.opened:
      case SignalOutcomeKind.open:
        return p.accent;
      case SignalOutcomeKind.win:
        return p.profit;
      case SignalOutcomeKind.loss:
        return p.loss;
      case SignalOutcomeKind.neutral:
        return p.textSecondary;
      case SignalOutcomeKind.skipped:
        return p.textMuted;
    }
  }

  void _toggle(String key) {
    AppHaptics.light();
    setState(() {
      if (!_expanded.add(key)) _expanded.remove(key);
    });
  }

  /// Short row: who, which side, result, profit. Tap to see the full card.
  Widget _compact(BuildContext context, _Item it) {
    final p = context.palette;
    final t = context.type;
    final sg = it.sg;
    final out = it.out;
    final isLong = sg['action'] == 'BUY';
    final sideColor = isLong ? p.profit : p.loss;
    final color = _kindColor(p, out.kind);
    final entry = numOrNull(sg['entry_price']);
    final risk = pctDist(entry, numOrNull(sg['stop_loss']));
    final tp1 = pctDist(entry, numOrNull(sg['tp1']));
    final tf = (sg['timeframe'] is String) ? sg['timeframe'] as String : '';
    final skip = sg['skip_reason'];
    final line2 = [
      '${sg['ist_time_str'] ?? '--'}',
      if (tf.isNotEmpty) tf,
      if (entry != null) 'Entry ${fmtPrice(entry)}',
      if (risk != null) 'Risk ${risk.toStringAsFixed(2)}%',
      if (tp1 != null) 'TP1 +${tp1.toStringAsFixed(2)}%',
    ].join(' · ');

    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => _toggle(it.key),
      child: OWLCard(
        hasPositiveGlow: false,
        hasNegativeGlow: false,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.m, vertical: AppSpacing.s + 2),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(color: sideColor, borderRadius: BorderRadius.circular(4)),
                  child: Text(isLong ? 'LONG' : 'SHORT',
                      style: const TextStyle(color: Colors.white, fontSize: 9.5, fontWeight: FontWeight.w800, letterSpacing: 0.4)),
                ),
                const SizedBox(width: AppSpacing.s),
                Flexible(
                  child: Text(
                    '${sg['symbol'] ?? 'UNKNOWN'}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: t.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 14.5),
                  ),
                ),
                if (sg['signal_no'] != null) ...[
                  const SizedBox(width: 6),
                  Text('#${sg['signal_no']}', style: t.metadata),
                ],
                const Spacer(),
                Text(_plain(out), style: t.metadata.copyWith(color: color, fontWeight: FontWeight.w800, fontSize: 11)),
                if (out.pnl != null) ...[
                  const SizedBox(width: 6),
                  Text(fmtSigned(out.pnl!),
                      style: t.metadata.copyWith(color: out.pnl! >= 0 ? p.profit : p.loss, fontWeight: FontWeight.w800, fontSize: 12)),
                ],
                const SizedBox(width: 2),
                Icon(Icons.expand_more_rounded, size: 18, color: p.textMuted),
              ],
            ),
            const SizedBox(height: 4),
            Text(line2, maxLines: 1, overflow: TextOverflow.ellipsis, style: t.metadata.copyWith(fontSize: 11)),
            if (skip != null) ...[
              const SizedBox(height: 3),
              Text('Why skipped: $skip',
                  maxLines: 2, overflow: TextOverflow.ellipsis, style: t.metadata.copyWith(color: p.textSecondary, fontSize: 11)),
            ],
          ],
        ),
      ),
    );
  }

  /// Full card (the old detailed layout) with a "Show less" line.
  Widget _expandedCard(BuildContext context, _Item it) {
    final p = context.palette;
    final t = context.type;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SignalTile(signal: it.sg, outcome: it.out),
        InkWell(
          onTap: () => _toggle(it.key),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.expand_less_rounded, size: 18, color: p.textMuted),
                const SizedBox(width: 4),
                Text('Show less', style: t.metadata),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
