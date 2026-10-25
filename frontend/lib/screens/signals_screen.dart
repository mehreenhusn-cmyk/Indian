import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../widgets/signal_tile.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/trade_row.dart';
import '../widgets/trade_chart.dart';
import '../widgets/coin_history_sheet.dart';
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
  final String active;
  const _ChipsRow(this.counts, this.active);
}

class SignalsScreen extends StatefulWidget {
  const SignalsScreen({super.key});

  @override
  State<SignalsScreen> createState() => _SignalsScreenState();
}

class _SignalsScreenState extends State<SignalsScreen> {
  String _filter = 'auto'; // auto | running | closed | skipped  (auto = Running when something runs, else Closed)
  final Set<String> _expanded = {};
  bool _btcOnly = false; // BTC chip on top: shows only BTCUSDT signals, with their own summary

  bool _match(String tab, SignalOutcomeKind k) {
    switch (tab) {
      case 'running':
        return k == SignalOutcomeKind.open || k == SignalOutcomeKind.opened || k == SignalOutcomeKind.fresh;
      case 'skipped':
        return k == SignalOutcomeKind.skipped;
      default:
        return k == SignalOutcomeKind.win || k == SignalOutcomeKind.loss || k == SignalOutcomeKind.neutral;
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
                    children: [
                      Text('Signals', style: t.section.copyWith(fontSize: 22, fontWeight: FontWeight.bold)),
                      const SizedBox(width: 10),
                      _btcChip(context),
                      const Spacer(),
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

  /// Small "BTC" switch next to the title. On = only BTCUSDT signals (and their summary).
  Widget _btcChip(BuildContext context) {
    final p = context.palette;
    final on = _btcOnly;
    return OWLPressable(
      onTap: () {
        AppHaptics.light();
        setState(() => _btcOnly = !_btcOnly);
      },
      child: AnimatedContainer(
        duration: AppMotion.base,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
        decoration: BoxDecoration(
          color: on ? p.accent.withOpacity(0.16) : Colors.transparent,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: on ? p.accent.withOpacity(0.45) : p.border),
        ),
        child: Text(
          'BTC',
          style: AppTypography.secondaryData.copyWith(
            color: on ? p.accent : p.textSecondary,
            fontSize: 12,
            fontWeight: FontWeight.w800,
          ),
        ),
      ),
    );
  }

  Widget _body(BuildContext context) {
    final t = context.type;
    final provider = context.read<AppProvider>();
    final allSignals = provider.signals.whereType<Map>().map((e) => e.cast<String, dynamic>()).toList();
    final signals = _btcOnly ? allSignals.where((e) => '${e['symbol']}' == 'BTCUSDT').toList() : allSignals;
    if (allSignals.isEmpty && provider.status.isEmpty && provider.error == null) {
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
      return OWLPullEmpty(
        child: OWLEmptyState(
          icon: Icons.sensors_off_rounded,
          title: _btcOnly ? 'No BTC signal yet' : 'No signals yet',
          subtitle: _btcOnly
              ? 'BTC is always watched with the same EMA50 cross as every coin. Its trades use 1000 USDT at 10x (paper). When BTC fires or is skipped, it shows here with the reason.'
              : 'New signals will show up here when the strategy fires.',
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
    final counts = <String, int>{'running': 0, 'closed': 0, 'skipped': 0};
    for (final it in items) {
      all.add(it);
      if (it.day == todayKey) today.add(it);
      switch (it.out.kind) {
        case SignalOutcomeKind.open:
        case SignalOutcomeKind.opened:
        case SignalOutcomeKind.fresh:
          counts['running'] = counts['running']! + 1;
          break;
        case SignalOutcomeKind.skipped:
          counts['skipped'] = counts['skipped']! + 1;
          break;
        default:
          counts['closed'] = counts['closed']! + 1;
          break;
      }
    }
    final tab = _filter == 'auto' ? ((counts['running'] ?? 0) > 0 ? 'running' : 'closed') : _filter;

    // 3) Rows: summary, chips, then the signals grouped by day.
    final rows = <dynamic>[_SummaryRow(today, all), _ChipsRow(counts, tab)];
    final shown = items.where((e) => _match(tab, e.out.kind)).toList();
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
      rows.add('Nothing in this tab yet.');
    }

    return ListView.builder(
      physics: owlPullPhysics,
      itemCount: rows.length,
      itemBuilder: (context, index) {
        final row = rows[index];
        if (row is _SummaryRow) return _summaryCard(context, row);
        if (row is _ChipsRow) return _tabs(context, row.counts, row.active);
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
          child: _row(context, it, items, open),
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
                Text(_btcOnly ? 'BTC TODAY' : 'TODAY', style: t.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 1.2)),
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
                if (_btcOnly) 'BTC paper size: 1000 USDT at 10x. Tap a trade for its chart, Details for the levels.',
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

  Widget _tabs(BuildContext context, Map<String, int> counts, String active) {
    const labels = [('running', 'Running'), ('closed', 'Closed'), ('skipped', 'Skipped')];
    final p = context.palette;
    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.s),
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: p.surfaceHigher.withOpacity(0.6),
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
        border: Border.all(color: p.border),
      ),
      child: Row(
        children: [
          for (final l in labels)
            Expanded(
              child: OWLPressable(
                onTap: () => setState(() => _filter = l.$1),
                pressedScale: 0.97,
                child: AnimatedContainer(
                  duration: AppMotion.base,
                  alignment: Alignment.center,
                  padding: const EdgeInsets.symmetric(vertical: 9),
                  decoration: BoxDecoration(
                    color: active == l.$1 ? p.accent.withOpacity(0.16) : Colors.transparent,
                    borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
                    border: Border.all(color: active == l.$1 ? p.accent.withOpacity(0.45) : Colors.transparent),
                  ),
                  child: Text(
                    '${l.$2}  ${counts[l.$1] ?? 0}',
                    style: AppTypography.secondaryData.copyWith(
                      color: active == l.$1 ? p.accent : p.textSecondary,
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ),
            ),
        ],
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

  void _toggle(String key) {
    AppHaptics.light();
    setState(() {
      if (!_expanded.add(key)) _expanded.remove(key);
    });
  }

  /// What this signal is, in the shape TradeRow needs.
  TradeRowData _rowData(BuildContext context, _Item it) {
    final sg = it.sg;
    final out = it.out;
    final res = sg['result'] is Map ? Map<String, dynamic>.from(sg['result'] as Map) : <String, dynamic>{};
    final provider = context.read<AppProvider>();

    String status;
    switch (out.kind) {
      case SignalOutcomeKind.open:
      case SignalOutcomeKind.opened:
        status = 'open';
        break;
      case SignalOutcomeKind.win:
        status = 'won';
        break;
      case SignalOutcomeKind.loss:
        status = 'lost';
        break;
      case SignalOutcomeKind.skipped:
        status = 'skipped';
        break;
      case SignalOutcomeKind.fresh:
        status = 'new';
        break;
      case SignalOutcomeKind.neutral:
        status = 'closed';
        break;
    }

    double? last;
    double? pnl = out.pnl;
    if (status == 'open') {
      // Live price (and P&L) from the matching open position.
      for (final x in provider.positions) {
        if (x is Map && '${x['symbol']}' == '${sg['symbol']}' && '${x['signal_no']}' == '${sg['signal_no']}') {
          last = numOrNull(x['ltp']);
          pnl ??= numOrNull(x['pnl_usdt']);
          break;
        }
      }
    } else if (status == 'won' || status == 'lost' || status == 'closed') {
      last = numOrNull(res['exit_px']);
    }

    final plain = _plain(out);
    final skip = sg['skip_reason'];
    final String? baseExtra = skip != null
        ? 'Why skipped: $skip'
        : (plain == 'Open' || plain == 'New' || plain == 'Opened' ? null : plain);
    // BTC rows carry a small tag, so they are easy to find in the all-coins list too.
    final String? extra = '${sg['symbol']}' == 'BTCUSDT' ? (baseExtra == null ? 'BTC' : 'BTC · $baseExtra') : baseExtra;

    return TradeRowData(
      symbol: '${sg['symbol'] ?? 'UNKNOWN'}',
      isLong: sg['action'] == 'BUY',
      status: status,
      entry: numOrNull(sg['entry_price']),
      last: last,
      lastIsLive: status == 'open',
      pnl: pnl,
      openedSec: status == 'skipped' || status == 'new' ? null : (numOrNull(res['opened_ts']) ?? numOrNull(sg['recorded_at'])),
      closedSec: numOrNull(res['closed_ts']),
      fallbackTime: '${sg['ist_time_str'] ?? '--'}',
      extra: extra,
      onTap: () => _openChart(context, it),
    );
  }

  /// Tap a row -> the candle chart with entry, stop-loss, targets and the exit.
  void _openChart(BuildContext context, _Item it) {
    final sg = it.sg;
    final res = sg['result'] is Map ? Map<String, dynamic>.from(sg['result'] as Map) : <String, dynamic>{};
    final k = it.out.kind;
    final closed = k == SignalOutcomeKind.win || k == SignalOutcomeKind.loss || k == SignalOutcomeKind.neutral;
    final running = k == SignalOutcomeKind.open || k == SignalOutcomeKind.opened;
    final map = <String, dynamic>{
      'symbol': sg['symbol'],
      'side': sg['action'] == 'BUY' ? 'BUY' : 'SELL',
      'entry': sg['entry_price'],
      'sl': sg['stop_loss'],
      'tp1': sg['tp1'],
      'tp2': sg['tp2'],
      'tp3': sg['tp3'],
      'tp4': sg['tp4'],
      'opened': res['opened_ts'] ?? sg['recorded_at'],
      'state': closed ? 'closed' : (running ? 'open' : 'none'),
      'tf': sg['timeframe'],
    };
    if (closed) {
      map['closed'] = res['closed_ts'];
      map['exit'] = res['exit_px'];
      map['pnl'] = it.out.pnl;
      map['roi'] = res['roi'];
      map['reason'] = it.out.label;
    }
    showTradeChart(context, map);
  }

  /// Today's trades of this coin (or its latest ones when it has none today).
  void _openHistory(BuildContext context, _Item it, List<_Item> all) {
    final sym = '${it.sg['symbol']}';
    final todayKey = _istDay(0);
    var list = all.where((e) => '${e.sg['symbol']}' == sym && e.day == todayKey).toList();
    var title = '$sym today';
    if (list.isEmpty) {
      list = all.where((e) => '${e.sg['symbol']}' == sym).take(20).toList();
      title = '$sym recent';
    }
    showCoinHistorySheet(context, title: title, rows: [for (final e in list) _rowData(context, e)]);
  }

  Widget _row(BuildContext context, _Item it, List<_Item> all, bool open) {
    final row = TradeRow(
      data: _rowData(context, it),
      detailsOpen: open,
      onDetails: () => _toggle(it.key),
      onHistory: () => _openHistory(context, it, all),
    );
    if (!open) return row;
    // Details: the old full card (levels, targets) under the row.
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        row,
        const SizedBox(height: AppSpacing.s),
        SignalTile(signal: it.sg, outcome: it.out),
      ],
    );
  }
}
