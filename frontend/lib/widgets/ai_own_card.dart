import 'dart:async';
import 'package:flutter/material.dart';
import '../utils/format.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'free_trade_chart.dart';

/// Bot vs AI tab, under "AI Pick": "AI OWN SIGNALS (SHADOW)".
///
/// Round B. The AI looks for its OWN signals on closed candles, using only situations it has proven (see AI Pick).
/// Nothing is traded: a signal is written down and later candles decide how it ended. This card starts by itself
/// once the AI Pick has collected data for a day and proven something. Until then it only says what it is waiting for.
///
/// Everything comes from GET /api/ai/selfsignal (backend ai_selfsignal.py). All text is plain English.
class AiOwnCard extends StatefulWidget {
  final TabController? tabs; // when given, loading / refreshing only happens while this tab is the open one
  final int tabIndex;
  const AiOwnCard({super.key, this.tabs, this.tabIndex = 0});

  @override
  State<AiOwnCard> createState() => _AiOwnCardState();
}

class _AiOwnCardState extends State<AiOwnCard> {
  Map<String, dynamic>? _o;
  bool _loading = false;
  String? _error;
  Timer? _timer;

  bool get _isVisibleTab => widget.tabs == null || widget.tabs!.index == widget.tabIndex;

  @override
  void initState() {
    super.initState();
    _o = context.read<AppProvider>().peekAi('/api/ai/selfsignal');
    Future.delayed(const Duration(milliseconds: 1200), () {
      if (mounted && _isVisibleTab) _load();
    });
    _timer = Timer.periodic(const Duration(seconds: 120), (_) {
      if (_isVisibleTab) _load();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_loading || !mounted) return;
    _loading = true;
    final prov = context.read<AppProvider>();
    final r = await prov.fetchAiSelfSignal();
    if (!mounted) return;
    setState(() {
      _loading = false;
      if (r != null) {
        _o = r;
        _error = null;
      } else {
        _error = prov.aiLastError ?? 'The backend did not answer.';
      }
    });
  }

  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _l(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
  static String _s(double v, {int d = 2}) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}';
  static String _pf(dynamic v) => v is num ? v.toStringAsFixed(2) : 'n/a';

  Widget _box(AppPalette p, Widget child, {Color? edge}) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: p.surfaceElevated,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
          border: Border.all(color: (edge ?? p.border).withOpacity(0.7), width: 0.8),
        ),
        child: child,
      );

  Widget _head(BuildContext context, String t, {String? sub}) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: context.type.section.copyWith(fontSize: 13)),
          if (sub != null) Text(sub, style: context.type.metadata),
        ]),
      );

  Widget _statRow(BuildContext context, AppPalette p, String who, Map<String, dynamic> s, Color c) => Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: Row(children: [
          SizedBox(width: 92, child: Text(who, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: c))),
          Expanded(
            child: Text(
                '${_i(s['n'])} signals  ·  win ${_n(s['wr']).toStringAsFixed(0)}%  ·  avg ${_s(_n(s['avg']))}%  ·  profit factor ${_pf(s['pf'])}',
                style: context.type.secondary.copyWith(fontSize: 12)),
          ),
        ]),
      );

  static String _px(double v) {
    final a = v.abs();
    return v.toStringAsFixed(a >= 100 ? 2 : (a >= 1 ? 4 : (a >= 0.01 ? 5 : 7)));
  }

  Widget _liveLine(BuildContext context, Map<String, dynamic> r) => Padding(
        padding: const EdgeInsets.only(bottom: 5),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${r['sym']}  ${r['side'] == 'BUY' ? 'LONG' : 'SHORT'}  ·  ${fmtMins(r['age_min'])}', style: context.type.secondary.copyWith(fontSize: 12, fontWeight: FontWeight.w700)),
          Text((r['why'] ?? '').toString(), style: context.type.metadata),
        ]),
      );

  /// One open free trade: a tap on the chevron opens entry / stop / now and a small chart. Collapsed it is one line,
  /// so many open trades never need a long scroll.
  /// The "money" block of the answer (margin per trade, leverage). Used to show the chart result in USDT.
  Map<String, dynamic> get _moneyMap =>
      (_o != null && _o!['money'] is Map) ? Map<String, dynamic>.from(_o!['money'] as Map) : <String, dynamic>{};

  Widget _liveTile(BuildContext context, AppPalette p, Map<String, dynamic> r) {
    final long = r['side'] == 'BUY';
    final pnl = _n(r['pnl']);
    final entry = _n(r['entry']);
    final sl = _n(r['sl']);
    final now = _n(r['now']);
    final candles = (r['chart'] is List) ? (r['chart'] as List).whereType<List>().map((e) => e.map((x) => (x is num) ? x.toDouble() : 0.0).toList()).toList() : <List<double>>[];
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.only(bottom: 8),
        dense: true,
        title: Row(children: [
          Expanded(
              child: Text('${r['sym']}  ${long ? 'LONG' : 'SHORT'}  ·  ${fmtMins(r['age_min'])}',
                  style: context.type.secondary.copyWith(fontSize: 12, fontWeight: FontWeight.w700))),
          Text('${_s(pnl, d: 1)}%', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: pnl >= 0 ? p.profit : p.loss)),
        ]),
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Entry ${_px(entry)}   ·   Stop ${_px(sl)}   ·   Now ${_px(now)}', style: context.type.secondary.copyWith(fontSize: 12, fontWeight: FontWeight.w700)),
              if (_n(r['sl0']) != 0 && _n(r['sl0']) != sl)
                Text('Stop moved by the AI (first stop ${_px(_n(r['sl0']))})', style: context.type.metadata),
              const SizedBox(height: 4),
              Text((r['why'] ?? '').toString(), style: context.type.metadata),
              if (r['k'] != null)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: OutlinedButton.icon(
                    onPressed: () => showFreeTradeChart(context, row: Map<String, dynamic>.from(r), money: _moneyMap),
                    icon: const Icon(Icons.show_chart_rounded, size: 16),
                    label: const Text('Open full chart (stop moves)'),
                  ),
                ),
              if (candles.length > 3) ...[
                const SizedBox(height: 6),
                SizedBox(
                  height: 120,
                  width: double.infinity,
                  child: CustomPaint(painter: _MiniChartPainter(candles, entry, sl, long, p.profit, p.loss, p.textMuted)),
                ),
                Text('Blue line = entry, red line = stop. Last ${candles.length} candles.', style: context.type.metadata),
              ] else
                Text('Chart appears after the next candle check.', style: context.type.metadata),
            ]),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final o = _o;
    final explore = o != null && o['explore'] == true;
    final free = o != null && o['free'] == true;
    final title = free ? 'AI FREE TRADES (PAPER)' : (explore ? 'AI OWN TRADES (PAPER)' : 'AI OWN SIGNALS (SHADOW)');
    final sub = free
        ? 'No fixed rules. The AI reads Z-score, TSI, SD bands and EMA itself: own entry, own stop, own exit, own flip. It learns from every trade. Paper only.'
        : explore
        ? 'The AI reads the indicators itself and enters on its own, at any time. Paper only: no real money.'
        : 'The AI looks for its own signals using only situations it has proven. Nothing is traded.';
    if (o == null) {
      return _box(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _head(context, title, sub: sub),
          if (_error != null) ...[
            Text(_error!, style: context.type.secondary.copyWith(color: p.loss)),
            const SizedBox(height: 8),
            OutlinedButton(onPressed: _load, child: const Text('Retry')),
          ] else
            Text('Loading...', style: context.type.secondary),
        ]),
      );
    }
    if (o['error'] != null) {
      return _box(p, Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(context, title),
        Text('The backend could not build this: ${o['error']}', style: context.type.secondary.copyWith(color: p.loss)),
      ]), edge: p.loss);
    }
    if (o['enabled'] == false) {
      return _box(p, Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(context, title),
        Text('Switched off (setting selfsignal_enabled).', style: context.type.secondary),
      ]));
    }
    if (o['gate_open'] != true) {
      return _box(p, Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(context, title, sub: sub),
        Text((o['gate_why'] ?? 'Waiting.').toString(), style: context.type.secondary),
        const SizedBox(height: 6),
        Text('It starts by itself. You do not have to do anything.', style: context.type.metadata),
      ]));
    }
    final mine = _m(o['mine']);
    final bot = _m(o['bot']);
    final recent = _l(o['recent']).take(10).toList();
    final err = o['last_error'];
    return _box(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(context, title, sub: sub),
        _statRow(context, p, 'AI own', mine, p.purple),
        _statRow(context, p, 'Bot', bot, p.textMuted),
        const SizedBox(height: 6),
        Text((o['verdict'] ?? '').toString(), style: TextStyle(fontSize: 13, height: 1.4, fontWeight: FontWeight.w700, color: p.textPrimary)),
        const SizedBox(height: 6),
        Text('${_i(o['open'])} own signal(s) still running  ·  ${(o['gate_why'] ?? '').toString()}', style: context.type.metadata),
        if (_l(o['live']).isNotEmpty) ...[
          const SizedBox(height: 10),
          Text('AI is in these right now (${_l(o['live']).length})', style: context.type.section.copyWith(fontSize: 12)),
          const SizedBox(height: 4),
          for (final r in _l(o['live']).take(free ? 40 : 5)) free ? _liveTile(context, p, r) : _liveLine(context, r),
        ],
        if (free && _m(o['learned']).isNotEmpty) ...[
          const SizedBox(height: 10),
          Text('What the AI has learned so far', style: context.type.section.copyWith(fontSize: 12)),
          const SizedBox(height: 2),
          Text('${_i(_m(o['learned'])['buckets'])} readings seen  ·  ${_i(_m(o['learned'])['trusted'])} with 5+ trades', style: context.type.metadata),
          for (final r in _l(_m(o['learned'])['best']).take(3))
            Text('Works: ${r['read']}  (${_s(_n(r['avg']))}% avg, ${_i(r['n'])} trades)', style: context.type.metadata.copyWith(color: p.profit)),
          for (final r in _l(_m(o['learned'])['worst']).take(3))
            Text('Loses: ${r['read']}  (${_s(_n(r['avg']))}% avg, ${_i(r['n'])} trades)', style: context.type.metadata.copyWith(color: p.loss)),
        ],
        if (recent.isNotEmpty) ...[
          const SizedBox(height: 10),
          Text(free ? 'Latest finished (tap for chart)' : 'Latest finished', style: context.type.section.copyWith(fontSize: 12)),
          const SizedBox(height: 4),
          for (final r in recent)
            InkWell(
              onTap: r['k'] == null
                  ? null
                  : () => showFreeTradeChart(context, row: Map<String, dynamic>.from(r as Map), money: _moneyMap),
              child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(children: [
                Expanded(child: Text('${r['sym']}  ${r['side'] == 'BUY' ? 'LONG' : 'SHORT'}  ·  ${r['how']}', style: context.type.secondary.copyWith(fontSize: 12))),
                Text('${_s(_n(r['roi']))}%', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: _n(r['roi']) >= 0 ? p.profit : p.loss)),
              ]),
            )),
        ],
        if (err != null) ...[
          const SizedBox(height: 6),
          Text('Last problem: $err', style: context.type.metadata.copyWith(color: p.loss)),
        ],
      ]),
    );
  }
}

class _MiniChartPainter extends CustomPainter {
  final List<List<double>> c; // [open, high, low, close]
  final double entry, sl;
  final bool long;
  final Color up, down, muted;
  _MiniChartPainter(this.c, this.entry, this.sl, this.long, this.up, this.down, this.muted);

  @override
  void paint(Canvas canvas, Size size) {
    if (c.isEmpty) return;
    double hi = entry > sl ? entry : sl, lo = entry < sl ? entry : sl;
    for (final k in c) {
      if (k.length < 4) continue;
      if (k[1] > hi) hi = k[1];
      if (k[2] < lo) lo = k[2];
    }
    final pad = (hi - lo) * 0.06;
    hi += pad;
    lo -= pad;
    final rng = (hi - lo) <= 0 ? 1.0 : (hi - lo);
    double y(double v) => size.height - (v - lo) / rng * size.height;
    final w = size.width / c.length;
    for (var i = 0; i < c.length; i++) {
      final k = c[i];
      if (k.length < 4) continue;
      final col = k[3] >= k[0] ? up : down;
      final x = i * w + w / 2;
      canvas.drawLine(Offset(x, y(k[1])), Offset(x, y(k[2])), Paint()..color = col..strokeWidth = 1);
      final top = y(k[3] >= k[0] ? k[3] : k[0]);
      final bot = y(k[3] >= k[0] ? k[0] : k[3]);
      canvas.drawRect(Rect.fromLTRB(x - w * 0.32, top, x + w * 0.32, bot < top + 1 ? top + 1 : bot), Paint()..color = col);
    }
    void line(double v, Color col) {
      final yy = y(v);
      final path = Path();
      for (double x = 0; x < size.width; x += 8) {
        path.moveTo(x, yy);
        path.lineTo(x + 4, yy);
      }
      canvas.drawPath(path, Paint()..color = col..strokeWidth = 1.4..style = PaintingStyle.stroke);
    }
    line(entry, const Color(0xFF2F6BFF));
    line(sl, const Color(0xFFE53935));
  }

  @override
  bool shouldRepaint(covariant _MiniChartPainter o) => o.c.length != c.length || o.entry != entry || o.sl != sl || (c.isNotEmpty && o.c.isNotEmpty && o.c.last[3] != c.last[3]);
}
