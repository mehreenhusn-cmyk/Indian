import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Round 25 (OwlSniper, the three PILLARS, read-only). Fed by ONE answer of GET /api/v2/sniper (fetchSniper). Wired into the Sniper tab in Round 27.
///   Pillar A  SniperCapitalShield     the 10 USDT base, fee + slippage per side, the cost of a round trip, the widest stop allowed, the worst loss of one trade, and the net of the unseen TEST days
///   Pillar B  SniperVolatilityGuard   one big regime banner (TRENDING SAFE / SIDEWAYS blocked / MIXED / NOT CLEAR YET) + how many coins are in each state
///   Pillar C  SniperInsightConsole    a dark console: "Lookback Length = X | Z-Score = Y | Win Probability = Z %" for the newest order cards
///   SniperPillars                     the three in one column (what the screen uses)
/// Every number comes from the backend answer (engine constants, saved model, saved cards). A missing number prints "--", never "null" or "None". Old backends without the new keys still draw.
/// OwlSniper only WATCHES: nothing here sends an order, saves or switches anything. Dart NOT compiled (the APK build is the proof).

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
double? _n(Object? v) => v is num ? v.toDouble() : null;
String _f(double? v, int dec, [String unit = '']) => v == null ? '--' : '${v.toStringAsFixed(dec)}$unit';
String _sg(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';

Widget _stat(AppPalette p, String big, String label, [Color? c]) => Expanded(
      child: Column(children: [
        Text(big, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: c ?? p.textPrimary)),
        const SizedBox(height: 2),
        Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
      ]),
    );

Widget _chip(String text, Color c) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
      child: Text(text, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: c)),
    );

Widget _title(AppPalette p, String pillar, String name, Widget trailing) => Row(children: [
      Expanded(
        child: Text.rich(TextSpan(children: [
          TextSpan(text: '$pillar  ', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: p.textMuted)),
          TextSpan(text: name, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary)),
        ])),
      ),
      trailing,
    ]);

/// Pillar A: Capital Shield.
class SniperCapitalShield extends StatelessWidget {
  final Map<String, dynamic> r;
  const SniperCapitalShield({super.key, required this.r});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final cap = _m(r['capital']);
    final eq = _m(r['equity']);
    final curve = eq['all'] is List ? [for (final e in eq['all'] as List) if (e is num) e.toDouble()] : <double>[];
    final trades = (_n(eq['test_trades']) ?? 0).toInt();
    final net = curve.isEmpty ? null : curve.last;
    final c = net == null ? p.textMuted : (net >= 0 ? p.profit : p.loss);
    final avg = (net == null || trades == 0) ? null : net / trades / (_n(cap['base_usdt']) ?? 10.0) * 100.0;
    return OWLCard(
      edge: c,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'PILLAR A', 'Capital Shield', _chip('${_f(_n(cap['base_usdt']) ?? 10.0, 0)} USDT base', p.textSecondary)),
        const SizedBox(height: 10),
        Row(children: [
          _stat(p, _f(_n(cap['fee_pct']), 2, '%'), 'fee per side'),
          _stat(p, _f(_n(cap['slip_pct']), 2, '%'), 'slippage per side'),
          _stat(p, _f(_n(cap['round_trip_pct']), 2, '%'), 'cost of one round trip'),
          _stat(p, _f(_n(cap['max_stop_pct']), 1, '%'), 'widest stop allowed'),
        ]),
        const SizedBox(height: 8),
        Text(
          cap.isEmpty
              ? 'The cost numbers are not in this backend answer yet. Install the newest backend zip.'
              : 'Worst case of ONE trade is about ${_f(_n(cap['worst_loss_usdt']), 2)} USDT (the widest stop plus the costs). A stop wider than that is refused.',
          style: TextStyle(fontSize: 12, color: p.textSecondary),
        ),
        const Divider(height: 18),
        Text(
          net == null
              ? 'No result on the unseen TEST days yet.'
              : 'Net after fees and slippage on the unseen TEST days: ${_sg(net)} USDT in $trades trades${avg == null ? '' : ' (${_sg(avg)}% of the base per trade)'}.',
          style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: c == p.textMuted ? p.textPrimary : c),
        ),
        const SizedBox(height: 4),
        Text('A replay on saved candles, not a promise. Real trades can end better or worse.', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }
}

/// Pillar B: Volatility Guard.
class SniperVolatilityGuard extends StatelessWidget {
  final Map<String, dynamic> r;
  const SniperVolatilityGuard({super.key, required this.r});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final b = '${r['banner'] ?? 'UNKNOWN'}';
    final g = _m(r['regimes']);
    final up = (_n(g['TRENDING']) ?? 0).toInt(), side = (_n(g['SIDEWAYS']) ?? 0).toInt(), unk = (_n(g['UNKNOWN']) ?? 0).toInt();
    late final String word, sub;
    late final Color c;
    late final IconData icon;
    switch (b) {
      case 'TRENDING':
        word = 'MARKET REGIME: TRENDING SAFE';
        sub = 'Most coins are trending, so signals may be checked. Safe here only means trades are allowed to be checked: every other check still has to pass.';
        c = p.profit;
        icon = Icons.verified_user_rounded;
        break;
      case 'SIDEWAYS':
        word = 'MARKET REGIME: SIDEWAYS (Trading Blocked)';
        sub = 'Most coins are flat. A crossover in a flat market is never traded.';
        c = p.loss.withOpacity(0.85);
        icon = Icons.block_rounded;
        break;
      case 'MIXED':
        word = 'MARKET REGIME: MIXED';
        sub = 'Some coins trend and some are flat. Every coin is judged on its own.';
        c = p.warning;
        icon = Icons.tune_rounded;
        break;
      default:
        word = 'MARKET REGIME: NOT CLEAR YET';
        sub = 'There is not enough fresh data to tell. Trades stay blocked.';
        c = p.textMuted;
        icon = Icons.help_outline_rounded;
    }
    final total = up + side + unk;
    return OWLCard(
      edge: c,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'PILLAR B', 'Volatility Guard', const SizedBox.shrink()),
        const SizedBox(height: 10),
        Row(children: [
          Icon(icon, color: c, size: 22),
          const SizedBox(width: 8),
          Expanded(child: Text(word, style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800, color: c))),
        ]),
        const SizedBox(height: 6),
        Text(sub, style: TextStyle(fontSize: 12, color: p.textSecondary)),
        const SizedBox(height: 10),
        if (total > 0) ...[
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: SizedBox(
              height: 8,
              child: Row(children: [
                if (up > 0) Expanded(flex: up, child: Container(color: p.profit)),
                if (side > 0) Expanded(flex: side, child: Container(color: p.loss.withOpacity(0.85))),
                if (unk > 0) Expanded(flex: unk, child: Container(color: p.textMuted)),
              ]),
            ),
          ),
          const SizedBox(height: 8),
          Row(children: [
            _stat(p, '$up', 'trending', p.profit),
            _stat(p, '$side', 'sideways', p.loss),
            _stat(p, '$unk', 'not clear', p.textMuted),
          ]),
        ] else
          Text('No coin has been scanned yet.', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }
}

/// Pillar C: Terminal Insight console.
class SniperInsightConsole extends StatelessWidget {
  final Map<String, dynamic> r;
  final int maxLines;
  const SniperInsightConsole({super.key, required this.r, this.maxLines = 3});

  String _line(Map<String, dynamic> c) {
    final z = _n(c['z']), conf = _n(c['confidence']), sd = _n(c['sd_len']);
    return 'Lookback Length = ${sd == null ? '--' : sd.toInt()} | Z-Score = ${_f(z, 2)} | Win Probability = ${conf == null ? '--' : (conf * 100).toStringAsFixed(1)} %';
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    const mono = 'monospace';
    final cards = _l(r['cards']).take(maxLines).toList();
    final floor = (_n(r['floor']) ?? 0.85) * 100;
    final proven = r['floor_verified'] == true;
    final rows = <Widget>[];
    if (cards.isEmpty) {
      rows.add(Text('> Lookback Length = -- | Z-Score = -- | Win Probability = -- %', style: TextStyle(fontFamily: mono, fontSize: 11.5, color: p.textMuted)));
      rows.add(const SizedBox(height: 4));
      rows.add(Text('> No coin has a signal right now. Watching.', style: TextStyle(fontFamily: mono, fontSize: 11.5, color: p.textSecondary)));
    }
    for (final c in cards) {
      final pass = c['action'] == 'SNIPER_LONG' || c['action'] == 'SNIPER_SHORT';
      final col = pass ? p.profit : p.warning;
      rows.add(Text('> ${c['symbol'] ?? '--'}  ${c['side'] ?? ''}  ${pass ? 'PASS' : 'BLOCKED'}', style: TextStyle(fontFamily: mono, fontSize: 11.5, fontWeight: FontWeight.w700, color: col)));
      rows.add(Text('  ${_line(c)}', style: TextStyle(fontFamily: mono, fontSize: 11.5, color: p.textPrimary)));
      rows.add(const SizedBox(height: 6));
    }
    rows.add(Text('> Floor = ${floor.toStringAsFixed(0)} % | proven on TEST days: ${proven ? 'yes' : 'NO (signals are held back)'}',
        style: TextStyle(fontFamily: mono, fontSize: 11.5, color: proven ? p.profit : p.warning)));
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'PILLAR C', 'Terminal Insight', _chip('watch only', p.textSecondary)),
        const SizedBox(height: 10),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(color: p.bg, borderRadius: BorderRadius.circular(8), border: Border.all(color: p.border)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: rows),
        ),
      ]),
    );
  }
}

/// The three pillars in one column.
class SniperPillars extends StatelessWidget {
  final Map<String, dynamic> r;
  const SniperPillars({super.key, required this.r});

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      SniperVolatilityGuard(r: r),
      const SizedBox(height: AppSpacing.m),
      SniperInsightConsole(r: r),
      const SizedBox(height: AppSpacing.m),
      SniperCapitalShield(r: r),
    ]);
  }
}
