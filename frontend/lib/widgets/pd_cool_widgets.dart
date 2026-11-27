import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'pd_pre_widgets.dart';
import 'pd_widgets.dart';

/// Part 4 (Round 3 part B, 28 Nov 2026): "Cooling watch" of the Pump / Dump tab. Data = GET /api/pd/cool (backend/pd_cool.py).
/// Coins that pumped in the last 10 days: still running (TREND), top forming (PEAK), cooling down (COOLING), danger of a dump (WARNING),
/// dump started (DUMP_START). One card per coin: name, one plain sentence, one level, 5 small test chips, the learned chance (WARNING only).
/// Every number is in the details sheet. Plain widgets, no provider, no timer. Dart NOT compiled in the sandbox: the GitHub APK build is the first compile.

String _cn(dynamic v, [int d = 2]) => v == null ? '-' : pdNum(v).toStringAsFixed(d);

Color pdCoolColor(AppPalette p, String stage) {
  switch (stage) {
    case 'WARNING':
      return Colors.deepOrange;
    case 'DUMP_START':
      return p.loss;
    case 'TREND':
      return p.profit;
    case 'COOLING':
      return p.warning;
    default:
      return p.textMuted;
  }
}

String pdCoolTag(String stage) {
  switch (stage) {
    case 'WARNING':
      return 'KHATRA';
    case 'DUMP_START':
      return 'DUMP SHURU';
    case 'TREND':
      return 'CHAL RAHA';
    case 'COOLING':
      return 'THANDA PAD RAHA';
    default:
      return 'TOP BAN RAHA';
  }
}

String pdCoolSentence(Map<String, dynamic> c) {
  final lvl = pdPrice(pdNum(c['level']));
  final drop = _cn(c['drop_pct'], 1);
  switch ('${c['stage']}') {
    case 'WARNING':
      return 'Pump ke baad thak raha hai. Girne ka khatra badh raha hai. $lvl ke neeche gaya to dump.';
    case 'DUMP_START':
      return 'Dump shuru ho gaya, $lvl toota. Ab upar wala normal scanner dekhega.';
    case 'TREND':
      return 'Abhi bhi upar chal raha hai, volume theek hai. $lvl ke neeche gaya to kamzor.';
    case 'COOLING':
      return 'Pump ke baad thanda pad raha hai: top se $drop% neeche, volume kam. $lvl ke neeche gaya to dump.';
    default:
      return 'Pump ka top ban sakta hai: top se $drop% neeche. $lvl ke neeche gaya to dump.';
  }
}

Widget _coolRow(AppPalette p, String k, String v) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 118, child: Text(k, style: TextStyle(fontSize: 12, color: p.textMuted))),
        Expanded(child: Text(v, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: p.textPrimary))),
      ]),
    );

/// The 5 weakness tests as small chips (lit = the test is on, grey = off or no data yet).
Widget _coolChips(AppPalette p, Map t, Color col) {
  final items = <List<dynamic>>[
    ['Lower high', t['lower_high']],
    ['Red me volume', t['red_vol']],
    ['Sellers zyada', t['taker']],
    ['Momentum kamzor', t['tsi_weak']],
    ['Funding gir rahi', t['funding_down']],
  ];
  return Wrap(runSpacing: 3, children: [
    for (final it in items)
      Container(
        margin: const EdgeInsets.only(right: 4),
        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
        decoration: BoxDecoration(color: (it[1] == true ? col : p.textMuted).withOpacity(it[1] == true ? 0.16 : 0.08), borderRadius: BorderRadius.circular(5)),
        child: Text(it[0] as String, style: TextStyle(fontSize: 9, fontWeight: FontWeight.w700, color: it[1] == true ? col : p.textMuted)),
      ),
  ]);
}

/// One coin of the Cooling watch. Tap = every number + the chart.
class PdCoolCard extends StatelessWidget {
  final Map<String, dynamic> c;
  final int ts;
  const PdCoolCard({super.key, required this.c, required this.ts});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final stage = '${c['stage']}';
    final col = pdCoolColor(p, stage);
    final tests = c['tests'] is Map ? c['tests'] as Map : <dynamic, dynamic>{};
    final ch = c['chance'] is Map ? c['chance'] as Map : null;
    final showTests = stage == 'WARNING' || stage == 'COOLING';
    return GestureDetector(
      onTap: () => showPdCoolDetail(context, c, ts),
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [col.withOpacity(0.12), p.surface]),
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
          border: Border.all(color: col.withOpacity(0.45)),
          boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.12), blurRadius: 6, offset: const Offset(0, 2))],
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(pdCoin('${c['symbol']}'), maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800, color: p.textPrimary))),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(color: col.withOpacity(0.16), borderRadius: BorderRadius.circular(5)),
              child: Text(pdCoolTag(stage), style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w800, color: col, letterSpacing: 0.2)),
            ),
            const SizedBox(width: 6),
            Icon(Icons.candlestick_chart_outlined, size: 16, color: p.textMuted),
          ]),
          const SizedBox(height: 4),
          Text('Pump ${pdSigned(pdNum(c['pump_pct']), digits: 0)} · top se ${_cn(c['drop_pct'], 1)}% neeche · top ko ${pdDur(pdNum(c['since_peak_min']))} hue', style: TextStyle(fontSize: 10.5, color: p.textMuted)),
          const SizedBox(height: 6),
          Text(pdCoolSentence(c), style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
          if (showTests) ...[
            const SizedBox(height: 6),
            _coolChips(p, tests, col),
          ],
          if (ch != null) ...[
            const SizedBox(height: 6),
            Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text('${pdNum(ch['pct']).toStringAsFixed(0)}%', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: col)),
              const SizedBox(width: 6),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 3),
                  child: Text(ch['est'] == false ? 'girne ka chance: ${ch['worked']} / ${ch['checked']} chale' : 'girne ka chance (andaaza)', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
                ),
              ),
            ]),
          ],
        ]),
      ),
    );
  }
}

/// Details of one coin: every number + Open chart.
void showPdCoolDetail(BuildContext context, Map<String, dynamic> c, int ts) {
  final p = context.palette;
  final stage = '${c['stage']}';
  final tests = c['tests'] is Map ? c['tests'] as Map : <dynamic, dynamic>{};
  final ch = c['chance'] is Map ? c['chance'] as Map : null;
  final weak = c['tf_weak'] is List ? (c['tf_weak'] as List).join(', ') : '';
  String yn(dynamic v) => v == true ? 'haan' : (v == false ? 'nahi' : 'data aa raha hai');
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
            Text('${pdCoin('${c['symbol']}')}  ·  ${pdCoolTag(stage)}', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 6),
            Text(pdCoolSentence(c), style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () {
                  Navigator.of(ctx).pop();
                  pdOpenChart(context, {'symbol': c['symbol'], 'price': c['price'], 'ts': ts}, false);
                },
                icon: const Icon(Icons.candlestick_chart_outlined, size: 18),
                label: const Text('Open chart'),
              ),
            ),
            const SizedBox(height: 8),
            _coolRow(p, 'Price', pdPrice(pdNum(c['price']))),
            _coolRow(p, 'Pump ka top', '${pdPrice(pdNum(c['peak']))}  (pump ${pdSigned(pdNum(c['pump_pct']))})'),
            _coolRow(p, 'Top se neeche', '${_cn(c['drop_pct'], 1)}%  ·  top ko ${pdDur(pdNum(c['since_peak_min']))} hue'),
            _coolRow(p, 'Ye stage', '${pdDur(pdNum(c['stage_min']))} se'),
            _coolRow(p, 'Support level', pdPrice(pdNum(c['level']))),
            _coolRow(p, 'Volume', '${_cn(c['vol_ratio'], 2)}x pump ke volume ka (6 ghante)'),
            _coolRow(p, '12 ghante range', '${_cn(c['range12'], 1)}%'),
            _coolRow(p, 'Buyers share', '${(pdNum(c['taker6']) * 100).toStringAsFixed(0)}% (pichhli 6 candle)'),
            _coolRow(p, 'Funding', c['funding'] == null ? 'data aa raha hai' : '${(pdNum(c['funding']) * 100).toStringAsFixed(4)}%'),
            const Divider(height: 22),
            Text('Kamzori ke 5 test: ${c['weak_n'] ?? 0} of 5 on', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 4),
            _coolRow(p, 'Lower high bana', yn(tests['lower_high'])),
            _coolRow(p, 'Red me volume zyada', yn(tests['red_vol'])),
            _coolRow(p, 'Sellers zyada (<45%)', yn(tests['taker'])),
            _coolRow(p, 'Momentum kamzor', '${yn(tests['tsi_weak'])}${weak.isEmpty ? '' : '  ($weak)'}'),
            _coolRow(p, 'Funding gir rahi', yn(tests['funding_down'])),
            if (ch != null) ...[
              const SizedBox(height: 4),
              _coolRow(p, 'Girne ka chance', '${_cn(ch['pct'], 0)}%  ·  ${ch['est'] == false ? 'asli: ${ch['worked']} / ${ch['checked']} chale' : 'andaaza, abhi ${ch['checked']} alert check hue (100 chahiye)'}'),
            ],
            const SizedBox(height: 10),
            Text('Ye heads-up hai, sell order nahi. Kuch warning fake honge.', style: TextStyle(fontSize: 11, color: p.textMuted)),
          ]),
        ),
      ),
    ),
  );
}

/// The whole Part 4 block: "Cooling watch", WARNING first, then DUMP_START, COOLING, PEAK, TREND (the backend sends them sorted).
class PdCoolSection extends StatelessWidget {
  final Map<String, dynamic>? data;
  const PdCoolSection({super.key, required this.data});

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

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = data;
    if (d == null) {
      return Padding(padding: const EdgeInsets.symmetric(vertical: 10), child: ClipRRect(borderRadius: BorderRadius.circular(3), child: const LinearProgressIndicator(minHeight: 3)));
    }
    if (d['state'] != null) {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(p, 'Cooling watch', 'abhi available nahi'),
        _note(p, 'Cooling watch phone ke backend par abhi nahi hai. Repo update karo, phir owloff, owlon.'),
      ]);
    }
    final ts = pdNum(d['ts']).toInt();
    final limited = '${d['limited'] ?? ''}';
    final waiting = pdNum(d['waiting']).toInt();
    final rows = d['cool'] is List ? d['cool'] as List : const <dynamic>[];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _head(p, 'Cooling watch', 'pump ke baad girne ka khatra, ${pdNum(d['listed']).toInt()} coin watch me'),
      if (limited.isNotEmpty) _note(p, '$limited. Candle numbers thodi der late ho sakte hain.', color: p.warning),
      if (waiting > 0) _note(p, 'Candle data aa raha hai: $waiting coin baaki. Thodi der me list ban jayegi.', color: p.warning),
      if (rows.isEmpty)
        _note(p, d['listed'] == 0 ? 'Abhi koi pump wala coin watch me nahi (pichhle 10 din me 15%+ gainer chahiye).' : 'Abhi kisi coin me pump ke baad thakan nahi dikhi.')
      else
        for (final r in rows)
          if (r is Map) PdCoolCard(c: Map<String, dynamic>.from(r), ts: ts),
      const SizedBox(height: 4),
      Text('KHATRA ka chance = ${pdNum(d['real_move']).toStringAsFixed(0)}%+ girna ${pdDur(pdNum(d['check_min']))} me. Andaaza hai jab tak ${d['min_outcomes'] ?? 100} alert check na ho jayein. Ye sell order nahi hai.', style: TextStyle(fontSize: 11, color: p.textMuted)),
    ]);
  }
}
