import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'pd_widgets.dart';

/// Round 2 (28 Nov 2026): "Taiyari me" (pre-pump / pre-dump) of the Pump / Dump tab. Data = GET /api/pd/pre (backend/pd_pre.py).
/// Coins whose price is still flat while volume rises and buyers (or sellers) arrive. Same card style as Round 1 (name, one plain sentence,
/// big CHANCE, one level, thin strength bar); every number is in the details sheet. Plain widgets, no provider, no timer.
/// Dart NOT compiled in the sandbox: the GitHub APK build is the first compile.

/// Minutes as text. Over 60 min = hours + minutes ("2 h 10 min"), never "130 min" (owner rule).
String pdDur(num m) {
  final t = m.round();
  if (t < 60) return '$t min';
  final h = t ~/ 60;
  final r = t % 60;
  return r == 0 ? '$h h' : '$h h $r min';
}

String _n(dynamic v, [int d = 2]) => v == null ? '-' : pdNum(v).toStringAsFixed(d);

String pdPreSentence(Map<String, dynamic> c, bool pump) {
  final who = pump ? 'buyers' : 'sellers';
  final base = 'Abhi shaant hai, par $who aa rahe hain';
  return '$base. Volume ${_n(c['vol_ratio'], 1)} guna, price ${_n(c['range_pct'], 1)}% ki range me';
}

Widget _pdPreRow(AppPalette p, String k, String v) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 118, child: Text(k, style: TextStyle(fontSize: 12, color: p.textMuted))),
        Expanded(child: Text(v, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: p.textPrimary))),
      ]),
    );

/// Three small chips: which of the 3 signals are on (TSI palta, momentum palta, buyers / sellers ka share).
Widget _pdPreChips(AppPalette p, Map sig, bool pump, Color col) {
  Widget chip(String t, bool on) => Container(
        margin: const EdgeInsets.only(right: 4),
        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
        decoration: BoxDecoration(color: (on ? col : p.textMuted).withOpacity(on ? 0.16 : 0.08), borderRadius: BorderRadius.circular(5)),
        child: Text(t, style: TextStyle(fontSize: 9, fontWeight: FontWeight.w700, color: on ? col : p.textMuted)),
      );
  return Wrap(runSpacing: 3, children: [
    chip('Palat', sig['tsi_on'] == true),
    chip('Momentum', sig['hist_on'] == true),
    chip(pump ? 'Buyers' : 'Sellers', sig['taker_on'] == true),
  ]);
}

/// One coin of "Taiyari me". Tap = every number + the chart.
class PdPreCard extends StatelessWidget {
  final Map<String, dynamic> c;
  final bool pump;
  final int ts;
  const PdPreCard({super.key, required this.c, required this.pump, required this.ts});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final col = pump ? p.profit : p.loss;
    final fading = c['fading'] == true;
    final tagCol = fading ? p.warning : col;
    final ch = c['chance'] is Map ? c['chance'] as Map : <dynamic, dynamic>{};
    final est = ch['est'] != false;
    final score = pdNum(c['score']).clamp(0, 100).toDouble();
    final lvl = pdNum(c['level']);
    final sig = c['sig'] is Map ? c['sig'] as Map : <dynamic, dynamic>{};
    return GestureDetector(
      onTap: () => showPdPreDetail(context, c, pump, ts),
      child: Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.all(9),
        decoration: BoxDecoration(
          gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [col.withOpacity(0.10), p.surface]),
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
          border: Border.all(color: col.withOpacity(fading ? 0.25 : 0.45)),
          boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.12), blurRadius: 6, offset: const Offset(0, 2))],
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(pdCoin('${c['symbol']}'), maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
            Icon(Icons.candlestick_chart_outlined, size: 16, color: p.textMuted),
          ]),
          const SizedBox(height: 4),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
            decoration: BoxDecoration(color: tagCol.withOpacity(0.16), borderRadius: BorderRadius.circular(5)),
            child: Text(fading ? 'KAMZOR HO RAHA' : 'TAIYARI ME', style: TextStyle(fontSize: 9, fontWeight: FontWeight.w800, color: tagCol, letterSpacing: 0.2)),
          ),
          const SizedBox(height: 6),
          Text(pdPreSentence(c, pump), style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
          const SizedBox(height: 6),
          _pdPreChips(p, sig, pump, col),
          const SizedBox(height: 6),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text('${pdNum(ch['pct']).toStringAsFixed(0)}%', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: col)),
            const SizedBox(width: 6),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(bottom: 3),
                child: Text(est ? 'chance (andaaza)' : '${ch['worked']} / ${ch['checked']} chale', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
              ),
            ),
          ]),
          if (lvl > 0) ...[
            const SizedBox(height: 4),
            Text(pump ? 'Ye ${pdPrice(lvl)} ke neeche gaya to signal kharab' : 'Ye ${pdPrice(lvl)} ke upar gaya to signal kharab', style: TextStyle(fontSize: 10.5, color: p.textSecondary)),
          ],
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(value: score / 100.0, minHeight: 4, backgroundColor: col.withOpacity(0.15), valueColor: AlwaysStoppedAnimation<Color>(col)),
          ),
          const SizedBox(height: 3),
          Text('Taiyari ${score.toStringAsFixed(0)} / 100 · ${pdDur(pdNum(c['since_min']))} se list me', style: TextStyle(fontSize: 10, color: p.textMuted)),
        ]),
      ),
    );
  }
}

/// Details of one coin: every number + Open chart.
void showPdPreDetail(BuildContext context, Map<String, dynamic> c, bool pump, int ts) {
  final p = context.palette;
  final ch = c['chance'] is Map ? c['chance'] as Map : <dynamic, dynamic>{};
  final sig = c['sig'] is Map ? c['sig'] as Map : <dynamic, dynamic>{};
  final tf = c['tf'] is Map ? c['tf'] as Map : <dynamic, dynamic>{};
  final who = pump ? 'buyers' : 'sellers';
  showModalBottomSheet<void>(
    context: context,
    backgroundColor: p.surfaceElevated,
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(18))),
    builder: (ctx) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
        child: SingleChildScrollView(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text('${pdCoin('${c['symbol']}')}  ·  ${pump ? 'Pre-pump' : 'Pre-dump'}  ·  taiyari me', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 6),
            Text(pdPreSentence(c, pump), style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () {
                  Navigator.of(ctx).pop();
                  pdOpenChart(context, {'symbol': c['symbol'], 'price': c['price'], 'ts': ts}, pump);
                },
                icon: const Icon(Icons.candlestick_chart_outlined, size: 18),
                label: const Text('Open chart'),
              ),
            ),
            const SizedBox(height: 8),
            _pdPreRow(p, 'Price', pdPrice(pdNum(c['price']))),
            _pdPreRow(p, 'Move 15 min', '${pdSigned(pdNum(c['move_15m']), digits: 2)}  (+ = move ke saath)'),
            _pdPreRow(p, 'Price range', '${_n(c['range_pct'], 1)}% pichhle 60 min me'),
            _pdPreRow(p, 'Volume', '${_n(c['vol_ratio'], 1)}x (15 min vs pichhla ghanta)'),
            _pdPreRow(p, 'Taiyari', '${_n(c['score'], 0)} / 100  (${sig['n'] ?? 0} of 3 signal on)'),
            _pdPreRow(p, 'TSI palta', '${sig['tsi'] ?? 0} time frame me ${sig['tsi_on'] == true ? '(on)' : '(kam)'}'),
            _pdPreRow(p, 'Momentum palta', '${sig['hist'] ?? 0} time frame me ${sig['hist_on'] == true ? '(on)' : '(kam)'}'),
            _pdPreRow(p, '${pump ? 'Buyers' : 'Sellers'} share', sig['taker'] == null ? 'data aa raha hai' : '${(pdNum(sig['taker']) * 100).toStringAsFixed(0)}% ($who) ${sig['taker_on'] == true ? '(on)' : '(kam)'}'),
            _pdPreRow(p, 'List me', '${pdDur(pdNum(c['since_min']))} se${c['fading'] == true ? ' (signal kamzor ho raha)' : ''}'),
            _pdPreRow(p, 'Chance', '${_n(ch['pct'], 0)}%  ·  ${ch['est'] == false ? 'asli: ${ch['worked']} / ${ch['checked']} chale' : 'andaaza, abhi ${ch['checked']} alert check hue (100 chahiye)'}'),
            const Divider(height: 22),
            Text('Indicator numbers (TSI 25/5/14, Z 200, ZSM 200, EMA 50)', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 4),
            if (tf.isEmpty) Text('Candle data abhi aa raha hai.', style: TextStyle(fontSize: 12, color: p.textMuted)),
            for (final k in const ['5m', '15m', '1h', '2h'])
              if (tf[k] is Map)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Text(
                    '$k   TSI ${_n((tf[k] as Map)['tsi'], 1)} ${(tf[k] as Map)['tsi_up'] == true ? '↑' : ((tf[k] as Map)['tsi_up'] == false ? '↓' : '')}  hist ${_n((tf[k] as Map)['hist'], 1)}  Z ${_n((tf[k] as Map)['z200'])}  ZSM ${_n((tf[k] as Map)['zsm'])}  EMA50 ${_n((tf[k] as Map)['ema50'], 1)}%',
                    style: TextStyle(fontSize: 11.5, color: p.textSecondary),
                  ),
                ),
            const SizedBox(height: 10),
            Text('Ye heads-up hai, buy / sell order nahi. Pre signal me fake zyada hote hain.', style: TextStyle(fontSize: 11, color: p.textMuted)),
          ]),
        ),
      ),
    ),
  );
}

/// The whole Round 2 block: "Taiyari me" (pre-pump left, pre-dump right).
class PdPreSection extends StatelessWidget {
  final Map<String, dynamic>? data;
  const PdPreSection({super.key, required this.data});

  Widget _head(AppPalette p, String t, String sub) => Padding(
        padding: const EdgeInsets.only(top: 4, bottom: 8),
        child: Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
          Text(t, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(width: 8),
          Expanded(child: Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, color: p.textMuted))),
        ]),
      );

  Widget _note(AppPalette p, String text, {Color? color}) => Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: (color ?? p.textMuted).withOpacity(0.10), borderRadius: BorderRadius.circular(AppSpacing.radiusSmall)),
        child: Text(text, style: TextStyle(fontSize: 12, color: p.textSecondary)),
      );

  List<Widget> _cards(dynamic rows, bool pump, int ts) => [
        for (final r in (rows is List ? rows : const <dynamic>[]))
          if (r is Map) PdPreCard(c: Map<String, dynamic>.from(r), pump: pump, ts: ts),
      ];

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = data;
    if (d == null) {
      return Padding(padding: const EdgeInsets.symmetric(vertical: 10), child: ClipRRect(borderRadius: BorderRadius.circular(3), child: const LinearProgressIndicator(minHeight: 3)));
    }
    if (d['state'] != null) {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(p, 'Taiyari me', 'abhi available nahi'),
        _note(p, 'Taiyari me phone ke backend par abhi nahi hai. Repo update karo, phir owloff, owlon.'),
      ]);
    }
    final ts = pdNum(d['ts']).toInt();
    final limited = '${d['limited'] ?? ''}';
    final pre = d['pre'] is Map ? d['pre'] as Map : <dynamic, dynamic>{};
    final a = _cards(pre['pump'], true, ts);
    final b = _cards(pre['dump'], false, ts);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _head(p, 'Taiyari me', 'price abhi shaant, buyers / sellers aa rahe hain'),
      if (limited.isNotEmpty) _note(p, '$limited. Candle numbers thodi der late ho sakte hain.', color: p.warning),
      if (d['ready'] != true) _note(p, 'Taiyari ho rahi hai: price ka lagbhag 40 min ka history ban raha hai. Tab tak list khaali rahegi.', color: p.warning),
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(child: PdSideColumn(pump: true, count: a.length, children: a, emptyText: 'Abhi koi coin taiyari me nahi')),
        const SizedBox(width: 8),
        Expanded(child: PdSideColumn(pump: false, count: b.length, children: b, emptyText: 'Abhi koi coin taiyari me nahi')),
      ]),
      const SizedBox(height: 6),
      Text('Chance = ${pdNum(d['real_move']).toStringAsFixed(0)}%+ move ${pdDur(pdNum(d['check_min']))} me. Andaaza hai jab tak ${d['min_outcomes'] ?? 100} alert check na ho jayein. Ye buy / sell order nahi hai.', style: TextStyle(fontSize: 11, color: p.textMuted)),
    ]);
  }
}
