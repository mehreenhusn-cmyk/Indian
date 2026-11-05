import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import '../widgets/candle_chart.dart';
import '../widgets/owl_card.dart';

/// R29b (Part 4): ONE open Sniper paper trade with a chart, like the Current Bot position card.
/// Opened by tapping a row of widgets/sniper_positions.dart. Data = the trade RECORD (GET /api/v2/sniper_trades, passed in as [rec]) + the LIVE position (AppProvider.positions, same list the Current Bot uses),
/// so price and P&L stay live. Chart = the same CandleChart (candles, EMA 30/50, ENTRY / SL / TP lines from the entry candle); tap it for the full TradingView-style sheet.
/// Read only: no close button, no move-SL button (the Sniper manages its own paper trades). A missing number prints "--". Dart NOT compiled.
double? _n(Object? v) => v is num ? v.toDouble() : null;

/// The live paper position that belongs to a Sniper record: by paper trade id first, else (record has no trade id) the first Sniper position of the same coin. null = not found.
Map<String, dynamic>? sniperLivePos(List<dynamic> positions, Map<String, dynamic> rec) {
  final tid = rec['trade_id'];
  Map<String, dynamic>? bySym;
  for (final x in positions) {
    if (x is! Map) continue;
    if (tid != null && x['id'] == tid) return Map<String, dynamic>.from(x);
    if (bySym == null && '${x['source'] ?? ''}'.startsWith('sniper') && x['symbol'] == rec['symbol']) bySym = Map<String, dynamic>.from(x);
  }
  return tid == null ? bySym : null;
}

/// Entry / stop / target: the record first (what the Sniper planned), else what the live position holds.
class SniperLv {
  final double? entry, sl, tp;
  const SniperLv(this.entry, this.sl, this.tp);
}

SniperLv sniperLevels(Map<String, dynamic> rec, Map<String, dynamic>? pos) => SniperLv(
      _n(rec['entry']) ?? _n(pos?['entry_price']),
      _n(rec['stop_loss']) ?? _n(pos?['stop_loss']) ?? _n(pos?['sl']),
      _n(rec['take_profit']) ?? _n(pos?['effective_tp1']) ?? _n(pos?['tp1']),
    );

String sniperMins(Object? s) => _n(s) == null ? '--' : (_n(s)! >= 3600 ? '${(_n(s)! / 3600).toStringAsFixed(1)} h' : '${(_n(s)! / 60).round()} min');

/// Plan E: the result of an SL / TP check. [ok] true = fine, false = something to look at, null = cannot tell (a number is missing).
class SniperCheck {
  final bool? ok;
  final String text;
  const SniperCheck(this.ok, this.text);
}

/// Plan E (SL / TP verify): 1) the record's SL must sit on the losing side of the entry and the TP on the winning side (LONG: SL below, TP above; SHORT: the other way),
/// 2) when the live position is known, the SL and TP it really holds must be the same as the plan (0.05% tolerance). A difference is shown as "differs", not as an error:
/// the position may have been moved on purpose. A missing number gives "--", never a guess. Read only.
SniperCheck sniperVerify(Map<String, dynamic> rec, Map<String, dynamic>? pos) {
  final lv = sniperLevels(rec, null);
  final e = lv.entry, sl = lv.sl, tp = lv.tp;
  final long = rec['side'] == 'LONG';
  if (e == null || sl == null || tp == null) return const SniperCheck(null, 'SL / TP check: -- (the record has no full entry, SL and TP)');
  if (!(long ? sl < e : sl > e)) return SniperCheck(false, 'SL / TP check: the SL ${fmtPrice(sl)} is on the wrong side of the entry ${fmtPrice(e)}');
  if (!(long ? tp > e : tp < e)) return SniperCheck(false, 'SL / TP check: the TP ${fmtPrice(tp)} is on the wrong side of the entry ${fmtPrice(e)}');
  if (pos == null) return const SniperCheck(true, 'SL / TP check: sides are right (no live position to compare with)');
  final ps = _n(pos['effective_sl']) ?? _n(pos['stop_loss']) ?? _n(pos['signal_stop_loss']);
  final pt = _n(pos['effective_tp1']) ?? _n(pos['signal_tp1']) ?? _n(pos['tp1']);
  if (ps == null || pt == null) return const SniperCheck(null, 'SL / TP check: -- (the live position does not report its SL / TP)');
  bool near(double a, double b) => (a - b).abs() <= a.abs() * 0.0005;
  if (near(sl, ps) && near(tp, pt)) return const SniperCheck(true, 'SL / TP check: the live position holds the same SL and TP as the plan');
  return SniperCheck(false, 'SL / TP differs: plan SL ${fmtPrice(sl)} / TP ${fmtPrice(tp)}, live position SL ${fmtPrice(ps)} / TP ${fmtPrice(pt)}');
}

class SniperPositionChart extends StatefulWidget {
  final Map<String, dynamic> rec;
  final Map<String, dynamic>? pos;
  /// Plan E: true = a CLOSED Sniper trade (the record from /api/v2/sniper_trades closed list): result, exit reason and lesson instead of live price.
  final bool closed;
  const SniperPositionChart({super.key, required this.rec, this.pos, this.closed = false});

  @override
  State<SniperPositionChart> createState() => _SniperPositionChartState();
}

class _SniperPositionChartState extends State<SniperPositionChart> {
  List<dynamic> _candles = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prov = Provider.of<AppProvider>(context, listen: false);
    setState(() { _loading = true; _error = null; });
    final c = await prov.fetchCandles('${widget.rec['symbol']}', limit: 300);
    if (!mounted) return;
    setState(() {
      _candles = c;
      _loading = false;
      _error = c.isEmpty ? (prov.lastCandleError ?? 'No candles came back.') : null;
    });
  }

  Widget _line(AppPalette p, String t, {Color? c, double size = 12.5, bool bold = false}) =>
      Padding(padding: const EdgeInsets.only(top: 4), child: Text(t, style: TextStyle(fontSize: size, color: c ?? p.textSecondary, fontWeight: bold ? FontWeight.w700 : FontWeight.w400)));

  Widget _chip(String t, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(6)),
        child: Text(t, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: c)),
      );

  @override
  Widget build(BuildContext context) {
    final prov = Provider.of<AppProvider>(context); // listens: price and P&L move
    final p = context.palette;
    final rec = widget.rec;
    final closed = widget.closed;
    final pos = closed ? null : (sniperLivePos(prov.positions, rec) ?? widget.pos);
    final symbol = '${rec['symbol'] ?? '--'}';
    final isLong = rec['side'] == 'LONG';
    final lv = sniperLevels(rec, pos);
    final pnl = closed ? _n(rec['pnl_usdt']) : _n(pos?['pnl_usdt']), roi = closed ? _n(rec['roi_pct']) : _n(pos?['roi_pct']), ltp = _n(pos?['ltp']);
    final c = pnl == null || pnl == 0 ? p.textPrimary : (pnl > 0 ? p.profit : p.loss);
    final closedAt = _n(rec['closed_at']);
    final opened = _n(rec['opened_at']) ?? _n(pos?['opened_at_ts']) ?? ((closed && closedAt != null && _n(rec['held_sec']) != null) ? closedAt - _n(rec['held_sec'])! : null);
    final int? entryMs = opened == null ? null : (opened * 1000).round();
    final age = closed ? _n(rec['held_sec']) : (opened == null ? null : DateTime.now().millisecondsSinceEpoch / 1000 - opened);
    final chk = sniperVerify(rec, pos);
    final chkColor = chk.ok == null ? p.textMuted : (chk.ok! ? p.profit : p.loss);
    final tpLevels = <int, double?>{1: lv.tp};
    final basis = (rec['basis'] is List ? rec['basis'] as List : const []).take(5).map((e) => '$e').toList();
    String away(double? target) => (target == null || ltp == null || ltp == 0) ? '--' : '${((target - ltp).abs() / ltp * 100).toStringAsFixed(2)}%';

    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(
        backgroundColor: p.bg,
        elevation: 0,
        title: Row(children: [
          Flexible(child: Text(symbol, overflow: TextOverflow.ellipsis)),
          const SizedBox(width: 8),
          _chip(isLong ? 'LONG' : 'SHORT', isLong ? p.profit : p.loss),
          const SizedBox(width: 6),
          _chip('${rec['lane'] ?? 'SNIPER'}', p.warning),
          if (closed) ...[const SizedBox(width: 6), _chip('CLOSED', p.textMuted)],
        ]),
        actions: [IconButton(onPressed: _loading ? null : _load, icon: const Icon(Icons.refresh_rounded))],
      ),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.screenPad),
        children: [
          Text(pnl == null ? '--' : '${fmtSigned(pnl)} USDT', style: TextStyle(fontSize: 30, fontWeight: FontWeight.w800, color: c)),
          if (closed)
            _line(p, '${roi == null ? '--' : fmtSigned(roi, 1)}% ROI  |  closed by ${(rec['exit_reason'] ?? '').toString().isEmpty ? '--' : rec['exit_reason']}  |  held ${sniperMins(rec['held_sec'])}', c: c)
          else
            _line(p, '${roi == null ? '--' : fmtSigned(roi, 1)}% ROI  |  ${fmtPrice(lv.entry)} -> ${fmtPrice(ltp)}', c: c),
          if (closed) _line(p, 'The chart shows the newest candles. A trade older than that is outside it; the ENTRY, SL and TP lines are exact either way.', c: p.textMuted, size: 11),
          if (!closed && pos == null) _line(p, 'This trade is not in the live positions list right now, so price and P&L show "--".', c: p.textMuted, size: 11.5),
          const SizedBox(height: AppSpacing.m),
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => showCandleChartSheet(context, symbol, entry: lv.entry, sl: lv.sl, tpLevels: tpLevels, isLong: isLong, entryTsMs: entryMs, title: '$symbol  Sniper'),
            child: SizedBox(
              height: 260,
              width: double.infinity,
              child: _loading
                  ? const Center(child: CircularProgressIndicator())
                  : CandleChart(candles: _candles, entry: lv.entry, sl: lv.sl, tpLevels: tpLevels, entryTsMs: entryMs, showEma: true, visibleCount: 90, errorText: _error),
            ),
          ),
          _line(p, 'Tap the chart for the full chart (zoom, TSI, Z-score).', size: 11, c: p.textMuted),
          const SizedBox(height: AppSpacing.m),
          OWLCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('THE PLAN', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textMuted)),
              _line(p, 'Entry ${fmtPrice(lv.entry)}  |  TP ${fmtPrice(lv.tp)} (${away(lv.tp)} away)  |  SL ${fmtPrice(lv.sl)} (${away(lv.sl)} away)', c: p.textPrimary),
              if (_n(rec['expected_usdt']) != null)
                _line(p, 'Expected ${fmtSigned(_n(rec['expected_usdt'])!)} USDT at the target, risk -${(_n(rec['risk_usdt']) ?? 0).toStringAsFixed(2)} USDT (after fees)  |  ${rec['rr'] ?? '--'}R'),
              _line(p, '${closed ? 'Held' : 'Open'} ${sniperMins(age)}${_n(rec['max_hold_sec']) == null ? '' : ' of up to ${sniperMins(rec['max_hold_sec'])}'}${_n(rec['typical_hold_sec']) == null ? '' : '  |  typical ${sniperMins(rec['typical_hold_sec'])}'}'),
              _line(p, chk.text, c: chkColor, size: 11.5, bold: chk.ok == false),
              if (closed && _n(rec['vs_expected']) != null) _line(p, 'Result vs the expected ${fmtSigned(_n(rec['expected_usdt']) ?? 0)} USDT: ${fmtSigned(_n(rec['vs_expected'])!)} USDT'),
              if (closed && (rec['lesson'] ?? '').toString().isNotEmpty) _line(p, '${rec['tag'] ?? ''}: ${rec['lesson']}', size: 11.5),
            ]),
          ),
          const SizedBox(height: AppSpacing.s),
          OWLCard(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('WHY THE SNIPER TOOK IT', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textMuted)),
              _line(p, '${(rec['reason'] ?? '').toString().isNotEmpty ? rec['reason'] : (rec['signal'] ?? 'No record from the open (older trade).')}', c: p.textPrimary),
              if (basis.isNotEmpty) _line(p, basis.join('\n')),
              if (rec['regime'] != null) _line(p, 'Market state: ${rec['regime']}', size: 11.5),
            ]),
          ),
        ],
      ),
    );
  }
}
