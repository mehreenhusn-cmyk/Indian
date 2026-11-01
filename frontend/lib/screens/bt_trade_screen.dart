import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/bt_mini_chart.dart';
import '../widgets/owl_card.dart';

/// Part 87b (Active Paper Trade): read-only. The open PAPER trade of one coin from /api/v2/brain_trade (Part 87): chart with ENTRY / STOP / TARGET, unrealized net (after fee + slippage),
/// best point so far, worst point, give-back, candles held and left, a plain WATCH label (HOLD / PROTECT / CLOSE SOON = words, not orders) and "why I am still in this trade".
/// Marked PAPER ONLY. If the coin has no open trade it says so and shows the last closed one. Dart NOT compiled (the APK build is the proof).
class BtTradeScreen extends StatefulWidget {
  final String symbol;
  final String interval;
  const BtTradeScreen({super.key, required this.symbol, this.interval = '5m'});

  static Future<void> open(BuildContext context, String symbol, [String interval = '5m']) =>
      Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => BtTradeScreen(symbol: symbol, interval: interval)));

  @override
  State<BtTradeScreen> createState() => _BtTradeScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<String> _s(Object? v) => v is List ? [for (final e in v) '$e'] : <String>[];
double _d(Object? v) => v is num ? v.toDouble() : (double.tryParse('$v') ?? 0);
String _sg(double x, [int dp = 2]) => '${x >= 0 ? '+' : ''}${x.toStringAsFixed(dp)}';

class _BtTradeScreenState extends State<BtTradeScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchBrainTrade(widget.symbol, widget.interval);
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  String _problem(Map<String, dynamic> r) {
    switch (r['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the Active Trade route yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  Widget _title(AppPalette p, String t) => Padding(padding: const EdgeInsets.only(bottom: 6), child: Text(t, style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800, color: p.textPrimary)));

  Widget _kv(AppPalette p, String k, String v, [Color? c]) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          Expanded(child: Text(k, style: TextStyle(fontSize: 12.5, color: p.textSecondary))),
          Text(v, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: c ?? p.textPrimary)),
        ]),
      );

  String _px(double v) => v >= 100 ? v.toStringAsFixed(2) : v.toStringAsFixed(v >= 1 ? 4 : 6);

  Color _watchColor(AppPalette p, String w) => w == 'HOLD' ? p.profit : (w == 'PROTECT' ? p.warning : p.loss);

  List<Widget> _open(AppPalette p, Map<String, dynamic> r) {
    final net = _d(r['unrealized_net_usdt']);
    final w = '${r['watch']}';
    final wc = _watchColor(p, w);
    return [
      OWLCard(
        hasPositiveGlow: net > 0,
        hasNegativeGlow: net < 0,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('${r['symbol']}  ${r['side']}', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: p.textPrimary))),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(color: wc.withOpacity(0.14), borderRadius: BorderRadius.circular(10), border: Border.all(color: wc.withOpacity(0.5))),
              child: Text(w, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: wc)),
            ),
          ]),
          Text('PAPER ONLY (pretend money) - opened ${r['opened']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
          const SizedBox(height: 4),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(_sg(net), style: TextStyle(fontSize: 30, fontWeight: FontWeight.w800, color: net >= 0 ? p.profit : p.loss)),
            const SizedBox(width: 6),
            Padding(padding: const EdgeInsets.only(bottom: 5), child: Text('USDT now, after fee + slippage', style: TextStyle(fontSize: 12, color: p.textSecondary))),
          ]),
          const SizedBox(height: 8),
          BtMiniChart(
            chart: _m(r['chart']),
            lines: [BtLine(_d(r['entry']), 'ENTRY', p.textPrimary), BtLine(_d(r['sl']), 'STOP', p.loss), BtLine(_d(r['tp']), 'TARGET', p.profit)],
            up: p.profit,
            down: p.loss,
            ema: p.accent,
            band: p.textMuted,
            text: p.textMuted,
          ),
        ]),
      ),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'The trade'),
          _kv(p, 'Entry', _px(_d(r['entry']))),
          _kv(p, 'Now', _px(_d(r['now']))),
          _kv(p, 'Stop', _px(_d(r['sl'])), p.loss),
          _kv(p, 'Target', _px(_d(r['tp'])), p.profit),
          _kv(p, 'Best point so far', '${_sg(_d(r['mfe_pct']))}%'),
          _kv(p, 'Worst point so far', '${_sg(_d(r['mae_pct']))}%'),
          _kv(p, 'Given back from best', '${_d(r['giveback_pct']).toStringAsFixed(2)}%'),
          _kv(p, 'Candles held / left', '${r['held']} / ${r['left']}'),
          _kv(p, 'Pretend size', '${_d(r['size_usdt']).toStringAsFixed(0)} USDT'),
        ]),
      ),
      OWLCard(
        edge: wc,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'Why I am still in this trade'),
          for (final s in _s(r['why'])) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text(s, style: TextStyle(fontSize: 12.5, color: s.startsWith('Dhyan') ? p.warning : p.textPrimary))),
          const SizedBox(height: 4),
          Text('HOLD = nothing special. PROTECT = gave back half of a real gain, or TSI and the histogram turned against the trade. CLOSE SOON = 2 or fewer candles of hold time left. For a BT-02 trade the word is the Brain's own exit decision (HOLD / PROTECT = stop moved to lock profit / CLOSE = it closes now). These are words, not orders: the paper trade closes by itself at stop, target or time.',
              style: TextStyle(fontSize: 11, color: p.textMuted)),
        ]),
      ),
      Text('${r['paper_note']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    } else if (r == null || r['state'] != null || r['error'] != null) {
      kids = [OWLCard(edge: p.warning, child: Text(r != null && r['error'] != null ? '${r['error']}' : _problem(r ?? <String, dynamic>{'state': 'error'}), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else if (r['open'] != true) {
      final last = r['last_closed'] == null ? null : _m(r['last_closed']);
      kids = [
        OWLCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${r['note'] ?? 'No open paper trade in this coin.'}', style: TextStyle(fontSize: 13, color: p.textPrimary)),
            if (last != null) ...[
              const SizedBox(height: 6),
              Text('Last closed: ${last['side']}, ended by ${last['exit']}, net ${_sg(_d(last['net_usdt']))} USDT after ${last['held']} candles.', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
            ],
          ]),
        ),
      ];
    } else if (r['ready'] != true) {
      kids = [OWLCard(edge: p.warning, child: Text(_s(r['lines']).isNotEmpty ? _s(r['lines']).first : 'Not ready.', style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else {
      kids = _open(p, r);
    }
    return Scaffold(
      appBar: AppBar(title: Text('Paper trade - ${widget.symbol}')),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.l),
          children: [for (final k in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: k)],
        ),
      ),
    );
  }
}
