import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// A/B research scoreboard. The live bot is never touched. Five lines are scored on the SAME signals:
///   A bot akela | B + TSI | C + Z/SD | D + TSI and Z/SD together | E AI khud dhundha (sab facts)
/// Two views: LIVE TEST (rules frozen at test start, only newer signals count) and HISTORY CHECK
/// (rules learned on older 60%, scored on newer 40%). Below: the Price-vs-Z x TSI relationship table.
/// All numbers come from the backend (ai_ab_board.py); this widget only draws them. ROI is after fee.
class AiAbCard extends StatefulWidget {
  const AiAbCard({super.key});

  @override
  State<AiAbCard> createState() => _AiAbCardState();
}

class _AiAbCardState extends State<AiAbCard> {
  Map<String, dynamic>? _d;
  bool _failed = false;
  bool _busy = false;      // one request at a time (first load can take 20-40 s)
  String _tf = '';
  String _rel = 'pz3';
  final Set<String> _open = {};
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 60), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_busy) return;
    _busy = true;
    final r = await context.read<AppProvider>().fetchAiAbBoard(tf: _tf);
    _busy = false;
    if (!mounted) return;
    setState(() {
      if (r != null && r['building'] != true) {
        _d = r;
        _failed = false;
        if (_tf.isEmpty) _tf = (r['tf'] ?? '3m').toString();
      } else if (_d == null) {
        _failed = true;
      }
    });
  }

  Future<void> _reset() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Test dobara shuru karein?'),
        content: const Text('Live test aaj se naya shuru hoga aur AI rules purane saare signals se dobara seekhenge. '
            'Bot ya trades pe koi asar nahi padta.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Nahi')),
          TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('Haan, restart')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final r = await context.read<AppProvider>().resetAiAbBoard();
    if (!mounted) return;
    if (r != null) setState(() => _d = r);
  }

  // ----------------------------------------------------------- helpers
  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _l(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
  static String _sg(double v, {int d = 1}) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}%';

  Color _vColor(AppPalette p, String code) {
    switch (code) {
      case 'BETTER':
        return p.profit;
      case 'MAYBE':
        return p.warning;
      case 'WORSE':
        return p.loss;
    }
    return p.textMuted;
  }

  Widget _box(AppPalette p, {required Widget child, Color? border}) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: p.surfaceElevated,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
          border: Border.all(color: (border ?? p.border).withOpacity(0.7), width: 0.8),
        ),
        child: child,
      );

  Widget _chip(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
        decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(6)),
        child: Text(text, style: TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: c)),
      );

  Widget _stat(BuildContext context, String l, String v, {Color? color}) => Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(v, style: context.type.primary.copyWith(fontSize: 15, fontWeight: FontWeight.w800, color: color)),
          Text(l, style: context.type.metadata),
        ]),
      );

  // ----------------------------------------------------------- build
  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _d;
    return ListView(
      padding: const EdgeInsets.fromLTRB(AppSpacing.m, AppSpacing.s, AppSpacing.m, 96),
      children: [
        if (d == null || d['error'] != null)
          Padding(
            padding: const EdgeInsets.only(top: 40),
            child: Column(children: [
              Text(
                  d != null
                      ? 'Backend me error aaya:\n${d['error']}'
                      : (_failed
                          ? 'A/B data nahi mila.\n${context.read<AppProvider>().aiLastError ?? ''}'
                          : 'Load ho raha hai...\npehli baar 20-40 second lag sakte hain, ruk ja.'),
                  textAlign: TextAlign.center,
                  style: context.type.secondary.copyWith(color: p.textMuted)),
              if (d != null || _failed) ...[
                const SizedBox(height: 12),
                OutlinedButton(
                  onPressed: () {
                    setState(() {
                      _d = null;
                      _failed = false;
                    });
                    _load();
                  },
                  child: const Text('Retry'),
                ),
              ],
            ]),
          )
        else ...[
          _head(context, p, d),
          const SizedBox(height: 10),
          _section(context, p, 'fwd', 'LIVE TEST', _m(d['forward']),
              sub: 'rules test shuru hote hi freeze hue - sirf uske baad ke signals ginte hain'),
          const SizedBox(height: 10),
          _section(context, p, 'his', 'HISTORY CHECK', _m(d['history']),
              sub: 'purane 60% se seekha, naye 40% pe jaancha (jo AI ne dekha hi nahi)'),
          const SizedBox(height: 10),
          _relation(context, p, _m(d['relation'])),
          const SizedBox(height: 10),
          _box(p, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final c in (d['caveats'] is List ? (d['caveats'] as List) : const []))
              Padding(padding: const EdgeInsets.only(bottom: 4), child: Text('- $c', style: context.type.metadata)),
          ])),
        ],
      ],
    );
  }

  Widget _head(BuildContext context, AppPalette p, Map<String, dynamic> d) {
    final days = _n(d['days']);
    final lab = _m(d['lab']);
    return _box(
      p,
      border: p.purple,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('A/B Research Scoreboard', style: context.type.section.copyWith(fontSize: 14)),
              Text('sirf observer - koi trade change / block nahi', style: context.type.metadata),
            ]),
          ),
          GestureDetector(onTap: _load, child: Icon(Icons.refresh_rounded, size: 18, color: p.textMuted)),
        ]),
        const SizedBox(height: 10),
        Row(children: [
          for (final t in const ['3m', '5m', '15m'])
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(t),
                selected: _tf == t,
                onSelected: (_) {
                  setState(() => _tf = t);
                  _load();
                },
              ),
            ),
          const Spacer(),
          TextButton(onPressed: _reset, child: const Text('Restart test')),
        ]),
        Text(
          'Live test ko ${days.toStringAsFixed(1)} din hue  |  signals saved: ${_i(d['signals'])}'
          '  |  leverage ${_n(d['leverage']).toStringAsFixed(0)}x'
          '${_i(lab['pending']) > 0 ? '  |  ${_i(lab['pending'])} abhi chal rahe' : ''}',
          style: context.type.metadata,
        ),
      ]),
    );
  }

  Widget _section(BuildContext context, AppPalette p, String id, String title, Map<String, dynamic> b,
      {required String sub}) {
    final lines = _l(b['lines']);
    return _box(
      p,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(title, style: context.type.section.copyWith(fontSize: 13))),
          Text('${_i(b['n'])} signals', style: context.type.metadata),
        ]),
        Text(sub, style: context.type.metadata),
        const SizedBox(height: 10),
        if (lines.isEmpty)
          Text('Abhi is test ke liye signals nahi aaye. Thoda wait karo.', style: context.type.secondary)
        else
          for (final ln in lines) ...[
            _lineCard(context, p, '$id-${ln['key']}', ln, lines.first),
            const SizedBox(height: 8),
          ],
      ]),
    );
  }

  Widget _lineCard(BuildContext context, AppPalette p, String id, Map<String, dynamic> ln, Map<String, dynamic> bot) {
    final net = _n(ln['net']);
    final isBot = ln['key'] == 'bot';
    final v = _m(ln['verdict']);
    final code = (v['code'] ?? '').toString();
    final diff = net - _n(bot['net']);
    final open = _open.contains(id);
    final tp = (ln['tp'] is List) ? (ln['tp'] as List) : const [];
    final rules = _l(ln['rules']);
    return GestureDetector(
      onTap: () => setState(() => open ? _open.remove(id) : _open.add(id)),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: p.surfaceHigher, borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 2)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text((ln['title'] ?? '').toString(), style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
            if (!isBot && code.isNotEmpty) _chip(code, _vColor(p, code)),
            Icon(open ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 18, color: p.textMuted),
          ]),
          const SizedBox(height: 6),
          Row(children: [
            _stat(context, 'Net ROI', _sg(net), color: net >= 0 ? p.profit : p.loss),
            _stat(context, 'Trades', '${_i(ln['n'])}'),
            _stat(context, 'Wins', '${_i(ln['wins'])} (${_n(ln['win_rate']).toStringAsFixed(0)}%)'),
            _stat(context, 'Drawdown', '-${_n(ln['drawdown']).toStringAsFixed(1)}%'),
          ]),
          if (!isBot)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text('Bot se farq: ${_sg(diff)}  |  skip: ${_i(ln['skipped'])}  |  loss bacha: ${_sg(_n(ln['saved']))}',
                  style: context.type.secondary),
            ),
          if (open) ...[
            const SizedBox(height: 8),
            Text(
              'SL (original): ${_i(ln['sl'])}   |   TP1->BE exit: ${_i(ln['be'])}   |   REV/timeout: ${_i(ln['other'])}',
              style: context.type.secondary,
            ),
            Text(
              'TP tak pahunche:  TP1 ${tp.isNotEmpty ? tp[0] : 0}  |  TP2 ${tp.length > 1 ? tp[1] : 0}  |  '
              'TP3 ${tp.length > 2 ? tp[2] : 0}  |  TP4 ${tp.length > 3 ? tp[3] : 0}',
              style: context.type.secondary,
            ),
            if (!isBot)
              Text(
                'Achhe trade bhi gaye: ${_i(ln['good_lost_n'])} (${_sg(-_n(ln['good_lost']))})'
                '${ln['luck_pct'] is num ? '  |  luck chance: ${_n(ln['luck_pct']).toStringAsFixed(0)}%' : ''}',
                style: context.type.secondary,
              ),
            if ((v['text'] ?? '').toString().isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(v['text'].toString(), style: context.type.metadata.copyWith(color: _vColor(p, code))),
              ),
            for (final r in rules)
              Container(
                margin: const EdgeInsets.only(top: 8),
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: p.surfaceElevated,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: p.purple.withOpacity(0.5), width: 0.6),
                ),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('SKIP: ${r['label']}', style: context.type.primary.copyWith(fontSize: 12, fontWeight: FontWeight.w700, color: p.purple)),
                  const SizedBox(height: 2),
                  Text((r['why'] ?? '').toString(), style: context.type.metadata),
                ]),
              ),
          ],
        ]),
      ),
    );
  }

  // ----------------------------------------------------------- relationship table
  Widget _relation(BuildContext context, AppPalette p, Map<String, dynamic> rel) {
    final rows = _l(rel[_rel]);
    return _box(
      p,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('Price vs Z-score  x  TSI', style: context.type.section.copyWith(fontSize: 13))),
          for (final k in const [['pz3', '3 candle'], ['pz10', '10 candle']])
            Padding(
              padding: const EdgeInsets.only(left: 6),
              child: ChoiceChip(
                label: Text(k[1], style: const TextStyle(fontSize: 11)),
                selected: _rel == k[0],
                onSelected: (_) => setState(() => _rel = k[0]),
              ),
            ),
        ]),
        Text(
          'WITH / AGAINST = trade ki disha ke hisaab se (LONG me Price WITH = price upar, Z AGAINST = Z neeche). '
          'Har row: kitne signals aaye aur kaise khatam hue.',
          style: context.type.metadata,
        ),
        const SizedBox(height: 8),
        if (rows.isEmpty)
          Text('Abhi har combination ke liye kam signals hain.', style: context.type.secondary)
        else
          for (final r in rows)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(color: p.surfaceHigher, borderRadius: BorderRadius.circular(8)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${r['price_z']}  +  ${r['tsi']}', style: context.type.primary.copyWith(fontSize: 12, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 4),
                  Row(children: [
                    _stat(context, 'Signals', '${_i(r['n'])}'),
                    _stat(context, 'Avg ROI', _sg(_n(r['avg']), d: 2), color: _n(r['avg']) >= 0 ? p.profit : p.loss),
                    _stat(context, 'Win', '${_n(r['win_rate']).toStringAsFixed(0)}%'),
                    _stat(context, 'Naye data', r['avg_new'] is num ? _sg(_n(r['avg_new']), d: 2) : '-'),
                  ]),
                  const SizedBox(height: 2),
                  Text(
                    'SL ${_n(r['sl']).toStringAsFixed(0)}%  |  TP1->BE ${_n(r['be']).toStringAsFixed(0)}%  |  TP1 tak ${_n(r['tp1']).toStringAsFixed(0)}%'
                    '${_i(r['n']) < 30 ? '  |  sample kam' : ''}',
                    style: context.type.metadata,
                  ),
                ]),
              ),
            ),
      ]),
    );
  }
}
