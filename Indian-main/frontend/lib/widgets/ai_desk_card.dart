import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// AI DESK: the AI's own virtual account next to the bot.
/// Bot = EMA50 cross, as always. AI = same entry signal, but it decides LE / SKIP / WAIT from what the
/// old signals showed (Z-score, TSI, SD band) and manages its own exit (may hold past TP4 with a trail).
/// Everything is computed on the backend (GET /api/ai/desk, ai_desk.py). Display only: nothing here
/// opens, blocks or closes a bot trade.
class AiDeskCard extends StatefulWidget {
  /// embedded: no own scrolling/refresh (the host screen scrolls). part: 'all' | 'studies' (exit-rule replay + SD level
  /// study) | 'desk' (the old LE / SKIP / WAIT virtual account, its scorecard and decisions).
  final bool embedded;
  final String part;
  const AiDeskCard({super.key, this.embedded = false, this.part = 'all'});

  @override
  State<AiDeskCard> createState() => _AiDeskCardState();
}

class _AiDeskCardState extends State<AiDeskCard> with AutomaticKeepAliveClientMixin {
  Map<String, dynamic>? _d;
  Map<String, dynamic>? _lv; // SD level / Z-SMA behaviour study (GET /api/ai/levels)
  Map<String, dynamic>? _o; // observer: same bot trades under other exit rules (GET /api/ai/observer)
  bool _failed = false;
  bool _busy = false;
  Timer? _timer;

  @override
  bool get wantKeepAlive => true; // tab switch keeps the screen alive: no rebuild, no reload

  @override
  void initState() {
    super.initState();
    _d = context.read<AppProvider>().peekAi('/api/ai/desk'); // old numbers at once, fresh ones arrive behind them
    _o = context.read<AppProvider>().peekAi('/api/ai/observer');
    _lv = context.read<AppProvider>().peekAi('/api/ai/levels');
    _load();
    _timer = Timer.periodic(const Duration(seconds: 30), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_busy) return;
    _busy = true;
    final prov = context.read<AppProvider>();
    final r = await prov.fetchAiDesk();
    if (mounted) {
      setState(() {
        if (r != null) {
          _d = r;
          _failed = false;
        } else if (_d == null) {
          _failed = true;
        }
      });
    }
    final o = await prov.fetchAiObserver(); // second, so the desk numbers never wait for the replay
    final lv = await prov.fetchAiLevels(); // last: the desk and the replay never wait for it
    _busy = false;
    if (!mounted) return;
    if (o != null || lv != null) {
      setState(() {
        if (o != null) _o = o;
        if (lv != null) _lv = lv;
      });
    }
  }

  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<dynamic> _l(dynamic v) => v is List ? v : const [];
  static String _pct(dynamic v) => '${_n(v) >= 0 ? '+' : ''}${_n(v).toStringAsFixed(2)}%';

  static String _hm(dynamic ts) {
    if (ts is! num) return '--';
    final d = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round(), isUtc: true).add(const Duration(hours: 5, minutes: 30));
    return '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
  }

  Widget _card(AppPalette p, Widget child, {Color? edge}) => Container(
        width: double.infinity,
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: p.surfaceElevated,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
          border: Border.all(color: edge != null ? edge.withOpacity(0.45) : p.border, width: 1),
        ),
        child: child,
      );

  Widget _title(AppPalette p, String t) =>
      Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(t, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.6, color: p.textMuted)));

  Color _roiColor(AppPalette p, double v) => v > 0 ? p.profit : (v < 0 ? p.loss : p.textMuted);

  static String _usdt(dynamic v) => '${_n(v) >= 0 ? '+' : ''}${_n(v).toStringAsFixed(2)}';

  /// One row of the Bot | AI table.
  Widget _row(AppPalette p, String label, String bot, String ai, {Color? botColor, Color? aiColor, bool bold = false}) {
    final st = TextStyle(fontSize: bold ? 14 : 13, fontWeight: bold ? FontWeight.w800 : FontWeight.w600);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        Expanded(flex: 5, child: Text(label, style: TextStyle(fontSize: 12.5, color: p.textMuted))),
        Expanded(flex: 3, child: Text(bot, textAlign: TextAlign.right, style: st.copyWith(color: botColor ?? p.textPrimary))),
        Expanded(flex: 3, child: Text(ai, textAlign: TextAlign.right, style: st.copyWith(color: aiColor ?? p.textPrimary))),
      ]),
    );
  }

  Widget _chip(AppPalette p, String call) {
    final c = call == 'LE' ? p.profit : (call == 'SKIP' ? p.loss : p.warning);
    final t = call == 'LE' ? 'LE' : (call == 'SKIP' ? 'SKIP' : 'WAIT');
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: c.withOpacity(0.16), borderRadius: BorderRadius.circular(6)),
      child: Text(t, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: c)),
    );
  }

  Widget _learnRows(AppPalette p, List<dynamic> items, Color c) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final raw in items)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                child: Text('${_m(raw)['side'] == 'BUY' ? 'LONG' : 'SHORT'} | ${_m(raw)['kind']}: ${_m(raw)['text']}',
                    style: TextStyle(fontSize: 12.5, height: 1.3, color: p.textPrimary)),
              ),
              const SizedBox(width: 8),
              Text('${_pct(_m(raw)['avg'])}\n${_i(_m(raw)['n'])} signal',
                  textAlign: TextAlign.right, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: c)),
            ]),
          ),
      ]);

  /// One row of the "other exit rules" table.
  Widget _polRow(AppPalette p, Map<String, dynamic> r) {
    final v = (r['verdict'] ?? '').toString();
    final gain = _n(r['gain_total']);
    final collecting = v == 'COLLECTING';
    final tag = collecting
        ? '  [JAMA HO RAHA ${_i(r['have'])}/${_i(r['need'])}]'
        : (v == 'CLEAR' ? '  [PAKKA]' : (v == 'MAYBE' ? '  [DEKHO]' : (v == 'WORSE' ? '  [BEKAR]' : '')));
    final gainColor = v == 'CONTROL' ? p.textMuted : (v == 'CLEAR' ? p.profit : (v == 'MAYBE' ? p.warning : p.textMuted));
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        Expanded(flex: 6, child: Text('${r['name']}$tag', style: TextStyle(fontSize: 12.5, color: p.textPrimary))),
        Expanded(flex: 3, child: Text(_pct(r['avg']), textAlign: TextAlign.right, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: _roiColor(p, _n(r['avg']))))),
        Expanded(
            flex: 3,
            child: Text(v == 'CONTROL' ? 'control' : (collecting ? '...' : '${gain >= 0 ? '+' : ''}${gain.toStringAsFixed(0)}%'),
                textAlign: TextAlign.right, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: gainColor))),
      ]),
    );
  }

  /// "AI sab bot trades manage karta to": replay of the SAME trades (same entry, SL, TP) under other exit rules.
  List<Widget> _observerCards(AppPalette p) {
    final o = _o;
    if (o == null) return const [];
    // STEP1 / STEP2 (trailing tests) are shown in the Overview "Trailing test" card only, not here.
    final pol = _l(o['policies']).where((x) => !(x is Map && (x['key'] == 'STEP1' || x['key'] == 'STEP2'))).toList();
    final ee = _m(o['entry_exit']);
    final never = _m(ee['never']);
    final gave = _m(ee['gave_back']);
    final kept = _m(ee['kept']);
    final scen = _l(o['scenarios']);
    final coll = _l(o['collect']);
    final small = TextStyle(fontSize: 11.5, height: 1.35, color: p.textMuted);
    return [
      _card(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'AI SAB BOT TRADES MANAGE KARTA TO? (${_i(o['n'])} trade)'),
          Text((o['headline'] ?? '').toString(), style: TextStyle(fontSize: 13.5, height: 1.35, color: p.textPrimary, fontWeight: FontWeight.w600)),
          if (pol.isNotEmpty) ...[
            const SizedBox(height: 10),
            Row(children: [
              Expanded(flex: 6, child: Text('Exit rule', style: small)),
              Expanded(flex: 3, child: Text('Avg/trade', textAlign: TextAlign.right, style: small)),
              Expanded(flex: 3, child: Text('Bot se farak', textAlign: TextAlign.right, style: small)),
            ]),
            const Divider(height: 10),
            for (final raw in pol) _polRow(p, _m(raw)),
          ],
          const SizedBox(height: 6),
          Text('Wahi entry, wahi SL/TP. AI koi alag trade nahi leti, sirf bot ke trade ka journey dekhkar alag exit try karti hai. Fee kat ke.', style: small),
        ]),
      ),
      if (coll.any((c) => _i(_m(c)['have']) < _i(_m(c)['need'])) || _i(o['n']) == 0)
        _card(
          p,
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _title(p, 'DATA JAMA HO RAHA HAI'),
            Text('Bot ke har trade ka journey save ho raha hai. Verdict tab dikhega jab har cheez ke ${coll.isEmpty ? 30 : _i(_m(coll.first)['need'])}+ trade ho jayen. Tab tak "jama ho raha hai" likha rahega.', style: small),
            const SizedBox(height: 8),
            if (_i(o['n']) == 0) Text('Abhi 0 trade band hue journey ke saath.', style: TextStyle(fontSize: 12.5, color: p.textPrimary)),
            for (final raw in coll)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(children: [
                  Expanded(flex: 5, child: Text(_m(raw)['name'].toString(), style: TextStyle(fontSize: 12.5, color: p.textPrimary))),
                  Expanded(
                      flex: 5,
                      child: Text(
                          _i(_m(raw)['have']) >= _i(_m(raw)['need'])
                              ? 'ready (${_i(_m(raw)['have'])})'
                              : 'jama ho raha hai ${_i(_m(raw)['have'])}/${_i(_m(raw)['need'])}',
                          textAlign: TextAlign.right,
                          style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: _i(_m(raw)['have']) >= _i(_m(raw)['need']) ? p.profit : p.warning))),
                ]),
              ),
          ]),
        ),
      if (_i(ee['n']) > 0)
        _card(
          p,
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _title(p, 'NUKSAAN ENTRY SE YA EXIT SE?'),
            Text((ee['msg'] ?? '').toString(), style: TextStyle(fontSize: 13, height: 1.35, color: p.textPrimary)),
            const SizedBox(height: 8),
            _row(p, 'TP1 tak gaye hi nahi (${_i(never['n'])})', '', '${_n(never['sum']).toStringAsFixed(0)}%', aiColor: p.loss),
            _row(p, 'TP1 chhua, phir bhi haare (${_i(gave['n'])})', '', '${_n(gave['sum']).toStringAsFixed(0)}%', aiColor: p.loss),
            _row(p, 'TP1 chhua aur kamaya (${_i(kept['n'])})', '', '+${_n(kept['sum']).toStringAsFixed(0)}%', aiColor: p.profit),
          ]),
        ),
      if (scen.isNotEmpty)
        _card(
          p,
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _title(p, 'KIS SITUATION ME KAUN SA EXIT'),
            for (final raw in scen)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text('${_m(raw)['label']} (${_i(_m(raw)['n'])} trade): ${_m(raw)['msg']}',
                    style: TextStyle(fontSize: 12.5, height: 1.35, color: p.textPrimary)),
              ),
          ]),
        ),
    ];
  }

  /// "SD level / Z-SMA kaise behave karte hain": counts of bounce vs break, no rule taught.
  Widget _levelCard(AppPalette p) {
    final lv = _lv;
    if (lv == null) return const SizedBox.shrink();
    final small = TextStyle(fontSize: 11.5, height: 1.35, color: p.textMuted);
    final levels = _l(lv['levels']);
    final sit = _l(lv['situations']);
    final n = _i(lv['n']);
    final need = _i(lv['need']);
    return _card(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'SD LEVEL / Z-SMA KAISE BEHAVE KARTE HAIN'),
        Text(n < need ? 'Data jama ho raha hai: $n/$need event. Tab tak koi verdict nahi.' : (lv['headline'] ?? '').toString(),
            style: TextStyle(fontSize: 13, height: 1.35, color: n < need ? p.warning : p.textPrimary, fontWeight: FontWeight.w600)),
        if (levels.isNotEmpty) ...[
          const SizedBox(height: 8),
          Row(children: [
            Expanded(flex: 4, child: Text('Level', style: small)),
            Expanded(flex: 2, child: Text('Event', textAlign: TextAlign.right, style: small)),
            Expanded(flex: 3, child: Text('Bounce/Follow', textAlign: TextAlign.right, style: small)),
          ]),
          const Divider(height: 10),
          for (final raw in levels)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(children: [
                Expanded(flex: 4, child: Text(_m(raw)['label'].toString(), style: TextStyle(fontSize: 12.5, color: p.textPrimary))),
                Expanded(flex: 2, child: Text('${_i(_m(raw)['n'])}', textAlign: TextAlign.right, style: TextStyle(fontSize: 12.5, color: p.textMuted))),
                Expanded(
                    flex: 3,
                    child: Text(_i(_m(raw)['n']) < _i(_m(raw)['need']) ? 'jama ho raha hai' : '${_n(_m(raw)['rate']).toStringAsFixed(0)}%',
                        textAlign: TextAlign.right,
                        style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: _i(_m(raw)['n']) < _i(_m(raw)['need']) ? p.warning : p.textPrimary))),
              ]),
            ),
        ],
        if (sit.isNotEmpty) ...[
          const SizedBox(height: 8),
          for (final raw in sit)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                  '${_m(raw)['label']} (${_i(_m(raw)['n'])}): ${_n(_m(raw)['rate']).toStringAsFixed(0)}%'
                  '${_m(raw)['old'] == null ? '' : ' (purana ${_n(_m(raw)['old']).toStringAsFixed(0)}% / naya ${_n(_m(raw)['new']).toStringAsFixed(0)}%)'}'
                  '${_m(raw)['verdict'] == 'GOOD' ? '  [BOUNCE PAKKA]' : (_m(raw)['verdict'] == 'BAD' ? '  [TOOT JATA HAI]' : '  [EDGE NAHI]')}',
                  style: TextStyle(fontSize: 12, height: 1.3, color: p.textPrimary)),
            ),
        ],
        const SizedBox(height: 4),
        Text('Sirf ginti hai, koi rule nahi sikhaya. 50% = sikka uchhalna. Pakka tab jab purane aur naye dono hisse 60%+ (ya 40%-) ho.', style: small),
      ]),
    );
  }

  /// "AI ki galtiyan": every decision with a known outcome is RIGHT or WRONG, wrong ones keep their situation.
  Widget _scoreCard(AppPalette p, Map<String, dynamic> sc) {
    final mist = _l(sc['mistakes']);
    return _card(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'AI KI GALTIYAN'),
        if (_i(sc['n']) == 0)
          Text('Abhi kisi faisle ka nateeja nahi aaya. Bot ke trade band hone do.', style: TextStyle(fontSize: 13, color: p.textMuted))
        else ...[
          Text('${_i(sc['n'])} faisle: ${_i(sc['right'])} sahi, ${_i(sc['wrong'])} galat (${_n(sc['right_pct']).toStringAsFixed(0)}% sahi).',
              style: TextStyle(fontSize: 13, height: 1.35, color: p.textPrimary)),
          const SizedBox(height: 4),
          Text('SKIP/WAIT aur bot haara = sahi. SKIP/WAIT aur bot jeeta = galti. LE aur haara = galti.', style: TextStyle(fontSize: 11.5, height: 1.35, color: p.textMuted)),
          for (final raw in mist)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                  '${_m(raw)['sym']} ${_m(raw)['side'] == 'BUY' ? 'LONG' : 'SHORT'} | ${_m(raw)['call']} ${_usdt(_m(raw)['result'])} USDT'
                  '${(_m(raw)['situation'] ?? '').toString().isEmpty ? '' : ' | ${_m(raw)['situation']}'}',
                  style: TextStyle(fontSize: 12, height: 1.3, color: p.textPrimary)),
            ),
        ],
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.palette;
    final d = _d;
    if (d == null) {
      if (widget.embedded) {
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Text(_failed ? 'AI Desk did not load. Restart the backend and try again.' : 'Loading...', style: TextStyle(fontSize: 12, color: p.textMuted)),
        );
      }
      return Center(child: Text(_failed ? 'AI Desk load nahi hua. Backend restart karke dekho.' : 'Load ho raha hai...', style: TextStyle(color: p.textMuted)));
    }
    final calls = _m(d['calls']);
    final open = _l(d['open']);
    final recent = _l(d['recent']);
    final beyond = _m(d['beyond']);
    final skipped = _m(d['skipped']);
    final bot = _m(d['bot']);
    final ai = _m(d['ai']);
    final cmp = _m(d['compare']);
    final lr = _m(d['learned']);
    final lrGood = _l(lr['good']);
    final lrBad = _l(lr['bad']);
    final headColor = _i(cmp['n']) < 5 ? p.warning : (_n(cmp['diff']) >= 0 ? p.profit : p.loss);
    final headW = <Widget>[
          _card(
            p,
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('AI DESK', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.8, color: headColor)),
              const SizedBox(height: 6),
              Text((d['headline'] ?? '').toString(), style: TextStyle(fontSize: 15, height: 1.35, color: p.textPrimary, fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              Text('Entry dono ki same (EMA50 cross). Bot apna kaam karta hai, AI apna alag virtual khata chalata hai. Margin AI ka wahi jo bot ka.', style: TextStyle(fontSize: 11.5, height: 1.35, color: p.textMuted)),
            ]),
            edge: headColor,
          ),
    ];
    final studiesW = <Widget>[
      ..._observerCards(p),
      _levelCard(p),
    ];
    final restW = <Widget>[
      _scoreCard(p, _m(d['scorecard'])),
          _card(
            p,
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _title(p, 'BOT vs AI'),
              Row(children: [
                const Expanded(flex: 5, child: SizedBox()),
                Expanded(flex: 3, child: Text('BOT', textAlign: TextAlign.right, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textMuted))),
                Expanded(flex: 3, child: Text('AI', textAlign: TextAlign.right, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.accent))),
              ]),
              const Divider(height: 12),
              _row(p, 'Signal aaye', '${_i(d['signals'])}', '${_i(d['signals'])}'),
              _row(p, 'Trade li', '${_i(bot['traded'])}', '${_i(ai['traded'])}'),
              _row(p, 'Band ho chuki', '${_i(bot['closed'])}', '${_i(ai['closed'])}'),
              _row(p, 'Abhi khuli', '${_i(bot['open'])}', '${_i(ai['open'])}'),
              _row(p, 'Win', '${_i(bot['wins'])}', '${_i(ai['wins'])}'),
              _row(p, 'Loss', '${_i(bot['losses'])}', '${_i(ai['losses'])}'),
              _row(p, 'Win rate', '${_n(bot['wr']).toStringAsFixed(0)}%', '${_n(ai['wr']).toStringAsFixed(0)}%'),
              _row(p, 'Avg ROI', _pct(bot['avg']), _pct(ai['avg'])),
              const Divider(height: 12),
              _row(p, 'Kamaya / Gawaya (USDT)', _usdt(bot['pnl']), _usdt(ai['pnl']),
                  botColor: _roiColor(p, _n(bot['pnl'])), aiColor: _roiColor(p, _n(ai['pnl'])), bold: true),
              Text('Sirf band trades ka paisa. AI ke khule trades abhi ${_usdt(d['ai_open_pnl'])} USDT par.',
                  style: TextStyle(fontSize: 11, color: p.textMuted)),
            ]),
          ),
          _card(
            p,
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _title(p, 'FARAK KAHAN SE AAYA (${_i(cmp['n'])} band signal)'),
              _row(p, 'Bot ne in par', _usdt(cmp['bot']), '', botColor: _roiColor(p, _n(cmp['bot']))),
              _row(p, 'AI ne in par', '', _usdt(cmp['ai']), aiColor: _roiColor(p, _n(cmp['ai']))),
              const Divider(height: 12),
              _row(p, 'AI ka farak', '', _usdt(cmp['diff']), aiColor: _roiColor(p, _n(cmp['diff'])), bold: true),
              const SizedBox(height: 6),
              Text(
                  'Entry se: ${_usdt(cmp['entry_effect'])} USDT (AI ne ${_i(skipped['n'])} signal chhode, unpe bot ne ${_usdt(skipped['bot_pnl'])} kiya: ${_i(skipped['bot_wins'])} win, ${_i(skipped['bot_losses'])} loss).\n'
                  'Exit se: ${_usdt(cmp['exit_effect'])} USDT (jo trade AI ne li, unme apne exit se bot se kitna alag).',
                  style: TextStyle(fontSize: 12, height: 1.4, color: p.textMuted)),
              const SizedBox(height: 8),
              Row(children: [
                _chip(p, 'LE'), const SizedBox(width: 6), Text('${_i(calls['LE'])}', style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w700)),
                const SizedBox(width: 16),
                _chip(p, 'SKIP'), const SizedBox(width: 6), Text('${_i(calls['SKIP'])}', style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w700)),
                const SizedBox(width: 16),
                _chip(p, 'WAIT'), const SizedBox(width: 6), Text('${_i(calls['WAIT'])}', style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w700)),
              ]),
            ]),
          ),
          _card(
            p,
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _title(p, 'AI NE KYA SEEKHA'),
              Text((lr['msg'] ?? 'Abhi seekh raha hai.').toString(), style: TextStyle(fontSize: 13, height: 1.35, color: p.textPrimary)),
              const SizedBox(height: 4),
              Text('Dono indicator (price/SD band + Z-score/TSI) ki ${_i(lr['cells'])} situations dekhi, ${_i(lr['ready'])} me 30+ purane signal hain.',
                  style: TextStyle(fontSize: 11.5, height: 1.35, color: p.textMuted)),
              if (lrGood.isNotEmpty) ...[
                const SizedBox(height: 10),
                Text('LENE LAYAK', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.profit)),
                const SizedBox(height: 4),
                _learnRows(p, lrGood, p.profit),
              ],
              if (lrBad.isNotEmpty) ...[
                const SizedBox(height: 10),
                Text('CHHODNE LAYAK', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.loss)),
                const SizedBox(height: 4),
                _learnRows(p, lrBad, p.loss),
              ],
            ]),
          ),
          _card(
            p,
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _title(p, 'AI KE KHULE TRADE (${open.length})'),
              if (open.isEmpty) Text('Abhi AI ka koi trade khula nahi.', style: TextStyle(fontSize: 13, color: p.textMuted)),
              for (final o in open)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      Text('${o['sym']}  ${o['side'] == 'BUY' ? 'LONG' : 'SHORT'}', style: TextStyle(fontWeight: FontWeight.w800, color: p.textPrimary)),
                      const Spacer(),
                      Text(o['roi'] == null ? '--' : _pct(o['roi']), style: TextStyle(fontWeight: FontWeight.w800, color: o['roi'] == null ? p.textMuted : _roiColor(p, _n(o['roi'])))),
                    ]),
                    Text('${o['stage']}  |  target: ${_i(o['target']) >= 4 ? 'TP4 aur uske aage trail' : 'TP${_i(o['target'])} par band'}', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
                  ]),
                ),
            ]),
          ),
          _card(
            p,
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _title(p, 'TP4 KE AAGE HOLD'),
              Text((beyond['msg'] ?? '').toString(), style: TextStyle(fontSize: 13, height: 1.35, color: p.textPrimary)),
            ]),
          ),
          _card(
            p,
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _title(p, 'AI KE FAISLE (latest)'),
              if (recent.isEmpty) Text('Abhi koi naya signal nahi aaya.', style: TextStyle(fontSize: 13, color: p.textMuted)),
              for (final r in recent)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      Text(_hm(r['t']), style: TextStyle(fontSize: 11.5, color: p.textMuted)),
                      const SizedBox(width: 8),
                      Text('${r['sym']} ${r['side'] == 'BUY' ? 'LONG' : 'SHORT'}', style: TextStyle(fontWeight: FontWeight.w700, color: p.textPrimary)),
                      const SizedBox(width: 8),
                      _chip(p, (r['call'] ?? 'WAIT').toString()),
                      const Spacer(),
                      if (r['ai'] != null) Text('AI ${_usdt(r['ai'])}  ', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: _roiColor(p, _n(r['ai'])))),
                      if (r['bot'] != null) Text('bot ${_usdt(r['bot'])}', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: _roiColor(p, _n(r['bot'])))),
                    ]),
                    const SizedBox(height: 3),
                    Text((r['why'] ?? '').toString(), style: TextStyle(fontSize: 12, height: 1.35, color: p.textMuted)),
                  ]),
                ),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: Text(_l(d['caveats']).map((e) => '- $e').join('\n'), style: TextStyle(fontSize: 11, height: 1.4, color: p.textMuted)),
          ),
    ];
    final shown = widget.part == 'studies' ? studiesW : (widget.part == 'desk' ? [...headW, ...restW] : [...headW, ...studiesW, ...restW]);
    if (widget.embedded) return Column(crossAxisAlignment: CrossAxisAlignment.start, children: shown);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 90),
        children: shown,
      ),
    );
  }
}
