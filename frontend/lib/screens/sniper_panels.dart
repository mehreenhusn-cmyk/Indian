import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/equity_line.dart';
import '../widgets/owl_card.dart';

/// Part S6 (OwlSniper), part 1 of 2: the panels, all read-only, all fed by ONE answer of the Part S5 route /api/v2/sniper (file screens/sniper_screen.dart is part 2 of 2).
/// Panels: SniperBanner (Trending / Sideways word + one headline + 5 counts), SniperEquity (running net of the unseen TEST days, after fees), SniperFloor (is the 85% floor proven?),
/// SniperCards (order cards, newest first), SniperReport (the Insight Report lines). OwlSniper only WATCHES: nothing here sends an order or saves anything. Dart NOT compiled (the APK build is the proof).

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
double _d(Object? v) => v is num ? v.toDouble() : 0.0;
List<double> _pts(Object? v) => v is List ? [for (final e in v) _d(e)] : <double>[];
String _sg(Object? v) => '${_d(v) >= 0 ? '+' : ''}${_d(v).toStringAsFixed(2)}';
String _pct(Object? v) => '${(_d(v) * 100).toStringAsFixed(1)}%';
String _two(int n) => n < 10 ? '0$n' : '$n';

String _px(Object? v) {
  final x = _d(v);
  if (x >= 100) return x.toStringAsFixed(2);
  if (x >= 1) return x.toStringAsFixed(4);
  return x.toStringAsFixed(6);
}

String _utc(Object? t) {
  if (t is! num) return '';
  final d = DateTime.fromMillisecondsSinceEpoch(t.toInt() * 1000, isUtc: true);
  return '${_two(d.hour)}:${_two(d.minute)} UTC';
}

String _ago(Object? s) {
  if (s is! num) return 'not yet';
  final n = s.toInt();
  if (n < 90) return '${n}s ago';
  if (n < 5400) return '${(n / 60).round()} min ago';
  return '${(n / 3600).toStringAsFixed(1)} h ago';
}

Widget _stat(AppPalette p, String big, String label, [Color? c]) => Expanded(
      child: Column(children: [
        Text(big, style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: c ?? p.textPrimary)),
        const SizedBox(height: 2),
        Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
      ]),
    );

Widget _chip(String text, Color c) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
      child: Text(text, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: c)),
    );

/// Panel 1: the Trending / Sideways banner.
class SniperBanner extends StatelessWidget {
  final Map<String, dynamic> r;
  const SniperBanner({super.key, required this.r});

  String _word(String b) => b == 'TRENDING' ? 'TRENDING' : b == 'SIDEWAYS' ? 'SIDEWAYS' : b == 'MIXED' ? 'MIXED' : 'NOT CLEAR YET';

  String _sub(String b) {
    switch (b) {
      case 'TRENDING':
        return 'Most coins are trending. A trade can pass only when every check passes.';
      case 'SIDEWAYS':
        return 'Most coins are flat. Trades are blocked.';
      case 'MIXED':
        return 'Some coins trend and some are flat. Every coin is checked on its own.';
      default:
        return 'There is not enough fresh data to tell yet.';
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final b = '${r['banner'] ?? 'UNKNOWN'}';
    final c = b == 'TRENDING' ? p.profit : (b == 'UNKNOWN' ? p.textMuted : p.warning);
    final n = _m(r['counts']);
    final g = _m(r['regimes']);
    final pass = _d(n['SNIPER_LONG']) + _d(n['SNIPER_SHORT']);
    return OWLCard(
      edge: c,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('OwlSniper (watch only)', style: TextStyle(fontSize: 13, color: p.textSecondary))),
          _chip(_word(b), c),
        ]),
        const SizedBox(height: 8),
        Text('${r['headline'] ?? ''}', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: p.textPrimary)),
        const SizedBox(height: 4),
        Text(_sub(b), style: TextStyle(fontSize: 12, color: p.textSecondary)),
        const SizedBox(height: 10),
        Row(children: [
          _stat(p, '${r['coins_scanned'] ?? 0}', 'coins scanned'),
          _stat(p, '${(g['TRENDING'] ?? 0)}', 'trending', p.profit),
          _stat(p, '${_d(g['SIDEWAYS']).toInt() + _d(g['UNKNOWN']).toInt()}', 'sideways / unclear', p.warning),
          _stat(p, '${pass.toInt()}', 'pass all checks', pass > 0 ? p.profit : null),
          _stat(p, '${n['BLOCK_TRADE'] ?? 0}', 'blocked'),
        ]),
        const SizedBox(height: 8),
        Text(
          'Checked ${_ago(r['updated_ago_sec'])}  |  learned ${_ago(r['model_ago_sec'])}${r['refreshing'] == true ? '  |  working in the background...' : ''}${_d(r['stale_coins']) > 0 ? '  |  ${r['stale_coins']} coin(s) skipped, old candles' : ''}',
          style: TextStyle(fontSize: 11, color: p.textMuted),
        ),
      ]),
    );
  }
}

/// Panel 2: running net of the unseen TEST days (fees and slippage already counted).
class SniperEquity extends StatelessWidget {
  final Map<String, dynamic> r;
  const SniperEquity({super.key, required this.r});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final eq = _m(r['equity']);
    final all = _pts(eq['all']);
    final flo = _pts(eq['floor']);
    final fc = _m(r['floor_check']);
    final floorPct = (_d(r['floor']) * 100).toStringAsFixed(0);
    final noFloor = _d(fc['trades']) == 0 || flo.length < 2;
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Unseen test days (after fees)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 4),
        Text('Pretend trades of the settings that were learned on older days, run on newer days they never saw. ${eq['test_trades'] ?? 0} trades.',
            style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        const SizedBox(height: 10),
        if (all.length < 2)
          Text('Not enough test-day trades for a line yet.', style: TextStyle(fontSize: 12.5, color: p.textMuted))
        else ...[
          Row(children: [
            Expanded(child: Text('All signals that passed the sideways guard', style: TextStyle(fontSize: 12, color: p.textSecondary))),
            Text('${_sg(all.last)} USDT', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: all.last >= 0 ? p.profit : p.loss)),
          ]),
          const SizedBox(height: 6),
          EquityLine(values: all, line: p.accent, grid: p.border, height: 110),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: Text('Only signals with win chance $floorPct% or more', style: TextStyle(fontSize: 12, color: p.textSecondary))),
            if (!noFloor) Text('${_sg(flo.last)} USDT', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: flo.last >= 0 ? p.profit : p.loss)),
          ]),
          const SizedBox(height: 6),
          if (noFloor)
            Text('No signal reached the $floorPct% floor on the test days.', style: TextStyle(fontSize: 12.5, color: p.textMuted))
          else
            EquityLine(values: flo, line: p.profit, grid: p.border, height: 90),
        ],
      ]),
    );
  }
}

/// Panel 3: is the win-chance floor proven on the unseen days?
class SniperFloor extends StatelessWidget {
  final Map<String, dynamic> r;
  const SniperFloor({super.key, required this.r});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final fc = _m(r['floor_check']);
    final ok = r['floor_verified'] == true;
    final floorPct = (_d(r['floor']) * 100).toStringAsFixed(0);
    final n = _d(fc['trades']).toInt();
    return OWLCard(
      edge: ok ? p.profit : p.warning,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('$floorPct% win-chance floor', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary))),
          _chip(ok ? 'PROVEN' : 'NOT PROVEN', ok ? p.profit : p.warning),
        ]),
        const SizedBox(height: 6),
        Text(
          n == 0
              ? 'No signal was rated $floorPct% or more on the test days.'
              : '$n signals were rated $floorPct% or more on the test days. ${fc['wins']} won (${_pct(fc['win_rate'])}, it could be as low as ${_pct(fc['win_low95'])}). Net ${_sg(fc['net_usdt'])} USDT after fees.',
          style: TextStyle(fontSize: 12.5, color: p.textPrimary),
        ),
        const SizedBox(height: 4),
        Text(
          ok ? 'The floor held on days the model never saw, so signals of $floorPct% or more may pass.' : 'While the floor is not proven, no signal can pass. The floor is never lowered to make it pass.',
          style: TextStyle(fontSize: 11.5, color: p.textMuted),
        ),
      ]),
    );
  }
}

/// Panel 4: the order cards. Green = passes every check (watch only), amber = blocked, with the plain reason.
class SniperCards extends StatelessWidget {
  final Map<String, dynamic> r;
  final bool showAll;
  final VoidCallback onToggle;
  const SniperCards({super.key, required this.r, required this.showAll, required this.onToggle});

  Widget _card(AppPalette p, Map<String, dynamic> c) {
    final ok = c['action'] == 'SNIPER_LONG' || c['action'] == 'SNIPER_SHORT';
    final col = ok ? p.profit : p.warning;
    final side = '${c['side'] ?? ''}';
    return OWLCard(
      edge: col,
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${c['symbol'] ?? ''}', style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800, color: p.textPrimary))),
          _chip(ok ? 'PASSES  $side' : 'BLOCKED', col),
        ]),
        const SizedBox(height: 6),
        Text('${c['reason'] ?? ''}', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
        if (ok) ...[
          const SizedBox(height: 8),
          Row(children: [
            _stat(p, _px(c['entry_price']), 'entry'),
            _stat(p, _px(c['stop_loss']), 'stop', p.loss),
            _stat(p, _px(c['take_profit']), 'target', p.profit),
            _stat(p, c['confidence'] == null ? '-' : _pct(c['confidence']), 'win chance'),
          ]),
        ] else if (c['confidence'] != null) ...[
          const SizedBox(height: 4),
          Text('Win chance ${_pct(c['confidence'])}', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        ],
        const SizedBox(height: 4),
        Text('Candle ${_utc(c['t'])}  |  market ${c['regime'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final all = _l(r['cards']);
    final shown = showAll || all.length <= 8 ? all : all.sublist(0, 8);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.only(left: 2, bottom: 6),
        child: Text('Order cards (newest first)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
      ),
      if (all.isEmpty)
        OWLCard(child: Text('No signal has appeared yet. A card shows up here when a coin crosses and the checks either pass or block it.', style: TextStyle(fontSize: 12.5, color: p.textMuted)))
      else
        for (final c in shown) Padding(padding: const EdgeInsets.only(bottom: 8), child: _card(p, c)),
      if (all.length > 8)
        TextButton(onPressed: onToggle, child: Text(showAll ? 'Show fewer' : 'Show all ${all.length} cards')),
    ]);
  }
}

/// Panel 5: the Insight Report, plain lines (what was tested, what was learned, what is proven).
class SniperReport extends StatelessWidget {
  final Map<String, dynamic> r;
  const SniperReport({super.key, required this.r});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final lines = r['lines'] is List ? [for (final e in r['lines'] as List) '$e'] : <String>[];
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Insight report', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 6),
        if (lines.isEmpty)
          Text('The first report is written after OwlSniper has learned from the saved candles.', style: TextStyle(fontSize: 12.5, color: p.textMuted))
        else
          for (final t in lines)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('\u2022  ', style: TextStyle(fontSize: 12.5, color: p.textMuted)),
                Expanded(child: Text(t, style: TextStyle(fontSize: 12.5, color: p.textPrimary))),
              ]),
            ),
      ]),
    );
  }
}
