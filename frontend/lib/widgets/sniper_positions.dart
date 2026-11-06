import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../screens/sniper_position_chart.dart';
import '../theme/app_active.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'owl_card.dart';

/// R29b (Part 4): the SNIPER POSITIONS list, same idea as the Current Bot Live list. Used as the "Sniper" tab of Positions and as a pushed page from the Sniper tab.
///   top      ONE Sniper-only total: open count, open P&L (paper USDT), how many are in profit / loss. Never added to the Current Bot, Dual or Brain numbers.
///   open     one card per open Sniper paper trade: coin, side, lane, P&L, entry -> now, SL, TP, how long open. Tap = chart + plan + why (screens/sniper_position_chart.dart).
///   closed   the newest closed Sniper trades with result, exit reason, held time and the mistake tag.
/// Data: GET /api/v2/sniper_trades (the record, read every 20 s) joined with AppProvider.positions (live price + P&L, the same list the Current Bot uses; Sniper trades carry source sniper / sniper_learn).
/// A Sniper position with no record (opened before the trade record existed) is still listed, with a note. Read only: nothing here closes or changes a trade. Dart NOT compiled.
double? _n(Object? v) => v is num ? v.toDouble() : null;
Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(Object? v) => v is List ? v : const [];

class SniperPositions extends StatefulWidget {
  const SniperPositions({super.key});

  @override
  State<SniperPositions> createState() => _SniperPositionsState();
}

class _SniperPositionsState extends State<SniperPositions> {
  Map<String, dynamic>? _rec;
  Map<String, dynamic>? _opp; // Part 17a: GET /api/v2/sniper_opp (one rough STAY / TAKE PROFIT / ROTATE line per open trade)
  Timer? _timer;
  bool _allClosed = false;

  @override
  void initState() {
    super.initState();
    _rec = ScreenCache.get('sniper_trades'); // Part 14: last good record at once, refresh quietly
    _opp = ScreenCache.get('sniper_opp');
    _load();
    _timer = AppActive.every(const Duration(seconds: 20), _load);
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final pr = Provider.of<AppProvider>(context, listen: false);
    final out = await Future.wait<Map<String, dynamic>>([pr.fetchSniperTrades(), pr.fetchSniperOpp()]);
    if (!mounted) return;
    setState(() {
      _rec = ScreenCache.put('sniper_trades', out[0]) ? out[0] : _rec;
      _opp = ScreenCache.put('sniper_opp', out[1]) ? out[1] : _opp;
    });
  }

  /// Part 17a: the OPP row of one open trade (matched by the Sniper client id), or null.
  Map<String, dynamic>? _oppFor(Object? id) {
    if (id == null) return null;
    for (final x in _l(_opp?['rows'])) {
      if (x is Map && x['id'] == id) return _m(x);
    }
    return null;
  }

  Color _oppColor(AppPalette p, String d) => d == 'TAKE_PROFIT' ? p.profit : (d == 'ROTATE' ? p.warning : (d == 'STAY' ? p.textSecondary : p.textMuted));

  /// Open record rows joined with their live position, then any Sniper position that has no record.
  List<Map<String, dynamic>> _rows(List<dynamic> positions) {
    final rows = <Map<String, dynamic>>[];
    final used = <dynamic>{};
    for (final r in _l(_rec?['open'])) {
      final rec = _m(r);
      final pos = sniperLivePos(positions, rec);
      if (pos != null) used.add(pos['id']);
      rows.add({'rec': rec, 'pos': pos});
    }
    for (final x in positions) {
      if (x is! Map || !'${x['source'] ?? ''}'.startsWith('sniper') || used.contains(x['id'])) continue;
      rows.add({
        'rec': <String, dynamic>{'symbol': x['symbol'], 'side': x['action'] == 'BUY' ? 'LONG' : 'SHORT', 'lane': '${x['source']}' == 'sniper_learn' ? 'LEARN' : 'REAL', 'note': 'No record from the open (older trade).'},
        'pos': Map<String, dynamic>.from(x),
      });
    }
    return rows;
  }

  Widget _txt(AppPalette p, String t, {Color? c, double size = 12, bool bold = false}) =>
      Padding(padding: const EdgeInsets.only(top: 3), child: Text(t, style: TextStyle(fontSize: size, color: c ?? p.textSecondary, fontWeight: bold ? FontWeight.w700 : FontWeight.w400)));

  Widget _openCard(BuildContext context, AppPalette p, Map<String, dynamic> row) {
    final rec = _m(row['rec']);
    final pos = row['pos'] is Map ? _m(row['pos']) : null;
    final long = rec['side'] == 'LONG';
    final pnl = _n(pos?['pnl_usdt']), roi = _n(pos?['roi_pct']), ltp = _n(pos?['ltp']);
    final c = pnl == null ? p.textMuted : (pnl >= 0 ? p.profit : p.loss);
    final lv = sniperLevels(rec, pos);
    final t0 = _n(rec['opened_at']) ?? _n(pos?['opened_at_ts']);
    final age = t0 == null ? null : DateTime.now().millisecondsSinceEpoch / 1000 - t0;
    final opp = _oppFor(rec['id']);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.s),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => SniperPositionChart(rec: rec, pos: pos))),
        child: OWLCard(
          edge: c,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: Text('${rec['symbol'] ?? '--'}  ${long ? 'LONG' : 'SHORT'}', style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800, color: p.textPrimary))),
              Text(pnl == null ? '--' : '${fmtSigned(pnl)} USDT', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: c)),
            ]),
            _txt(p, 'Entry ${fmtPrice(lv.entry)} -> Now ${fmtPrice(ltp)}${roi == null ? '' : '   ${fmtSigned(roi, 1)}% ROI'}', c: p.textPrimary),
            _txt(p, 'Stop (loss limit) ${fmtPrice(lv.sl)}  |  Target (profit goal) ${fmtPrice(lv.tp)}'),
            if (pnl != null) _txt(p, 'Right now ${pnl >= 0 ? 'up' : 'down'} ${pnl.abs().toStringAsFixed(2)} USDT. You do not need to do anything: the stop or the target closes it by itself.', size: 11.5, c: p.textSecondary),
            if (sniperVerify(rec, pos).ok == false) _txt(p, sniperVerify(rec, pos).text, size: 11, c: p.loss, bold: true), // Plan E: only a problem is shown on the card, the full check is on the chart page
            Row(children: [
              Expanded(child: _txt(p, '${rec['lane'] ?? 'SNIPER'}  |  open for ${sniperMins(age)}${_n(rec['max_hold_sec']) == null ? '' : ', will be closed after ${sniperMins(rec['max_hold_sec'])} at most'}', size: 11.5, c: p.textMuted)),
              _txt(p, 'Chart >', size: 11.5, c: p.warning, bold: true),
            ]),
            if (opp != null) _txt(p, '${opp['text'] ?? ''}', size: 11, c: _oppColor(p, '${opp['decision']}')),
            if (rec['note'] != null) _txt(p, '${rec['note']}', size: 11, c: p.textMuted),
          ]),
        ),
      ),
    );
  }

  Widget _closedCard(BuildContext context, AppPalette p, Map<String, dynamic> t) {
    final pnl = _n(t['pnl_usdt']);
    final c = pnl == null ? p.textMuted : (pnl >= 0 ? p.profit : p.loss);
    final tag = '${t['tag'] ?? ''}';
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.s),
      child: GestureDetector(
       behavior: HitTestBehavior.opaque,
       // Plan E: a closed trade opens its chart too (entry / SL / TP lines, result, exit reason, lesson).
       onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => SniperPositionChart(rec: t, closed: true))),
       child: OWLCard(
        edge: c,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('${t['symbol'] ?? '--'}  ${t['side'] ?? ''}  ${t['lane'] ?? ''}', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary))),
            Text(pnl == null ? '--' : '${fmtSigned(pnl)} USDT', style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800, color: c)),
          ]),
          _txt(p, 'Closed by ${(t['exit_reason'] ?? '').toString().isEmpty ? '--' : t['exit_reason']}  |  held ${sniperMins(t['held_sec'])}${tag.isEmpty ? '' : '  |  $tag'}', size: 11.5),
          _txt(p, 'Chart >', size: 11.5, c: p.warning, bold: true),
        ]),
       ),
      ),
    );
  }

  Widget _head(AppPalette p, List<Map<String, dynamic>> rows) {
    var total = 0.0, up = 0, down = 0;
    for (final r in rows) {
      final v = _n(r['pos'] is Map ? (r['pos'] as Map)['pnl_usdt'] : null);
      if (v == null) continue;
      total += v;
      if (v >= 0) { up++; } else { down++; }
    }
    final c = total == 0 ? p.textPrimary : (total > 0 ? p.profit : p.loss);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('SNIPER OPEN TRADES  ${rows.length}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textMuted)),
        const SizedBox(height: 4),
        Text('${fmtSigned(total)} USDT', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, color: c)),
        _txt(p, '$up in profit  |  $down in loss  |  paper money, Sniper only (never added to the Current Bot, Dual or Brain)', size: 11.5),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final prov = Provider.of<AppProvider>(context); // listens: live price and P&L
    final p = context.palette;
    final rows = _rows(prov.positions);
    final closed = _l(_rec?['closed']);
    final shown = _allClosed ? closed : closed.take(8).toList();
    final oldBackend = _rec != null && _rec!['open'] == null;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.screenPad),
        children: [
          _head(p, rows),
          const SizedBox(height: AppSpacing.s),
          if (_rec == null && rows.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator())),
          if (oldBackend) OWLCard(edge: p.warning, child: Text('${_rec!['text'] ?? 'The trade record is not available from this backend yet. Install the newest backend zip, restart it, then pull down.'}', style: TextStyle(fontSize: 12.5, color: p.textPrimary))),
          if (_rec != null && !oldBackend && rows.isEmpty)
            OWLCard(child: Text('No Sniper trade is open right now. The Sniper opens paper trades by itself when a signal passes its checks (see GATES on the Sniper tab).', style: TextStyle(fontSize: 12.5, color: p.textSecondary))),
          for (final r in rows) _openCard(context, p, r),
          if (shown.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.m),
            Text('CLOSED  (newest first)', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textMuted)),
            const SizedBox(height: AppSpacing.s),
            for (final t in shown) _closedCard(context, p, _m(t)),
            if (closed.length > 8)
              GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: () => setState(() => _allClosed = !_allClosed),
                child: Padding(padding: const EdgeInsets.symmetric(vertical: 10), child: Center(child: Text(_allClosed ? 'Show fewer' : 'Show all ${closed.length}', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.warning)))),
              ),
          ],
        ],
      ),
    );
  }
}
