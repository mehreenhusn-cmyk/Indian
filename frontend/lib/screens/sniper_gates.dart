import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// R26b (Sniper tab): the GATES CHECKLIST and the MISTAKES journal. Data: GET /api/v2/sniper_gates (read only, paper only), loaded by sniper_screen.dart.
/// SniperGates = ONE reason line, two lane chips (EXPLORE lane = the paper lane that learns, REAL lane = the locked 85% gate), 8 gates PASS / FAIL / WAIT with a plain sentence.
/// SniperMistakes = the combos that rest after 3 losses in a row, the mistake counts and the newest closed trades with ONE lesson sentence each. Every word comes from the backend; nothing is made up here. Dart NOT compiled (the APK build is the proof).
Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List _l(Object? v) => v is List ? v : const [];
Color _c(AppPalette p, Object? s) => s == 'PASS' || s == 'OPEN' ? p.profit : (s == 'FAIL' || s == 'BLOCKED' ? p.loss : (s == 'OFF' ? p.textMuted : p.warning));

Widget _chip(String t, Color c) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
      decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
      child: Text(t, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: c)),
    );

Widget _msg(AppPalette p, Map<String, dynamic>? g, String what) => OWLCard(
      child: Text(g == null ? 'Loading the $what...' : 'The $what is not available from this backend yet. Install the newest backend zip, restart it, then pull down.', style: TextStyle(fontSize: 12, color: p.textSecondary)),
    );

class SniperGates extends StatelessWidget {
  final Map<String, dynamic>? g;
  const SniperGates({super.key, required this.g});

  Widget _lane(AppPalette p, String name, Map<String, dynamic> x) => Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 92, child: Align(alignment: Alignment.centerLeft, child: _chip('$name: ${x['state'] ?? '?'}', _c(p, x['state'])))),
          const SizedBox(width: 8),
          Expanded(child: Text('${x['text'] ?? ''}', style: TextStyle(fontSize: 11.5, color: p.textMuted))),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (g == null || g!['gates'] == null || _l(g!['gates']).isEmpty) return _msg(p, g, 'gates checklist');
    final x = g!;
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${x['reason'] ?? ''}', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        _lane(p, 'EXPLORE', _m(x['explore'])),
        _lane(p, 'REAL', _m(x['real'])),
        const SizedBox(height: 8),
        for (final e in _l(x['gates']))
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(width: 44, child: Text('${_m(e)['state']}', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: _c(p, _m(e)['state'])))),
              Expanded(
                child: Text.rich(TextSpan(children: [
                  TextSpan(text: '${_m(e)['name']}${_m(e)['lane'] == 'REAL' ? ' (REAL only)' : ''}: ', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textPrimary)),
                  TextSpan(text: '${_m(e)['text']}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
                ])),
              ),
            ]),
          ),
      ]),
    );
  }
}

class SniperMistakes extends StatelessWidget {
  final Map<String, dynamic>? g;
  const SniperMistakes({super.key, required this.g});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final ms = _m(g?['mistakes']);
    if (g == null || ms.isEmpty) return _msg(p, g, 'mistakes journal');
    final jr = _l(ms['journal']);
    final bl = _l(ms['blocked']);
    final n = (ms['trades'] is num) ? (ms['trades'] as num).toInt() : 0;
    if (n == 0) {
      return OWLCard(child: Text('No closed Sniper trade yet, so there is nothing to learn from. Every closed trade will get a tag and one lesson here.', style: TextStyle(fontSize: 12, color: p.textSecondary)));
    }
    final cnt = _m(ms['counts']).entries.where((e) => e.key != 'GOOD' && e.key != 'UNKNOWN' && e.value is num && e.value > 0).map((e) => '${e.value} ${e.key.toString().toLowerCase().replaceAll('_', ' ')}').join(', ');
    return OWLCard(
      edge: bl.isEmpty ? null : p.warning,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('$n closed trades tagged. ${cnt.isEmpty ? 'No mistake tag yet.' : 'Mistakes: $cnt.'}', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textPrimary)),
        Text('${ms['rule'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textMuted)),
        if (bl.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('RESTING NOW (not repeated)', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: p.warning)),
          for (final b in bl) Padding(padding: const EdgeInsets.only(top: 3), child: Text('${_m(b)['text']}', style: TextStyle(fontSize: 12, color: p.textPrimary))),
        ],
        const SizedBox(height: 8),
        Text('JOURNAL (newest first)', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: p.textMuted)),
        for (final j in jr.take(8))
          Padding(
            padding: const EdgeInsets.only(top: 5),
            child: Text.rich(TextSpan(children: [
              TextSpan(text: '${_m(j)['symbol']} ${_m(j)['side']}  ${((_m(j)['pnl'] ?? 0) as num) >= 0 ? '+' : ''}${((_m(j)['pnl'] ?? 0) as num).toStringAsFixed(2)}  ', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: (((_m(j)['pnl'] ?? 0) as num) >= 0) ? p.profit : p.loss)),
              TextSpan(text: '${_m(j)['text']}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
            ])),
          ),
      ]),
    );
  }
}
