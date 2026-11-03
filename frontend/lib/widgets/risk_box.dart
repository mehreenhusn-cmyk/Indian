import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'load_state.dart';
import 'owl_card.dart';

/// Part 12 (FILE 23): the RISK BOX card on a signal. Read only: it never opens, closes or changes anything.
/// It asks GET /api/v2/sniper_riskbox (Part 11) for ONE coin and shows what happened in SIMILAR past trades:
/// win chance, expected result in R and USDT, how long a trade usually takes, and the worst case.
/// Below 30 similar trades the backend says NOT_ENOUGH_DATA: then this card shows NO number at all (no fake number).
/// Every number comes from the backend; nothing is worked out here. Paper only. LoadSpinner (Part 1) while it waits.
/// Part 50 (FILE 59): under the box, 4 extra plain lines from the backend (d['extras']): Edge (valid / weak / expired), SCALP / SWING, Stay or rotate (the rule), Session. They are shown
/// in the NOT ENOUGH DATA card too (they say NOT ENOUGH DATA themselves), each with a small tag; a red edge or a kill rule line is shown in red. Older backends send no extras: then nothing is added.
/// Use: RiskBox(symbol: 'BTCUSDT', tf: '5m', side: 'LONG', size: 10, lev: 1). side empty = the Sniper's own signal.
/// Dart NOT compiled (the APK build is the proof).

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
double _d(Object? v) => v is num ? v.toDouble() : 0.0;
String _r(Object? v) => '${_d(v) >= 0 ? '+' : ''}${_d(v).toStringAsFixed(2)} R';
String _usdt(Object? v) => '${_d(v) >= 0 ? '+' : ''}${_d(v).toStringAsFixed(2)} USDT';

/// Owner rule: more than 60 minutes is shown as hours + minutes ("2 h 10 min"), never "220 min".
String riskBoxDuration(Object? secs) {
  final s = _d(secs);
  if (s <= 0) return '-';
  if (s < 60) return '${s.round()} s';
  final min = (s / 60).round();
  if (min <= 60) return '$min min';
  final h = min ~/ 60, m = min % 60;
  return m == 0 ? '$h h' : '$h h $m min';
}

class RiskBox extends StatefulWidget {
  final String symbol;
  final String tf;
  final String side;
  final double size;
  final double lev;
  const RiskBox({super.key, required this.symbol, this.tf = '5m', this.side = '', this.size = 10, this.lev = 1});

  @override
  State<RiskBox> createState() => _RiskBoxState();
}

class _RiskBoxState extends State<RiskBox> {
  Map<String, dynamic>? _data;
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(RiskBox old) {
    super.didUpdateWidget(old);
    if (old.symbol != widget.symbol || old.tf != widget.tf || old.side != widget.side || old.size != widget.size || old.lev != widget.lev) _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final d = await context.read<AppProvider>().fetchSniperRiskBox(widget.symbol, tf: widget.tf, side: widget.side, size: widget.size, lev: widget.lev);
    if (!mounted) return;
    setState(() {
      _data = d;
      _busy = false;
    });
  }

  Widget _title(AppPalette p, {Widget? tag}) => Row(children: [
        Expanded(child: Text('Risk Box', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary))),
        if (tag != null) tag,
      ]);

  Widget _chip(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
        child: Text(text, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: c)),
      );

  Widget _line(AppPalette p, String t, {Color? c, double size = 12}) =>
      Padding(padding: const EdgeInsets.only(top: 4), child: Text(t, style: TextStyle(fontSize: size, color: c ?? p.textSecondary)));

  Widget _cell(AppPalette p, String label, String value, {Color? c}) => Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: TextStyle(fontSize: 11, color: p.textMuted)),
          const SizedBox(height: 2),
          Text(value, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: c ?? p.textPrimary)),
        ]),
      );

  Widget _note(AppPalette p, String text, {Color? edge, String? chip}) => OWLCard(
        edge: edge,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, tag: chip == null ? null : _chip(chip, edge ?? p.textMuted)),
          _line(p, text, c: p.textPrimary),
        ]),
      );

  /// Part 50 + 51: the 5 extra lines under the box (the 5th is MTF CONFLUENCE, red when the higher interval is AGAINST). Empty when the backend sent none (older backend).
  Widget _extras(AppPalette p, Map<String, dynamic> d) {
    final x = _m(d['extras']);
    if (x.isEmpty) return const SizedBox.shrink();
    final edge = _m(x['edge']);
    final bad = '${edge['state']}' == 'EXPIRED' || '${edge['kill']}' == 'TRIPPED';
    final warn = '${edge['state']}' == 'WEAK' || '${edge['kill']}' == 'WATCH';
    final rows = <List<String>>[
      ['EDGE', '${edge['line'] ?? ''}'],
      ['SCALP / SWING', '${_m(x['scalp'])['line'] ?? ''}'],
      ['STAY OR ROTATE', '${_m(x['stay'])['line'] ?? ''}'],
      ['SESSION', '${_m(x['session'])['line'] ?? ''}'],
      ['MTF CONFLUENCE', '${_m(x['confluence'])['line'] ?? ''}'],
    ];
    final against = '${_m(x['confluence'])['state']}' == 'AGAINST';
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Divider(height: 1, color: p.border),
        for (final r in rows)
          if (r[1].isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(r[0], style: TextStyle(fontSize: 10, fontWeight: FontWeight.w800, letterSpacing: 0.5, color: p.textMuted)),
                Text(r[1], style: TextStyle(fontSize: 12, color: r[0] == 'EDGE' && bad ? p.loss : (r[0] == 'EDGE' && warn ? p.warning : (r[0] == 'MTF CONFLUENCE' && against ? p.loss : p.textSecondary)))),
              ]),
            ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    if (_busy || d == null) return OWLCard(child: Column(children: [_title(p), LoadSpinner(onRetry: _load)]));
    final st = '${d['state']}';
    if (st == 'off') return _note(p, 'The V2 data API or the Sniper is switched off, so the Risk Box cannot be read.', edge: p.textMuted, chip: 'OFF');
    if (st == 'old') return _note(p, 'This backend has no Risk Box route yet. Install the newest backend zip and restart the backend.', edge: p.warning, chip: 'OLD BACKEND');
    if (st == 'busy') return _note(p, '${d['text'] ?? 'The Risk Box is reading the saved trades. Open this page again in a minute.'}', edge: p.warning, chip: 'BUSY');
    if (st == 'error') return _note(p, '${d['text'] ?? 'The Risk Box could not be read.'} Open the page again to retry.', edge: p.loss, chip: 'ERROR');
    if (st == 'NO_SIGNAL') return _note(p, '${d['text'] ?? 'No signal to rate.'}', chip: 'NO SIGNAL');
    final n = _d(d['n']).toInt();
    final minN = _d(d['min_n']) > 0 ? _d(d['min_n']).toInt() : 30;
    if (st == 'NOT_ENOUGH_DATA') {
      return OWLCard(
        edge: p.warning,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, tag: _chip('NOT ENOUGH DATA', p.warning)),
          const SizedBox(height: 8),
          Text('$n of $minN similar past trades', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: LinearProgressIndicator(value: (n / minN).clamp(0.0, 1.0), minHeight: 8, backgroundColor: p.border, color: p.accent),
          ),
          _line(p, 'No win chance or profit number is shown until $minN similar trades exist. A guess would be a fake number.', size: 11.5),
          for (final t in (d['lines'] is List ? (d['lines'] as List).skip(1) : const <Object?>[])) _line(p, '$t', size: 11.5, c: p.textMuted),
          _extras(p, d),
        ]),
      );
    }
    if (st != 'OK') return _note(p, '${d['text'] ?? 'Unknown Risk Box state.'}', edge: p.warning, chip: st);
    final exp = _d(d['exp_r']);
    final c = exp > 0 ? p.profit : (exp < 0 ? p.loss : p.textSecondary);
    final hasUsdt = d['exp_usdt'] != null;
    final src = _m(d['by_source']).entries.map((e) => '${e.key} ${_d(e.value).toInt()}').join(', ');
    return OWLCard(
      edge: c,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, tag: _chip('$n similar trades', c)),
        const SizedBox(height: 10),
        Row(children: [
          _cell(p, 'Win chance', '${_d(d['win_pct']).toStringAsFixed(0)}%'),
          _cell(p, 'Could be as low as', '${_d(d['win_low95_pct']).toStringAsFixed(0)}%', c: p.textSecondary),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          _cell(p, 'Expected (after fees)', _r(d['exp_r']), c: c),
          _cell(p, 'Low end', _r(d['exp_r_low']), c: p.textSecondary),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          _cell(p, 'Usual time', riskBoxDuration(d['median_secs'])),
          _cell(p, 'Slow trades (75%)', riskBoxDuration(d['p75_secs']), c: p.textSecondary),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          _cell(p, 'Worst single trade', _r(d['worst_r']), c: p.loss),
          _cell(p, 'Deepest dip (90%)', _r(d['mae_p90_r']), c: p.textSecondary),
        ]),
        if (hasUsdt) _line(p, '1R = ${_d(d['risk_usdt']).toStringAsFixed(4)} USDT (stop ${_d(d['stop_pct']).toStringAsFixed(2)}%): expected ${_usdt(d['exp_usdt'])}, worst ${_usdt(d['worst_usdt'])}.', c: p.textPrimary, size: 11.5),
        if (src.isNotEmpty) _line(p, 'Sources (never added together): $src.', size: 11, c: p.textMuted),
        _extras(p, d),
        _line(p, 'Past trades only, paper only. It is a guide, not a promise.', size: 11, c: p.textMuted),
      ]),
    );
  }
}
