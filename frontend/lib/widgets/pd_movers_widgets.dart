import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'pd_widgets.dart';

/// Round 1 (28 Nov 2026): "Naye movers" + "Pehle se chal rahe hain" of the Pump / Dump tab. Data = GET /api/pd/movers (backend/pd_rank.py).
/// Plain words on the card (one sentence, one big CHANCE number, one level, a thin strength bar); every technical number is in the details sheet.
/// Plain widgets, no provider, no timer. Dart NOT compiled in the sandbox: the GitHub APK build is the first compile.

String pdMoverSentence(Map<String, dynamic> c, bool pump) {
  final m15 = pdNum(c['move_15m']); // + = with the move
  final signed = pump ? m15 : -m15;
  if ('${c['kind']}' == 'run') {
    final v = c['vol15'] == null ? null : pdNum(c['vol15']);
    final vtxt = v == null ? '' : ', volume ${v.toStringAsFixed(1)} guna (pichhle ghante se)';
    if (pdMoverState(c) == 'ended') {
      final back = pdNum(c['giveback']).toStringAsFixed(0);
      final pk = pdNum(c['peak']);
      return pump
          ? 'Pump ulta ho gaya. ${pk > 0 ? 'Peak ${pdPrice(pk)} se' : 'Peak se'} $back% wapas aa gaya, 15 min me ${pdSigned(signed)}'
          : 'Dump ulta ho gaya. ${pk > 0 ? 'Low ${pdPrice(pk)} se' : 'Low se'} $back% wapas upar aa gaya, 15 min me ${pdSigned(signed)}';
    }
    if (signed < 0 && pdMoverState(c) == 'running') return pump ? 'Upar ka move ruka hua hai, 15 min me ${pdSigned(signed)}$vtxt' : 'Neeche ka move ruka hua hai, 15 min me ${pdSigned(signed)}$vtxt';
    if (pdMoverState(c) == 'tiring') return pump ? 'Pump thak sa raha hai$vtxt' : 'Dump thak sa raha hai$vtxt';
    return '${pump ? 'Abhi bhi upar chal raha hai' : 'Abhi bhi neeche chal raha hai'}, 15 min me ${pdSigned(signed)}$vtxt';
  }
  return '${pump ? 'Upar chadh raha hai' : 'Neeche gir raha hai'}, 15 min me ${pdSigned(signed)}, volume ${pdNum(c['vol_ratio']).toStringAsFixed(1)} guna';
}

/// Part A (29 Nov 2026): the tag comes from the backend (pd_rank.py Rank._state): new | running | tiring | ended. The app never builds its own tag.
/// An older backend has no state: the old tiring flag is the fallback.
String pdMoverState(Map<String, dynamic> c) {
  final s = '${c['state'] ?? ''}';
  if (s.isNotEmpty) return s;
  if ('${c['kind']}' != 'run') return 'new';
  return c['tiring'] == true ? 'tiring' : 'running';
}

String _num(dynamic v, [int d = 2]) => v == null ? '-' : pdNum(v).toStringAsFixed(d);

Widget _row(AppPalette p, String k, String v) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 118, child: Text(k, style: TextStyle(fontSize: 12, color: p.textMuted))),
        Expanded(child: Text(v, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: p.textPrimary))),
      ]),
    );

/// One coin of "Naye movers" (kind new) or "Pehle se chal rahe hain" (kind run). Tap = every number + the chart.
class PdMoverCard extends StatelessWidget {
  final Map<String, dynamic> c;
  final bool pump;
  final int ts;
  const PdMoverCard({super.key, required this.c, required this.pump, required this.ts});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final run = '${c['kind']}' == 'run';
    final state = pdMoverState(c);
    final ended = run && state == 'ended';
    final tiring = state == 'tiring';
    final col = ended ? p.textMuted : (pump ? p.profit : p.loss);
    final tag = ended ? 'ULTA HO GAYA' : (run ? (tiring ? 'THAK RAHA' : 'CHAL RAHA') : 'NAYA');
    final tagCol = tiring ? p.warning : col;
    final ch = c['chance'] is Map ? c['chance'] as Map : <dynamic, dynamic>{};
    final est = ch['est'] != false;
    final strength = pdNum(c['strength']).clamp(0, 100).toDouble();
    final lvl = pdNum(c['level']);
    return GestureDetector(
      onTap: () => showPdMoverDetail(context, c, pump, ts),
      child: Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.all(9),
        decoration: BoxDecoration(
          gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [col.withOpacity(0.12), p.surface]),
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
          border: Border.all(color: col.withOpacity(0.45)),
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
            child: Text(tag, style: TextStyle(fontSize: 9, fontWeight: FontWeight.w800, color: tagCol, letterSpacing: 0.2)),
          ),
          const SizedBox(height: 6),
          Text(pdMoverSentence(c, pump), style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
          const SizedBox(height: 6),
          if (ended) Text('Ab alert nahi, sirf record. Peak ${pdPrice(pdNum(c['peak']))}, ab ${pdPrice(pdNum(c['price']))}', style: TextStyle(fontSize: 11, color: p.textMuted)),
          if (!ended) Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text('${pdNum(ch['pct']).toStringAsFixed(0)}%', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: col)),
            const SizedBox(width: 6),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.only(bottom: 3),
                child: Text(est ? 'chance (andaaza)' : '${ch['worked']} / ${ch['checked']} chale', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
              ),
            ),
          ]),
          if (lvl > 0 && !ended) ...[
            const SizedBox(height: 4),
            Text(pump ? 'Ye ${pdPrice(lvl)} ke neeche gaya to kamzor' : 'Ye ${pdPrice(lvl)} ke upar gaya to kamzor', style: TextStyle(fontSize: 10.5, color: p.textSecondary)),
          ],
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(value: strength / 100.0, minHeight: 4, backgroundColor: col.withOpacity(0.15), valueColor: AlwaysStoppedAnimation<Color>(col)),
          ),
          const SizedBox(height: 3),
          Text('Taakat ${strength.toStringAsFixed(0)} / 100${c['partial'] == true ? ' · candle data aa raha hai' : ''}', style: TextStyle(fontSize: 10, color: p.textMuted)),
        ]),
      ),
    );
  }
}

/// Details of one coin: every number (rank, moves, volume, buyers, strength parts, the TSI / Z / EMA numbers per time frame) + Open chart.
void showPdMoverDetail(BuildContext context, Map<String, dynamic> c, bool pump, int ts) {
  final p = context.palette;
  final ch = c['chance'] is Map ? c['chance'] as Map : <dynamic, dynamic>{};
  final parts = c['parts'] is Map ? c['parts'] as Map : <dynamic, dynamic>{};
  final tf = c['tf'] is Map ? c['tf'] as Map : <dynamic, dynamic>{};
  final run = '${c['kind']}' == 'run';
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
            Text('${pdCoin('${c['symbol']}')}  ·  ${pump ? 'Pump' : 'Dump'}  ·  ${run ? (pdMoverState(c) == 'ended' ? 'ulta ho gaya' : 'pehle se chal raha') : 'naya mover'}', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 6),
            Text(pdMoverSentence(c, pump), style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
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
            _row(p, 'Price', pdPrice(pdNum(c['price']))),
            if (run && c['peak'] != null) _row(p, 'Peak se wapas', 'peak ${pdPrice(pdNum(c['peak']))}  ·  ${pdNum(c['giveback']).toStringAsFixed(0)}% wapas aaya  ·  poora move ${pdNum(c['move_peak']).toStringAsFixed(1)}%'),
            _row(p, 'Binance 24h list', '#${c['rank']}${run ? '' : '  (${c['rank_gain']} jagah upar)'}  ·  24h ${pdSigned(pdNum(c['chg24']))}'),
            _row(p, 'Move 5m / 15m', '${pdSigned(pdNum(c['move_5m']), digits: 2)}  /  ${pdSigned(pdNum(c['move_15m']), digits: 2)}  (+ = move ke saath)'),
            _row(p, 'Volume', run ? '${_num(c['vol15'], 1)}x (15 min vs pichhla ghanta)' : '${_num(c['vol_ratio'], 1)}x apne ghante ka'),
            _row(p, 'Move wali side share', c['buyers_share'] == null ? 'data aa raha hai' : '${(pdNum(c['buyers_share']) * 100).toStringAsFixed(0)}% (pump me buyers, dump me sellers)'),
            _row(p, 'Taakat', '${_num(c['strength'], 0)} / 100  (${c['tf_agree']} of 6 time frame ek raay)'),
            _row(p, 'Taakat ke hisse', 'volume ${_num(parts['vol'])}  buyers ${_num(parts['taker'])}  TSI ${_num(parts['tsi'])}  hist ${_num(parts['hist'])}  tf ${_num(parts['tf'])}  rank ${_num(parts['rank'])}'),
            _row(p, 'Chance', '${_num(ch['pct'], 0)}%  ·  ${ch['est'] == false ? 'asli: ${ch['worked']} / ${ch['checked']} chale' : 'andaaza, abhi ${ch['checked']} alert check hue (100 chahiye)'}'),
            const Divider(height: 22),
            Text('Indicator numbers (TSI 25/5/14, Z 200, ZSM 200, EMA 30/50)', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 4),
            if (tf.isEmpty) Text('Candle data abhi aa raha hai (cache me kuch nahi).', style: TextStyle(fontSize: 12, color: p.textMuted)),
            for (final k in const ['5m', '15m', '1h', '2h', '4h', '1d'])
              if (tf[k] is Map)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Text(
                    '$k   TSI ${_num((tf[k] as Map)['tsi'], 1)} ${(tf[k] as Map)['tsi_up'] == true ? '↑' : ((tf[k] as Map)['tsi_up'] == false ? '↓' : '')}  hist ${_num((tf[k] as Map)['hist'], 1)}  Z ${_num((tf[k] as Map)['z200'])}  ZSM ${_num((tf[k] as Map)['zsm'])}  EMA50 ${_num((tf[k] as Map)['ema50'], 1)}%',
                    style: TextStyle(fontSize: 11.5, color: p.textSecondary),
                  ),
                ),
            const SizedBox(height: 10),
            Text('Ye heads-up hai, buy / sell order nahi. Kuch alert fake honge.', style: TextStyle(fontSize: 11, color: p.textMuted)),
          ]),
        ),
      ),
    ),
  );
}

/// The whole Round 1 block: "Naye movers" (pump left, dump right) and under it "Pehle se chal rahe hain".
class PdMoversSection extends StatelessWidget {
  final Map<String, dynamic>? data;
  const PdMoversSection({super.key, required this.data});

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
          if (r is Map) PdMoverCard(c: Map<String, dynamic>.from(r), pump: pump, ts: ts),
      ];

  Widget _two(Map grp, int ts, String emptyPump, String emptyDump) {
    final a = _cards(grp['pump'], true, ts);
    final b = _cards(grp['dump'], false, ts);
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Expanded(child: PdSideColumn(pump: true, count: a.length, children: a, emptyText: emptyPump)),
      const SizedBox(width: 8),
      Expanded(child: PdSideColumn(pump: false, count: b.length, children: b, emptyText: emptyDump)),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = data;
    if (d == null) {
      return Padding(padding: const EdgeInsets.symmetric(vertical: 10), child: ClipRRect(borderRadius: BorderRadius.circular(3), child: const LinearProgressIndicator(minHeight: 3)));
    }
    if (d['state'] != null) {
      return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(p, 'Naye movers', 'abhi available nahi'),
        _note(p, 'Naye movers phone ke backend par abhi nahi hain. Repo update karo, phir owloff, owlon.'),
      ]);
    }
    final ts = pdNum(d['ts']).toInt();
    final ready = d['ready'] == true;
    final limited = '${d['limited'] ?? ''}';
    final mv = d['movers'] is Map ? d['movers'] as Map : <dynamic, dynamic>{};
    final rn = d['running'] is Map ? d['running'] as Map : <dynamic, dynamic>{};
    final en = d['ended'] is Map ? d['ended'] as Map : <dynamic, dynamic>{};
    final enN = ((en['pump'] is List ? en['pump'] as List : const <dynamic>[]).length) + ((en['dump'] is List ? en['dump'] as List : const <dynamic>[]).length);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _head(p, 'Naye movers', 'top 10 ke bahar, volume ke saath'),
      if (limited.isNotEmpty) _note(p, '$limited. Candle numbers thodi der late ho sakte hain.', color: p.warning),
      if (!ready) _note(p, 'Taiyari ho rahi hai: rank ka history ban raha hai (${pdNum(d['rank_warm_min']).toStringAsFixed(0)} min aur). Tab tak list khaali rahegi.', color: p.warning),
      _two(mv, ts, 'Abhi koi naya coin nahi mila', 'Abhi koi naya coin nahi mila'),
      const SizedBox(height: 16),
      _head(p, 'Pehle se chal rahe hain', 'sirf jo abhi chal rahe hain'),
      _two(rn, ts, 'Top 10 me abhi koi chalta coin nahi', 'Top 10 me abhi koi girta coin nahi'),
      if (enN > 0)
        Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            tilePadding: EdgeInsets.zero,
            childrenPadding: EdgeInsets.zero,
            title: Text('Khatam ho gaye ($enN)', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary)),
            subtitle: Text('Ulta ho gaye, ab alert nahi. Sirf record', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
            children: [_two(en, ts, 'Koi pump khatam nahi hua', 'Koi dump khatam nahi hua')],
          ),
        ),
      const SizedBox(height: 6),
      Text('Chance andaaza hai jab tak ${d['min_outcomes'] ?? 100} alert check na ho jayein. Ye buy / sell order nahi hai.', style: TextStyle(fontSize: 11, color: p.textMuted)),
    ]);
  }
}
