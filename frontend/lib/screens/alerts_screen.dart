import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../widgets/glass_card.dart';
import '../widgets/owl_card.dart';
import '../widgets/candle_chart.dart';
import '../widgets/trade_row.dart';
import '../widgets/trade_chart.dart';
import '../widgets/coin_history_sheet.dart';
import '../widgets/daily_report_card.dart';
import '../widgets/owl_empty_state.dart';
import '../widgets/owl_entrance.dart';
import '../widgets/owl_refresh.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';

/// Alerts feed. Every trade alert is a detailed, expandable card:
///  * header pill = how it ended (TP / SL / trailing SL / universal TP % /
///    reversed / manual / OPEN) + P&L, symbol, side, time
///  * chips = R:R (planned + realized), size & leverage, ROI, duration
///  * tap = full detail: entry / exit / SL / TP1-4 (touched ticks), peak &
///    worst ROI, trigger reason, SL basis, open/close times, a price-ladder
///    bar and a "View chart" button
///  * "catch-up" cards explain what the bot found after a restart / data gap
/// Older alerts without detail data still render as a simple one-line row.
class AlertsScreen extends StatefulWidget {
  const AlertsScreen({super.key});

  @override
  State<AlertsScreen> createState() => _AlertsScreenState();
}

/// Trading-day key of a timestamp. The bot's day starts at 5:30 AM IST, which is exactly 00:00 UTC, so the
/// UTC date IS the trading day. (It used to group by IST midnight, so "Today" here never matched the
/// Dashboard Today ring.)
String _istYmd(num ts) {
  final d = DateTime.fromMillisecondsSinceEpoch((ts * 1000).toInt(), isUtc: true);
  return '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
}

String _dayTitle(String ymd) {
  final now = DateTime.now().toUtc();
  String fmt(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  if (ymd == fmt(now)) return 'Today';
  if (ymd == fmt(now.subtract(const Duration(days: 1)))) return 'Yesterday';
  const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  final p = ymd.split('-');
  if (p.length != 3) return ymd;
  return '${int.tryParse(p[2]) ?? p[2]} ${m[((int.tryParse(p[1]) ?? 1) - 1).clamp(0, 11)]}';
}

/// One collapsible day header in the alerts list.
class _DayHeader {
  final String ymd;
  final String title;
  final int closed;
  final int wins;
  final double net;
  final int alerts;
  const _DayHeader(this.ymd, this.title, this.closed, this.wins, this.net, this.alerts);
}

class _AlertsScreenState extends State<AlertsScreen> {
  String _filter = 'trades'; // calm default: only trade events; System (catch-up/feed/startup) is one tap away
  final Set<String> _expanded = {};
  final Set<String> _flippedDays = {}; // days the user toggled; Today is open and older days are folded by default

  static const _tradeTypes = {'open', 'tp', 'sl', 'reversed', 'manual'};
  static const _skipTypes = {'skip', 'target', 'loss'};

  String _group(String type) {
    if (_tradeTypes.contains(type)) return 'trades';
    if (_skipTypes.contains(type)) return 'skips';
    return 'system';
  }

  String _keyOf(Map a) => '${a['ts'] ?? a['time']}_${a['text']}';

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 0),
          child: Selector<AppProvider, int>(
            selector: (_, p) => p.alertsRev,
            builder: (context, _rev, child) {
              final provider = context.read<AppProvider>();
              final all = provider.alerts.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
              int count(String g) => all.where((a) => _group('${a['type']}') == g).length;
              final shown = _filter == 'all'
                  ? all.where((a) => _group('${a['type']}') != 'system').toList()
                  : all.where((a) => _group('${a['type']}') == _filter).toList();

              // Day headers (Today / Yesterday / date). Today is open, older days are folded behind a chevron
              // so the list never turns into one long scroll. The day total is only for the alerts loaded here.
              final todayYmd = _istYmd(DateTime.now().millisecondsSinceEpoch / 1000);
              bool dayOpen(String ymd) => (ymd == todayYmd) != _flippedDays.contains(ymd);
              final rows = <dynamic>[];
              String? lastYmd;
              var hidden = false;
              for (var i = 0; i < shown.length; i++) {
                final tsv = shown[i]['ts'];
                final ymd = tsv is num ? _istYmd(tsv) : (lastYmd ?? '');
                if (ymd != lastYmd) {
                  var cn = 0, cw = 0, an = 0;
                  double cnet = 0;
                  for (var j = i; j < shown.length; j++) {
                    final tj = shown[j]['ts'];
                    if ((tj is num ? _istYmd(tj) : ymd) != ymd) break;
                    an++;
                    final dj = shown[j]['d'];
                    if (dj is Map && dj['exit_tag'] != null && dj['pnl'] is num) {
                      final v = (dj['pnl'] as num).toDouble();
                      cn++;
                      cnet += v;
                      if (v > 0) cw++;
                    }
                  }
                  rows.add(_DayHeader(ymd, _dayTitle(ymd), cn, cw, cnet, an));
                  hidden = !dayOpen(ymd);
                  lastYmd = ymd;
                }
                if (!hidden) rows.add(shown[i]);
              }

              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Title and filter chips share one row (no big title + empty space).
                  Row(
                    children: [
                      Expanded(
                        child: SingleChildScrollView(
                          scrollDirection: Axis.horizontal,
                          child: Row(
                            children: [
                              _chip(context, 'Trades', 'trades', count('trades')),
                              _chip(context, 'All', 'all', all.length - count('system')),
                              _chip(context, 'Skipped', 'skips', count('skips')),
                              _chip(context, 'System', 'system', count('system')),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                  const _PeriodStrip(),
                  const SizedBox(height: 8),
                  // Yesterday's result from the permanent archive. Shown only when the list below has no "Yesterday" row,
                  // so the same numbers are never printed twice.
                  if (!rows.any((r) => r is _DayHeader && r.title == 'Yesterday')) const DailyReportCard(),
                  Expanded(
                    child: OWLRefresh(
                      onRefresh: () => context.read<AppProvider>().fetchStatus(),
                      child: shown.isEmpty
                        ? OWLPullEmpty(
                            child: OWLEmptyState(
                              icon: Icons.notifications_none_rounded,
                              title: _filter == 'system' ? 'No system notices' : 'No alerts yet',
                              subtitle: 'Trade events, skipped signals and system notices show up here.',
                            ),
                          )
                        : ListView.builder(
                            physics: owlPullPhysics,
                            itemCount: rows.length,
                            itemBuilder: (context, index) {
                              final row = rows[index];
                              if (row is _DayHeader) {
                                final open = dayOpen(row.ymd);
                                final pal = context.palette;
                                final net = row.net;
                                return InkWell(
                                  borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
                                  onTap: () {
                                    AppHaptics.light();
                                    setState(() {
                                      if (!_flippedDays.add(row.ymd)) _flippedDays.remove(row.ymd);
                                    });
                                  },
                                  child: Padding(
                                    padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 2),
                                    child: Row(children: [
                                      Text(row.title,
                                          style: AppTypography.secondaryData.copyWith(
                                              color: pal.textPrimary, fontSize: 13, fontWeight: FontWeight.w800)),
                                      const SizedBox(width: 8),
                                      Expanded(
                                        child: Text(
                                          row.closed > 0
                                              ? '${row.closed} closed  ·  ${net >= 0 ? '+' : ''}${net.toStringAsFixed(2)}  ·  W${row.wins}/L${row.closed - row.wins}'
                                              : '${row.alerts} alerts',
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: AppTypography.secondaryData.copyWith(
                                              color: row.closed == 0 ? pal.textMuted : (net >= 0 ? pal.profit : pal.loss),
                                              fontSize: 11.5,
                                              fontWeight: FontWeight.w700),
                                        ),
                                      ),
                                      AnimatedRotation(
                                        turns: open ? 0.5 : 0,
                                        duration: const Duration(milliseconds: 180),
                                        child: Icon(Icons.expand_more_rounded, size: 22, color: pal.textMuted),
                                      ),
                                    ]),
                                  ),
                                );
                              }
                              final a = row as Map<String, dynamic>;
                              final key = _keyOf(a);
                              final ad = a['d'];
                              final ts = a['ts'];
                              final fresh = ts is num && (DateTime.now().millisecondsSinceEpoch / 1000 - ts) < 10;
                              final freshSl = fresh && ad is Map && ad['exit_tag'] == 'SL';
                              return OwlEntrance(
                                key: ValueKey(key),
                                index: index,
                                shake: freshSl,
                                child: Padding(
                                padding: const EdgeInsets.only(bottom: AppSpacing.cardGap),
                                child: _AlertCard(
                                  alert: a,
                                  expanded: _expanded.contains(key),
                                  onToggle: () {
                                    AppHaptics.light();
                                    setState(() {
                                      if (!_expanded.add(key)) _expanded.remove(key);
                                    });
                                  },
                                ),
                              ));
                            },
                          ),
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  Widget _chip(BuildContext context, String label, String value, int n) {
    return Padding(
      padding: const EdgeInsets.only(right: AppSpacing.s),
      child: OwlFilterChip(label: '$label $n', on: _filter == value, onTap: () => setState(() => _filter = value)),
    );
  }
}

/// Today / 7 days / 30 days closed P&L in one row. Comes from the backend (same numbers as the Dashboard),
/// so Alerts can no longer disagree with it. Paper mode only (hidden in live mode, where the backend sends none).
class _PeriodStrip extends StatelessWidget {
  const _PeriodStrip();

  @override
  Widget build(BuildContext context) {
    return Selector<AppProvider, int>(
      selector: (_, p) => Object.hash(p.closedPnl, p.pnl7d, p.pnl30d, p.trades7d, p.trades30d, p.periodPnl == null),
      builder: (context, _, __) {
        final p = context.read<AppProvider>();
        final per = p.periodPnl;
        if (per == null) return const SizedBox.shrink();
        final pal = context.palette;
        Widget cell(String label, double v, int trades) {
          final c = v > 0 ? pal.profit : (v < 0 ? pal.loss : pal.textMuted);
          return Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: AppTypography.metadata.copyWith(color: pal.textMuted, fontSize: 11)),
              const SizedBox(height: 2),
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text('${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}',
                    style: AppTypography.primaryData.copyWith(color: c, fontSize: 16, fontWeight: FontWeight.w800)),
              ),
              Text('$trades trades', style: AppTypography.metadata.copyWith(color: pal.textMuted, fontSize: 10.5)),
            ]),
          );
        }

        return Padding(
          padding: const EdgeInsets.only(top: 10),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: pal.glassFill,
              borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
              border: Border.all(color: pal.glassBorder),
            ),
            child: Row(children: [
              cell('Today', p.closedPnl, (per['today_trades'] as num?)?.toInt() ?? 0),
              cell('7 days', p.pnl7d, p.trades7d),
              cell('30 days', p.pnl30d, p.trades30d),
            ]),
          ),
        );
      },
    );
  }
}

// ------------------------------------------------------------------ helpers ----

double? _n(dynamic v) => numOrNull(v);

String _price(double? v) => fmtPrice(v);

String _signed(double v, [int dp = 2]) => fmtSigned(v, dp);

String _dur(double? secs) => fmtDuration(secs == null ? null : (secs < 0 ? 0 : secs));

Color _pnlColor(BuildContext context, double? pnl) =>
    (pnl ?? 0) >= 0 ? context.palette.profit : context.palette.loss;

String _shortSym(dynamic s) => '$s'.replaceAll(RegExp(r'USDTM$'), '');

// --------------------------------------------------------------------- card ----

class _AlertCard extends StatelessWidget {
  final Map<String, dynamic> alert;
  final bool expanded;
  final VoidCallback onToggle;

  const _AlertCard({required this.alert, required this.expanded, required this.onToggle});

  Map<String, dynamic>? get _d => alert['d'] is Map ? Map<String, dynamic>.from(alert['d'] as Map) : null;

  @override
  Widget build(BuildContext context) {
    final type = '${alert['type'] ?? 'info'}';
    final text = '${alert['text'] ?? '--'}';
    final time = '${alert['time'] ?? '--'}';
    final d = _d;

    if (d == null) return _simple(context, type, text, time);

    final kind = '${d['kind'] ?? ''}';
    final isClose = d['exit_tag'] != null;
    final pnl = _n(d['pnl']);
    final tag = '${d['exit_tag'] ?? ''}';

    // Pill: how it ended.
    String pill;
    Color color;
    if (type == 'open') {
      pill = 'OPEN';
      color = context.palette.accent;
    } else if (isClose) {
      switch (tag) {
        case 'TP':
          pill = 'TP';
          color = context.palette.profit;
          break;
        case 'SCALP':
          pill = 'TP %';
          color = context.palette.profit;
          break;
        case 'TSL':
          pill = 'TRAIL SL';
          color = _pnlColor(context, pnl);
          break;
        case 'SL':
          pill = 'SL';
          color = context.palette.loss;
          break;
        case 'REV':
          pill = 'REVERSED';
          color = context.palette.warning;
          break;
        case 'MAN':
          pill = 'MANUAL';
          color = context.palette.accent;
          break;
        default:
          pill = tag.isEmpty ? type.toUpperCase() : tag;
          color = _pnlColor(context, pnl);
      }
    } else if (type == 'sync' && kind == 'breakeven') {
      // Distinct grey/neutral tag so a genuine profit trailing-SL exit
      // (TRAIL SL pill above, colored by P&L) never looks the same as a
      // guard-loop TP1->breakeven stop shift, which is neither a profit
      // nor a loss event by itself.
      pill = 'BE';
      color = context.palette.textSecondary;
    } else if (type == 'sync') {
      pill = kind == 'catchup' ? 'CATCH-UP' : (kind == 'outdated' ? 'OUTDATED' : 'FEED');
      color = context.palette.accent;
    } else if (type == 'error') {
      pill = 'ERROR';
      color = context.palette.loss;
    } else if (type == 'skip' || type == 'target' || type == 'loss') {
      pill = type == 'skip' ? 'SKIPPED' : (type == 'target' ? 'TARGET' : 'LOSS LIMIT');
      color = context.palette.warning;
    } else {
      pill = type.toUpperCase();
      color = context.palette.textMuted;
    }

    final symbol = d['symbol'] != null ? _shortSym(d['symbol']) : null;
    final side = d['side'] != null ? '${d['side']}' : null;
    final rr = _n(d['rr_planned']);
    final rReal = _n(d['r_realized']);
    final size = _n(d['size_usdt']);
    final lev = _n(d['leverage']);
    final roi = _n(d['roi']);
    final dur = _n(d['duration_s']);
    final recovered = d['recovered'] == true;
    final reasonLabel = '${d['reason_label'] ?? d['skip_reason'] ?? ''}';
    final useText = kind.isNotEmpty || reasonLabel.isEmpty;

    // Trade open / close alerts get the Binance-style card.
    if (d['symbol'] != null && _n(d['entry']) != null && (type == 'open' || isClose)) {
      // Collapsed = the same clean row as Signals (tap = chart). "Details" opens the full card below.
      if (!expanded) {
        final r = _rowFromAlert(context, alert);
        if (r != null) {
          return TradeRow(
            data: r,
            onDetails: onToggle,
            onHistory: () => _openHistory(context, d, _n(alert['ts'])),
          );
        }
      }
      return _tradeCard(context, d, type: type, isClose: isClose, pill: pill, color: color, pnl: pnl, roi: roi, dur: dur);
    }

    return GlassCard(
      child: InkWell(
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        onTap: onToggle,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.m, AppSpacing.m - 2, AppSpacing.m, AppSpacing.m - 2),
          child: IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(
                  width: 4,
                  decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(2)),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // ---- header ----
                      Row(
                        children: [
                          _pillBox(context, isClose && pnl != null ? '$pill ${_signed(pnl)}' : pill, color),
                          const SizedBox(width: 8),
                          if (symbol != null)
                            Flexible(
                              child: Text(
                                symbol,
                                overflow: TextOverflow.ellipsis,
                                style: context.type.primary.copyWith(fontWeight: FontWeight.w700),
                              ),
                            ),
                          if (side != null) ...[
                            const SizedBox(width: 6),
                            _pillBox(context, side, side == 'BUY' ? context.palette.profit : context.palette.loss, small: true),
                          ],
                          const Spacer(),
                          Text(time, style: context.type.metadata),
                          AnimatedRotation(
                            turns: expanded ? 0.5 : 0,
                            duration: AppMotion.base,
                            curve: AppMotion.standard,
                            child: Icon(Icons.expand_more, size: 18, color: context.palette.textMuted),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      // ---- one-line reason ----
                      Text(
                        useText ? text : reasonLabel + (dur != null && isClose ? ' · ${_dur(dur)}' : ''),
                        style: context.type.secondary.copyWith(fontSize: 12),
                        maxLines: expanded ? 5 : 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 6),
                      // ---- chips ----
                      Wrap(
                        spacing: 6,
                        runSpacing: 4,
                        children: [
                          if (rr != null) _mini(context, 'R:R 1:${rr.toStringAsFixed(1)}', context.palette.textSecondary),
                          if (isClose && rReal != null) _mini(context, '${_signed(rReal, 1)}R', _pnlColor(context, rReal)),
                          if (isClose && roi != null) _mini(context, 'ROI ${_signed(roi)}%', _pnlColor(context, roi)),
                          if (size != null && size > 0)
                            _mini(context, 
                              '${size.toStringAsFixed(size % 1 == 0 ? 0 : 1)} USDT'
                              '${lev != null ? ' · ${lev.toStringAsFixed(lev % 1 == 0 ? 0 : 1)}x' : ''}',
                              context.palette.textSecondary,
                            ),
                          if (isClose && dur != null) _mini(context, '⏱ ${_dur(dur)}', context.palette.textSecondary),
                          if (recovered) _mini(context, 'caught up after gap', context.palette.warning),
                          if (kind == 'catchup') ...[
                            _mini(context, '${d['checked'] ?? 0} checked', context.palette.textSecondary),
                            if ((_n(d['closed']) ?? 0) > 0) _mini(context, '${d['closed']} closed while away', context.palette.warning),
                          ],
                        ],
                      ),
                      AnimatedSize(
                        duration: AppMotion.base,
                        curve: AppMotion.standard,
                        alignment: Alignment.topCenter,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (expanded) ..._details(context, d, isClose, pnl, color),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  // ---- clean row (same look as Signals) --------------------------------------

  TradeRowData? _rowFromAlert(BuildContext context, Map<String, dynamic> al) {
    final d = al['d'] is Map ? Map<String, dynamic>.from(al['d'] as Map) : null;
    if (d == null || d['symbol'] == null || _n(d['entry']) == null) return null;
    final type = '${al['type'] ?? ''}';
    final isClose = d['exit_tag'] != null;
    if (type != 'open' && !isClose) return null;
    final pnl = _n(d['pnl']);
    final roi = _n(d['roi']);
    final dur = _n(d['duration_s']);
    final entry = _n(d['entry']);
    final sl = _n(d['sl']) ?? _n(d['sl_initial']);
    final tp = d['tp'] is Map ? Map<String, dynamic>.from(d['tp'] as Map) : <String, dynamic>{};
    final ts = _n(al['ts']);
    final status = !isClose ? 'open' : (pnl == null ? 'closed' : (pnl > 0 ? 'won' : (pnl < 0 ? 'lost' : 'closed')));
    return TradeRowData(
      symbol: _shortSym(d['symbol']),
      isLong: d['side'] == 'BUY',
      status: status,
      entry: entry,
      last: isClose ? _n(d['exit']) : sl,
      lastLabel: isClose ? 'Exit' : 'Stop',
      pnl: isClose ? pnl : null,
      openedSec: isClose ? ((ts != null && dur != null) ? ts - dur : null) : ts,
      closedSec: isClose ? ts : null,
      fallbackTime: '${al['time'] ?? '--'}',
      extra: _plainLine(d, isClose, pnl, roi, dur, entry, sl, _n(tp['1'])),
      onTap: () => _openChart(context, d, ts, isClose, pnl, roi, dur),
    );
  }

  /// Tap a row -> candle chart with entry, stop-loss, targets and the exit.
  void _openChart(BuildContext context, Map<String, dynamic> d, double? ts, bool isClose, double? pnl, double? roi, double? dur) {
    final tp = d['tp'] is Map ? Map<String, dynamic>.from(d['tp'] as Map) : <String, dynamic>{};
    final map = <String, dynamic>{
      'symbol': d['symbol'],
      'side': d['side'] == 'BUY' ? 'BUY' : 'SELL',
      'entry': d['entry'],
      'sl': d['sl_initial'] ?? d['sl'],
      'tp1': tp['1'],
      'tp2': tp['2'],
      'tp3': tp['3'],
      'tp4': tp['4'],
      'opened': isClose ? ((ts != null && dur != null) ? ts - dur : null) : ts,
      'state': isClose ? 'closed' : 'open',
    };
    if (isClose) {
      map['closed'] = ts;
      map['exit'] = d['exit'];
      map['pnl'] = pnl;
      map['roi'] = roi;
      map['reason'] = '${d['reason_label'] ?? d['exit_tag']}';
    }
    showTradeChart(context, map);
  }

  /// All trades of this coin on the same trading day, in a bottom sheet.
  void _openHistory(BuildContext context, Map<String, dynamic> d, double? ts) {
    final sym = '${d['symbol']}';
    final day = ts == null ? null : _istYmd(ts);
    final rows = <TradeRowData>[];
    for (final a in context.read<AppProvider>().alerts) {
      if (a is! Map) continue;
      final m = Map<String, dynamic>.from(a);
      final dd = m['d'];
      if (dd is! Map || '${dd['symbol']}' != sym) continue;
      final at = m['ts'];
      if (day != null && !(at is num && _istYmd(at) == day)) continue;
      final r = _rowFromAlert(context, m);
      if (r != null) rows.add(r);
    }
    showCoinHistorySheet(
      context,
      title: day == null ? '${_shortSym(sym)} trades' : '${_shortSym(sym)}  ·  ${_dayTitle(day)}',
      rows: rows,
    );
  }

  // ---- Binance-style trade card ---------------------------------------------

  /// One plain sentence: what happened in this trade (so the numbers below are easy to read).
  String _plainLine(Map<String, dynamic> d, bool isClose, double? pnl, double? roi, double? dur, double? entry, double? sl, double? tp1) {
    final side = d['side'] == 'BUY' ? 'Bought' : 'Sold';
    final sym = _shortSym(d['symbol']);
    if (!isClose) {
      return '$side $sym at ${_price(entry)}. Stop at ${_price(sl)}${tp1 != null ? ', first target ${_price(tp1)}' : ''}. Trade is open.';
    }
    const how = {
      'TP': 'It reached its profit target',
      'SCALP': 'It reached its quick profit %',
      'TSL': 'The trailing stop closed it',
      'SL': 'The stop loss was hit',
      'REV': 'The opposite signal closed it',
      'MAN': 'It was closed by hand',
    };
    final w = how['${d['exit_tag']}'] ?? 'The trade closed';
    final res = pnl == null ? '' : (pnl >= 0 ? ' and made ${_signed(pnl)} USDT' : ' and lost ${_signed(pnl.abs())} USDT');
    return '$side $sym. $w$res${roi != null ? ' (${_signed(roi)}% of margin)' : ''}${dur != null ? ' after ${_dur(dur)}' : ''}.';
  }

  Widget _tradeCard(
    BuildContext context,
    Map<String, dynamic> d, {
    required String type,
    required bool isClose,
    required String pill,
    required Color color,
    required double? pnl,
    required double? roi,
    required double? dur,
  }) {
    final p = context.palette;
    final t = context.type;
    final symbol = '${d['symbol']}';
    final isBuy = d['side'] == 'BUY';
    final sideColor = isBuy ? p.profit : p.loss;
    final entry = _n(d['entry']);
    final exit = _n(d['exit']);
    final sl = _n(d['sl']) ?? _n(d['sl_initial']);
    final slInit = _n(d['sl_initial']) ?? sl;
    final tp = d['tp'] is Map ? Map<String, dynamic>.from(d['tp'] as Map) : <String, dynamic>{};
    final size = _n(d['size_usdt']);
    final lev = _n(d['leverage']);
    final notional = _n(d['notional']) ?? ((size != null && lev != null) ? size * lev : null);
    final tag = 'Perp · Cross${lev != null ? ' ${fmtCompact(lev)}x' : ''}';
    final pc = _pnlColor(context, pnl);
    final opened = d['opened_at'] != null ? '${d['opened_at']}' : '${alert['time'] ?? '--'}';
    final closed = d['closed_at'] != null ? '${d['closed_at']}' : '${alert['time'] ?? '--'}';

    Widget cell(String label, String value, {Color? vc, double fs = 13.5}) => Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: t.label),
              const SizedBox(height: 2),
              Text(
                value,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: t.primary.copyWith(color: vc ?? p.textPrimary, fontWeight: FontWeight.w700, fontSize: fs),
              ),
            ],
          ),
        );

    final List<Widget> grid;
    if (isClose) {
      grid = [
        Row(children: [
          cell('Realized PNL', pnl == null ? '--' : _signed(pnl), vc: pc, fs: 17),
          cell('ROI', roi == null ? '--' : '${_signed(roi)}%', vc: _pnlColor(context, roi)),
          cell('Size (USDT)', notional == null ? '--' : fmtMoney(notional, notional % 1 == 0 ? 0 : 2)),
        ]),
        const SizedBox(height: AppSpacing.s + 2),
        Row(children: [
          cell('Entry', _price(entry)),
          cell('Exit', _price(exit), vc: pc),
          cell('SL', _price(sl), vc: p.loss),
        ]),
      ];
    } else {
      final rr1 = rrTo(entry, slInit, _n(tp['1']));
      grid = [
        Row(children: [
          cell('Entry', _price(entry)),
          cell('SL', _price(sl), vc: p.loss),
          cell('Risk', fmtPctVal(pctDist(entry, slInit)), vc: p.textSecondary),
        ]),
        const SizedBox(height: AppSpacing.s + 2),
        Row(children: [
          cell('TP1', _price(_n(tp['1'])), vc: p.profit),
          cell('R:R (TP1)', fmtRR(rr1), vc: p.textSecondary),
          cell('Size (USDT)', notional == null ? '--' : fmtMoney(notional, notional % 1 == 0 ? 0 : 2)),
        ]),
      ];
    }

    Widget timeRow(String k, String v) => Padding(
          padding: const EdgeInsets.only(top: 2),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(k, style: t.metadata.copyWith(fontSize: 11)),
              Text(v, style: t.metadata.copyWith(fontSize: 11, color: p.textSecondary)),
            ],
          ),
        );

    return GlassCard(
      child: InkWell(
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        onTap: onToggle,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.m, AppSpacing.m - 2, AppSpacing.m, AppSpacing.m - 2),
          child: IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(
                  width: 4,
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: [color, color.withOpacity(0.25)],
                    ),
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // ---- header: [S] SYMBOL  Perp · Cross 10x        PILL v ----
                      Row(
                        children: [
                          OwlSideBadge(isBuy ? 'LONG' : 'SHORT', sideColor),
                          const SizedBox(width: 8),
                          Flexible(
                            child: Text(
                              symbol,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: t.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 15),
                            ),
                          ),
                          const SizedBox(width: 6),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                            decoration: BoxDecoration(color: p.surfaceHigher, borderRadius: BorderRadius.circular(4)),
                            child: Text(tag, style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 10, fontWeight: FontWeight.w600)),
                          ),
                          const Spacer(),
                          _pillBox(context, pill, color),
                          AnimatedRotation(
                            turns: expanded ? 0.5 : 0,
                            duration: AppMotion.base,
                            curve: AppMotion.standard,
                            child: Icon(Icons.expand_more, size: 18, color: p.textMuted),
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      Text(_plainLine(d, isClose, pnl, roi, dur, entry, sl, _n(tp['1'])),
                          style: t.secondary.copyWith(fontSize: 12.5, height: 1.35, color: p.textSecondary)),
                      const SizedBox(height: AppSpacing.m),
                      ...grid,
                      const SizedBox(height: AppSpacing.s),
                      timeRow('Opened', opened),
                      if (isClose) timeRow('Closed${dur != null ? ' (${_dur(dur)})' : ''}', closed),
                      AnimatedSize(
                        duration: AppMotion.base,
                        curve: AppMotion.standard,
                        alignment: Alignment.topCenter,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (expanded) ..._details(context, d, isClose, pnl, color, tradeCard: true),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  // ---- expanded body -------------------------------------------------------

  List<Widget> _details(BuildContext context, Map<String, dynamic> d, bool isClose, double? pnl, Color color, {bool tradeCard = false}) {
    final rows = <Widget>[];
    final tp = d['tp'] is Map ? Map<String, dynamic>.from(d['tp'] as Map) : <String, dynamic>{};
    final hit = (d['tp_hit_levels'] as List?)?.map((e) => '$e').toSet() ?? <String>{};
    final entry = _n(d['entry']);
    final exit = _n(d['exit']);
    final sl = _n(d['sl']);
    final slInit = _n(d['sl_initial']);
    final kind = '${d['kind'] ?? ''}';

    final divider = <Widget>[
      const SizedBox(height: AppSpacing.s),
      Divider(height: 1, color: context.palette.border),
      const SizedBox(height: AppSpacing.s),
    ];

    if (kind == 'catchup') {
      final items = (d['items'] as List?) ?? [];
      for (final it in items.whereType<Map>()) {
        final closed = it['outcome'] == 'closed';
        rows.add(_kv(context, 
          '#${it['id']} ${_shortSym(it['symbol'] ?? '')} ${it['side'] ?? ''}',
          closed ? 'closed: ${it['reason']} @ ${_price(_n(it['exit']))}' : 'still open ✓',
          vc: closed ? context.palette.warning : context.palette.profit,
        ));
      }
      if ((_n(d['gap_s']) ?? 0) > 0) rows.add(_kv(context, 'Data gap', _dur(_n(d['gap_s']))));
      return [...divider, ...rows];
    }
    if (kind == 'feed_up' || kind == 'feed_down') {
      if (d['down_s'] != null) rows.add(_kv(context, 'Feed down for', _dur(_n(d['down_s']))));
      if (d['error'] != null) rows.add(_kv(context, 'Last error', '${d['error']}'));
      return [...divider, ...rows];
    }

    if (!tradeCard) {
      rows.add(_kv(context, 'Entry', _price(entry)));
      if (isClose) rows.add(_kv(context, 'Exit', _price(exit), vc: _pnlColor(context, pnl)));
    }
    if (sl != null && (!tradeCard || d['sl_trailed'] == true)) {
      final trailed = d['sl_trailed'] == true;
      rows.add(_kv(context, 
        trailed ? 'SL (trailed)' : 'SL',
        _price(sl) + (trailed && slInit != null ? '   (was ${_price(slInit)})' : ''),
        vc: context.palette.loss,
      ));
    }
    for (final k in ['1', '2', '3', '4']) {
      if (tp[k] != null) {
        final reached = hit.contains(k);
        rows.add(_kv(context, 'TP$k', '${_price(_n(tp[k]))}${reached ? '   ✓ touched' : ''}',
            vc: reached ? context.palette.profit : context.palette.textSecondary));
      }
    }
    if (d['target_level'] != null) rows.add(_kv(context, 'Target', 'TP${d['target_level']}'));
    if (tradeCard) {
      final rSl = slInit ?? sl;
      final rr1 = rrTo(entry, rSl, _n(tp['1']));
      final rr4 = rrTo(entry, rSl, _n(tp['4']));
      if (rr1 != null || rr4 != null) {
        rows.add(_kv(context, 'R:R planned', 'TP1 ${fmtRR(rr1)}  ·  TP4 ${fmtRR(rr4)}'));
      }
      final risk = pctDist(entry, rSl);
      if (risk != null) rows.add(_kv(context, 'Risk (SL dist)', fmtPctVal(risk)));
      if (isClose && entry != null && exit != null && entry != 0) {
        final dir = d['side'] == 'BUY' ? 1.0 : -1.0;
        final move = (exit - entry) / entry * 100 * dir;
        rows.add(_kv(context, 'Price move', '${_signed(move)}%', vc: _pnlColor(context, move)));
      }
      final size = _n(d['size_usdt']);
      final lev = _n(d['leverage']);
      final notional = _n(d['notional']) ?? ((size != null && lev != null) ? size * lev : null);
      if (size != null && size > 0) {
        rows.add(_kv(context, 'Margin × Lev',
            '${fmtCompact(size)} USDT × ${lev != null ? fmtCompact(lev) : '?'}x${notional != null ? ' = ${fmtMoney(notional)}' : ''}'));
      }
    }
    if (_n(d['peak_roi']) != null || _n(d['worst_roi']) != null) {
      rows.add(_kv(context, 'Peak / worst ROI', '${_signed(_n(d['peak_roi']) ?? 0)}% / ${_signed(_n(d['worst_roi']) ?? 0)}%'));
    }
    final notional = _n(d['notional']);
    if (!tradeCard && notional != null && notional > 0) rows.add(_kv(context, 'Position value', '${notional.toStringAsFixed(2)} USDT'));
    if (d['trigger'] != null) rows.add(_kv(context, 'Trigger', '${d['trigger']}'));
    if (d['sl_type'] != null) rows.add(_kv(context, 'SL basis', '${d['sl_type']}'));
    if (d['skip_reason'] != null) rows.add(_kv(context, 'Why skipped', '${d['skip_reason']}'));
    if (d['signal_no'] != null) rows.add(_kv(context, 'Signal', '#${d['signal_no']}'));
    if (d['trade_id'] != null) rows.add(_kv(context, 'Trade', '#${d['trade_id']}'));
    if (!tradeCard && d['opened_at'] != null) rows.add(_kv(context, 'Opened', '${d['opened_at']}'));
    if (!tradeCard && d['closed_at'] != null) rows.add(_kv(context, 'Closed', '${d['closed_at']}'));
    if (d['note'] != null) {
      rows.add(Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Text(
          'ℹ️ ${d['note']}',
          style: context.type.metadata.copyWith(color: context.palette.warning, fontStyle: FontStyle.italic),
        ),
      ));
    }

    final out = <Widget>[...divider];
    if (entry != null && (sl != null || tp.isNotEmpty)) {
      out.add(SizedBox(
        height: 44,
        width: double.infinity,
        child: CustomPaint(
          painter: _LadderPainter(
            entry: entry,
            exit: exit,
            sl: slInit ?? sl,
            tps: {for (final e in tp.entries) e.key: _n(e.value)},
            hit: hit,
            exitColor: color,
            trackColor: context.palette.border,
            inColor: context.palette.textSecondary,
            ringColor: context.palette.textPrimary,
          ),
        ),
      ));
      out.add(const SizedBox(height: 8));
    }
    out.addAll(rows);

    final symbol = d['symbol'] != null ? '${d['symbol']}' : null;
    if (symbol != null && entry != null) {
      out.add(const SizedBox(height: 8));
      out.add(Align(
        alignment: Alignment.centerLeft,
        child: OutlinedButton.icon(
          onPressed: () => showCandleChartSheet(
            context,
            symbol,
            entry: entry,
            sl: slInit ?? sl,
            tpLevels: {
              for (final e in tp.entries)
                if (int.tryParse(e.key) != null) int.parse(e.key): _n(e.value),
            },
            isLong: d['side'] == 'BUY',
          ),
          icon: Icon(Icons.candlestick_chart, size: 16, color: context.palette.accent),
          label: Text('View chart', style: context.type.secondary.copyWith(color: context.palette.accent, fontSize: 12)),
          style: OutlinedButton.styleFrom(
            side: BorderSide(color: context.palette.accent),
            visualDensity: VisualDensity.compact,
          ),
        ),
      ));
    }
    return out;
  }

  Widget _simple(BuildContext context, String type, String text, String time) {
    Color color;
    if (type == 'tp' || type == 'open' || type == 'target') {
      color = context.palette.accent;
    } else if (type == 'sl' || type == 'loss' || type == 'error') {
      color = context.palette.loss;
    } else if (type == 'reversed' || type == 'skip') {
      color = context.palette.warning;
    } else {
      color = context.palette.accent;
    }
    return GlassCard(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.m - 2),
        child: Row(
          children: [
            Container(width: 4, height: 30, color: color),
            const SizedBox(width: 10),
            Expanded(child: Text(text, style: context.type.primary.copyWith(fontSize: 13))),
            Text(time, style: context.type.metadata),
          ],
        ),
      ),
    );
  }

  Widget _pillBox(BuildContext context, String text, Color color, {bool small = false}) {
    if (!small) return OwlChip(text, color);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
      decoration: BoxDecoration(
        color: color.withOpacity(0.16),
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
        border: Border.all(color: color.withOpacity(0.6)),
      ),
      child: Text(text, style: AppTypography.metadata.copyWith(color: color, fontSize: 10, fontWeight: FontWeight.w800)),
    );
  }

  Widget _mini(BuildContext context, String text, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: context.palette.surfaceHigher,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(text, style: AppTypography.metadata.copyWith(color: color, fontSize: 10.5, fontWeight: FontWeight.w700)),
    );
  }

  Widget _kv(BuildContext context, String k, String v, {Color? vc}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 104, child: Text(k, style: context.type.metadata.copyWith(fontSize: 11.5))),
          Expanded(
            child: Text(v, style: AppTypography.secondaryData.copyWith(color: vc ?? context.palette.textPrimary, fontSize: 11.5, fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
  }
}

/// Horizontal price ladder: SL ... entry ... TP1-4, with the exit marked.
class _LadderPainter extends CustomPainter {
  final double entry;
  final double? exit;
  final double? sl;
  final Map<String, double?> tps;
  final Set<String> hit;
  final Color exitColor;
  final Color trackColor;
  final Color inColor;
  final Color ringColor;

  _LadderPainter({
    required this.entry,
    required this.exit,
    required this.sl,
    required this.tps,
    required this.hit,
    required this.exitColor,
    required this.trackColor,
    required this.inColor,
    required this.ringColor,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final vals = <double>[
      entry,
      if (exit != null) exit!,
      if (sl != null) sl!,
      ...tps.values.whereType<double>(),
    ];
    final lo = vals.reduce(math.min);
    var hi = vals.reduce(math.max);
    if (hi - lo <= 0) hi = lo + 1e-9;
    const padX = 16.0;
    final w = size.width - padX * 2;
    if (w <= 10) return;
    double xOf(double p) => padX + (p - lo) / (hi - lo) * w;
    final yLine = size.height * 0.58;

    canvas.drawLine(
      Offset(padX, yLine),
      Offset(size.width - padX, yLine),
      Paint()
        ..color = trackColor
        ..strokeWidth = 2,
    );

    void tick(double price, String label, Color color) {
      final x = xOf(price);
      canvas.drawLine(
        Offset(x, yLine - 7),
        Offset(x, yLine + 7),
        Paint()
          ..color = color
          ..strokeWidth = 2,
      );
      final tp = TextPainter(
        text: TextSpan(text: label, style: AppTypography.metadata.copyWith(color: color, fontSize: 9, fontWeight: FontWeight.w700)),
        textDirection: TextDirection.ltr,
      )..layout();
      final left = (x - tp.width / 2).clamp(0.0, size.width - tp.width).toDouble();
      tp.paint(canvas, Offset(left, yLine - 21));
    }

    if (sl != null) tick(sl!, 'SL', AppColors.loss);
    tps.forEach((k, v) {
      if (v != null) tick(v, 'TP$k', hit.contains(k) ? AppColors.profit : AppColors.profit.withOpacity(0.55));
    });
    tick(entry, 'IN', inColor);

    final ex = exit;
    if (ex != null) {
      final x = xOf(ex);
      canvas.drawCircle(Offset(x, yLine), 6, Paint()..color = exitColor);
      canvas.drawCircle(
        Offset(x, yLine),
        6,
        Paint()
          ..color = ringColor
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.5,
      );
      final tp = TextPainter(
        text: TextSpan(text: 'OUT', style: AppTypography.metadata.copyWith(color: exitColor, fontSize: 9, fontWeight: FontWeight.w800)),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, Offset((x - tp.width / 2).clamp(0.0, size.width - tp.width).toDouble(), yLine + 10));
    }
  }

  @override
  bool shouldRepaint(covariant _LadderPainter old) => true;
}
