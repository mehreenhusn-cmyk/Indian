import 'dart:async';
import 'package:flutter/material.dart';
import '../utils/format.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'ai_recipe_card.dart';

/// The simple AI "Insights" screen. ONE question: "If the bot also reads BOTH indicators
/// (TSI + Z-score / SD bands), does profit go up - and is it safe to believe it yet?"
/// Everything comes from the backend (ai_ab_board.py -> 'insight' inside GET /api/ai/ab_board).
/// Nothing is calculated or guessed on the phone, and nothing here opens, blocks or closes a trade.
/// Order: verdict (3 lines) -> why (max 3 measured scenarios) -> price-vs-Z table -> safe-to-upgrade
/// checklist -> rollout stage (suggestion only) -> small word list.
class AiVerdictCard extends StatefulWidget {
  /// Opens the detailed A/B tab (optional).
  final VoidCallback? onOpenAb;
  final TabController? tabs; // when given, the 60 s refresh only runs while this tab is the visible one
  final int tabIndex;
  const AiVerdictCard({super.key, this.onOpenAb, this.tabs, this.tabIndex = 0});

  @override
  State<AiVerdictCard> createState() => _AiVerdictCardState();
}

class _AiVerdictCardState extends State<AiVerdictCard> with AutomaticKeepAliveClientMixin {
  static const _kTfs = ['3m', '5m', '15m'];

  /// Last good answer of EACH timeframe. A chip can only ever show its own timeframe's numbers.
  final Map<String, Map<String, dynamic>> _byTf = {};
  bool _building = false; // the backend is busy calculating this timeframe
  bool _loading = false; // a request is on its way
  bool _cmpBusy = false; // "Load all 3 timeframes" is running
  String? _error; // plain-English reason when the numbers could not load
  String _tf = ''; // '' until the backend tells us the bot's own timeframe
  Timer? _timer;
  Timer? _retry;

  Map<String, dynamic>? get _d => _byTf[_tf];

  @override
  bool get wantKeepAlive => true; // tab switch keeps the screen alive: no rebuild, no reload

  static bool _usable(Map<String, dynamic>? r, String tf) =>
      r != null && (r['tf'] ?? '').toString() == tf && r['building'] != true && r['error'] == null && r['insight'] != null;

  @override
  void initState() {
    super.initState();
    final prov = context.read<AppProvider>();
    for (final t in _kTfs) {
      final c = prov.peekAi('/api/ai/ab_board', t);
      if (_usable(c, t)) _byTf[t] = c!; // old numbers at once, fresh ones arrive behind them
    }
    final latest = prov.peekAi('/api/ai/ab_board');
    final lt = (latest?['tf'] ?? '').toString();
    if (_usable(latest, lt)) {
      _byTf.putIfAbsent(lt, () => latest!);
      _tf = lt;
    }
    _load();
    _timer = Timer.periodic(const Duration(seconds: 120), (_) {
      if (widget.tabs != null && widget.tabs!.index != widget.tabIndex) return;
      _load();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _retry?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final asked = _tf;
    if (!mounted) return;
    _loading = true; // no setState here: _load also runs from initState, the next rebuild picks it up
    final prov = context.read<AppProvider>();
    final r = await prov.fetchAiAbBoard(tf: asked);
    if (!mounted) return;
    var again = false;
    setState(() {
      _loading = false;
      if (r == null) {
        if (asked == _tf) {
          _building = false;
          _error = prov.aiLastError ?? 'The backend did not answer.';
        }
        return;
      }
      final got = (r['tf'] ?? '').toString();
      // An answer for another timeframe than the one asked is never shown.
      if (asked.isNotEmpty && got != asked) return;
      if (asked.isEmpty && _tf.isEmpty && got.isNotEmpty) _tf = got;
      if (_usable(r, got)) _byTf[got] = r; // always keep a good answer under ITS OWN timeframe
      if (asked != _tf && asked.isNotEmpty) return; // user already tapped another chip: do not touch its flags
      if (r['error'] != null) {
        _building = false;
        _error = 'The backend could not calculate $got: ${r['error']}';
      } else if (r['building'] == true) {
        _building = true;
        _error = null;
        again = true;
      } else {
        _building = false;
        _error = null;
      }
    });
    if (again) {
      _retry?.cancel();
      _retry = Timer(const Duration(seconds: 6), () {
        if (mounted) _load();
      });
    }
  }

  /// Fills the comparison table: asks the backend for each timeframe one after the other (it builds one at a time).
  Future<void> _loadAll() async {
    if (_cmpBusy) return;
    setState(() => _cmpBusy = true);
    final prov = context.read<AppProvider>();
    for (final t in _kTfs) {
      for (var i = 0; i < 8 && mounted; i++) {
        final r = await prov.fetchAiAbBoard(tf: t);
        if (!mounted) return;
        if (_usable(r, t)) {
          setState(() => _byTf[t] = r!);
          break;
        }
        await Future.delayed(const Duration(seconds: 6));
      }
    }
    if (mounted) setState(() => _cmpBusy = false);
  }

  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _l(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];

  /// "5 min ago" from a millisecond timestamp.
  static String _ago(dynamic ms) {
    if (ms is! num) return 'a while ago';
    final s = ((DateTime.now().millisecondsSinceEpoch - ms.toInt()) / 1000).round();
    return '${fmtSpan(s)} ago';
  }

  Color _statusColor(AppPalette p, String s) => s == 'READY' ? p.profit : (s == 'NO' ? p.loss : p.warning);

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

  Widget _title(BuildContext context, String t, {String? sub}) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: context.type.section.copyWith(fontSize: 13)),
          if (sub != null) Text(sub, style: context.type.metadata),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.palette;
    final d = _d;
    final ins = d == null ? <String, dynamic>{} : _m(d['insight']);
    return ListView(
      padding: const EdgeInsets.fromLTRB(AppSpacing.m, AppSpacing.s, AppSpacing.m, 96),
      children: [
        _title(context, 'Filter test',
            sub: 'One question: if the bot also read TSI and Z-score, would profit grow, and is it safe to trust that yet?'),
        _tfRow(context, p, d),
        const SizedBox(height: 10),
        if (d == null)
          _waiting(context, p)
        else if (ins.isEmpty)
          _box(p,
              border: p.warning,
              child: Text(
                  'The $_tf answer arrived without its insight part (the backend has not finished it). The app asks again in a minute.',
                  style: context.type.secondary))
        else ...[
          AiRecipeCard(tf: _tf),
          const SizedBox(height: 10),
          _verdict(context, p, ins),
          const SizedBox(height: 10),
          _why(context, p, ins),
          _relation(context, p, ins),
          _checklist(context, p, ins),
          const SizedBox(height: 10),
          _compare(context, p),
          const SizedBox(height: 10),
          _stage(context, p, ins),
          const SizedBox(height: 10),
          _words(context, p),
        ],
      ],
    );
  }

  /// What to show while the chosen timeframe has no numbers yet. Always says WHY.
  Widget _waiting(BuildContext context, AppPalette p) {
    final String title;
    final String body;
    Color? edge;
    if (_error != null) {
      title = 'Could not load ${_tf.isEmpty ? 'the numbers' : '$_tf numbers'}';
      body = '$_error\n\nTap the refresh icon to try again. If it keeps failing, open http://localhost:8000/api/ai/health in the phone browser and send me what it shows.';
      edge = p.loss;
    } else if (_building) {
      title = 'Calculating $_tf numbers...';
      body = 'The backend can build only one timeframe at a time and the phone is busy. This one is next. The app asks again every 6 seconds, nothing is lost.';
      edge = p.warning;
    } else {
      title = 'Loading ${_tf.isEmpty ? 'numbers' : '$_tf numbers'}...';
      body = 'Asking the backend. The first load can take up to 40 seconds on the phone.';
    }
    return _box(p,
        border: edge,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: context.type.section.copyWith(fontSize: 14, color: edge)),
          const SizedBox(height: 6),
          Text(body, style: context.type.secondary),
          if (_loading || _building) ...[
            const SizedBox(height: 10),
            const LinearProgressIndicator(minHeight: 3),
          ],
        ]));
  }

  Widget _tfRow(BuildContext context, AppPalette p, Map<String, dynamic>? d) {
    final shown = d == null
        ? (_tf.isEmpty ? 'Waiting for numbers...' : 'Waiting for $_tf numbers...')
        : 'Showing: $_tf  |  calculated ${_ago(d['now_ms'])}';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        for (final t in _kTfs)
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: ChoiceChip(
              label: Text(t),
              selected: _tf == t,
              onSelected: (_) {
                _retry?.cancel();
                setState(() {
                  _tf = t; // the screen switches to THIS timeframe's own numbers (or "Loading $t..."), never the old ones
                  _building = false;
                  _error = null;
                });
                _load();
              },
            ),
          ),
        const Spacer(),
        IconButton(
            onPressed: _loading ? null : _load,
            icon: Icon(Icons.refresh_rounded, size: 18, color: p.textMuted),
            visualDensity: VisualDensity.compact),
      ]),
      Text(shown, style: context.type.metadata),
      if (d != null && _error != null)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text('Refresh failed: $_error. These are the last good $_tf numbers.',
              style: context.type.metadata.copyWith(color: p.loss, fontWeight: FontWeight.w700)),
        ),
      if (d != null && _building)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text('Backend is busy, showing the last finished $_tf numbers. Asking again every 6 seconds.',
              style: context.type.metadata.copyWith(color: p.warning)),
        ),
    ]);
  }

  /// 3m / 5m / 15m side by side, from the same measured numbers (nothing new is calculated on the phone).
  Widget _compare(BuildContext context, AppPalette p) {
    final rows = <Widget>[];
    String? bestTf;
    double bestNet = -1e9;
    final st = context.type.metadata;
    Widget cell(String t, int flex, {TextAlign a = TextAlign.right, Color? c, bool bold = false}) => Expanded(
        flex: flex,
        child: Text(t, textAlign: a, style: st.copyWith(color: c, fontWeight: bold ? FontWeight.w800 : null)));
    for (final t in _kTfs) {
      final d = _byTf[t];
      final ins = d == null ? <String, dynamic>{} : _m(d['insight']);
      final cand = _m(ins['candidate']);
      final status = (ins['status'] ?? '').toString();
      if (cand.isNotEmpty && _n(cand['net']) > bestNet) {
        bestNet = _n(cand['net']);
        bestTf = t;
      }
      String pct(dynamic v) => '${_n(v) >= 0 ? '+' : ''}${_n(v).toStringAsFixed(0)}%';
      rows.add(Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          cell(t, 2, a: TextAlign.left, bold: true, c: p.textPrimary),
          cell(d == null ? '-' : '${_i(d['signals'])}', 3),
          cell(cand.isEmpty ? '-' : pct(cand['bot_net']), 3),
          cell(cand.isEmpty ? '-' : pct(cand['net']), 3, c: cand.isEmpty ? null : (_n(cand['net']) >= _n(cand['bot_net']) ? p.profit : p.loss)),
          cell(d == null ? 'not loaded' : (status == 'READY' ? 'ready' : (status == 'NO' ? 'no' : 'more data')), 3,
              c: d == null ? p.textMuted : _statusColor(p, status), bold: true),
        ]),
      ));
    }
    final loaded = _kTfs.where(_byTf.containsKey).length;
    return _box(p, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _title(context, 'WHICH TIMEFRAME IS BEST? (3m / 5m / 15m)',
          sub: 'Same replay, same fee. "Bot" = EMA50 cross alone. "Filter" = the best TSI / Z-score rule found.'),
      Row(children: [
        cell('TF', 2, a: TextAlign.left),
        cell('Signals', 3),
        cell('Bot', 3),
        cell('Filter', 3),
        cell('Verdict', 3),
      ]),
      const Divider(height: 10),
      ...rows,
      const SizedBox(height: 6),
      if (bestTf != null && loaded >= 2)
        Text('Highest filter result so far: $bestTf. This only counts when its checklist is fully green.', style: context.type.secondary)
      else
        Text('Load the other timeframes to compare them.', style: context.type.secondary),
      const SizedBox(height: 6),
      OutlinedButton(
        onPressed: _cmpBusy ? null : _loadAll,
        child: Text(_cmpBusy ? 'Loading timeframes (one by one)...' : (loaded >= 3 ? 'Refresh all 3 timeframes' : 'Load all 3 timeframes')),
      ),
    ]));
  }

  Widget _verdict(BuildContext context, AppPalette p, Map<String, dynamic> ins) {
    final st = (ins['status'] ?? 'MORE_DATA').toString();
    final c = _statusColor(p, st);
    final lines = (ins['lines'] is List) ? (ins['lines'] as List).map((e) => e.toString()).toList() : <String>[];
    final fin = (ins['final'] ?? 'Abhi aur data chahiye - filter live me mat lagao.').toString();
    final src = (ins['source'] ?? '').toString();
    return _box(p, border: c, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(color: c.withOpacity(0.16), borderRadius: BorderRadius.circular(6)),
          child: Text(st == 'READY' ? 'HARA' : (st == 'NO' ? 'LAAL' : 'PEELA'),
              style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: c)),
        ),
        const SizedBox(width: 8),
        Expanded(child: Text('Kya dono indicator se profit badhega?', style: context.type.section.copyWith(fontSize: 13))),
      ]),
      const SizedBox(height: 10),
      for (final t in lines)
        Padding(padding: const EdgeInsets.only(bottom: 6), child: Text(t, style: context.type.primary.copyWith(fontSize: 14))),
      const SizedBox(height: 4),
      Text(fin, style: context.type.primary.copyWith(fontSize: 13, fontWeight: FontWeight.w800, color: c)),
      const SizedBox(height: 6),
      Text(
        '${_i(ins['new_signals'])} naye signals, ${_n(ins['days']).toStringAsFixed(1)} din'
        '${src == 'history' ? '  |  abhi purane data ka check dikh raha hai' : ''}'
        '  |  ye sirf data ka hisaab hai, profit ki guarantee nahi.',
        style: context.type.metadata,
      ),
      if (widget.onOpenAb != null)
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(onPressed: widget.onOpenAb, child: const Text('Poora A/B scoreboard dekho')),
        ),
    ]));
  }

  Widget _why(BuildContext context, AppPalette p, Map<String, dynamic> ins) {
    final ky = _l(ins['kyun']);
    if (ky.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: _box(p, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(context, 'KYUN (AI ne ye scenarios skip karne layak paaye)', sub: 'sirf napi hui numbers, andaza nahi'),
        for (final k in ky)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('SKIP: ${k['label']}', style: context.type.primary.copyWith(fontSize: 12, fontWeight: FontWeight.w700, color: p.purple)),
              Text((k['why'] ?? '').toString(), style: context.type.metadata),
            ]),
          ),
      ])),
    );
  }

  Widget _relation(BuildContext context, AppPalette p, Map<String, dynamic> ins) {
    final rows = _l(ins['relation']);
    if (rows.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: _box(p, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(context, 'Price vs Z-score aur TSI', sub: 'WITH = trade ki disha me, AGAINST = ulta (3 candle)'),
        for (final r in rows)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${r['price_z']}  +  ${r['tsi']}', style: context.type.primary.copyWith(fontSize: 12, fontWeight: FontWeight.w700)),
              Text('${_i(r['n'])} signals  |  avg ${_n(r['avg']).toStringAsFixed(2)}%  |  win ${_n(r['win_rate']).toStringAsFixed(0)}%',
                  style: context.type.metadata.copyWith(color: _n(r['avg']) >= 0 ? p.profit : p.loss)),
            ]),
          ),
      ])),
    );
  }

  Widget _checklist(BuildContext context, AppPalette p, Map<String, dynamic> ins) {
    final cs = _l(ins['checks']);
    return _box(p, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _title(context, 'SAFE-TO-UPGRADE CHECKLIST',
          sub: '${_i(ins['ticks'])}/${cs.length} pass  |  bharosa: ${(ins['trust'] ?? 'KAM')}'),
      for (final c in cs)
        Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(c['ok'] == true ? Icons.check_circle_rounded : Icons.cancel_rounded,
                size: 16, color: c['ok'] == true ? p.profit : p.loss),
            const SizedBox(width: 8),
            Expanded(child: Text((c['t'] ?? '').toString(), style: context.type.secondary)),
          ]),
        ),
      const SizedBox(height: 4),
      Text('Jab tak saare tick hare na hon, filter live me mat lagana.', style: context.type.metadata),
    ]));
  }

  Widget _stage(BuildContext context, AppPalette p, Map<String, dynamic> ins) {
    final st = _m(ins['stage']);
    final names = (st['names'] is List) ? (st['names'] as List).map((e) => e.toString()).toList() : <String>[];
    final allowed = _i(st['allowed']);
    return _box(p, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _title(context, 'ROLLOUT PLAN (sirf suggestion, kuch automatic nahi)'),
      for (var i = 0; i < names.length; i++)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text(names[i],
              style: context.type.secondary.copyWith(
                  fontWeight: i + 1 == allowed ? FontWeight.w800 : FontWeight.w400,
                  color: i + 1 <= allowed ? null : p.textMuted)),
        ),
      Text('Data abhi Stage $allowed tak support karta hai. Agla stage tabhi jab checklist poora hara ho.',
          style: context.type.metadata),
    ]));
  }

  Widget _words(BuildContext context, AppPalette p) => _box(p, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(context, 'Chhote matlab'),
        for (final t in const [
          'ROI: trade pe % kamai ya nuksaan (fee ke baad).',
          'Drawdown: profit ke baad sabse bada giraav.',
          'Skip: jo trade filter ne nahi liya.',
          'Luck chance: ye result sirf kismat se aane ka chance.',
        ])
          Padding(padding: const EdgeInsets.only(bottom: 3), child: Text(t, style: context.type.metadata)),
      ]));
}

/// Full-screen wrapper (used by the Dashboard "AI Insights" card).
class AiVerdictPage extends StatelessWidget {
  const AiVerdictPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('AI Insights')),
      body: const SafeArea(child: AiVerdictCard()),
    );
  }
}
