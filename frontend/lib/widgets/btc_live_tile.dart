import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'candle_chart.dart';
import 'owl_pressable.dart';

/// Dashboard tile: BTC live price (moves every second, green/red flash) and BTC's own result today.
/// BTC numbers are kept apart from the alt coins. Tap = Signals tab with the BTC chip on.
/// The price comes from the bot's own Binance push feed through GET /api/btc/live (light call, 1 per second,
/// paused while the Dashboard is not on screen).
class BtcLiveTile extends StatefulWidget {
  const BtcLiveTile({super.key});

  @override
  State<BtcLiveTile> createState() => _BtcLiveTileState();
}

class _BtcLiveTileState extends State<BtcLiveTile> {
  Timer? _timer;
  Map<String, dynamic> _d = {};
  double? _prev;
  bool _up = true;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _tick();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  static double? _n(dynamic v) => v is num ? v.toDouble() : double.tryParse('$v');

  Future<void> _tick() async {
    if (_busy || !mounted || !TickerMode.of(context)) return;
    _busy = true;
    final d = await context.read<AppProvider>().getBtcJson('/api/btc/live');
    _busy = false;
    if (!mounted || d == null) return;
    final px = _n(d['price']);
    setState(() {
      if (px != null && _prev != null && px != _prev) _up = px > _prev!;
      if (px != null) _prev = px;
      _d = d;
    });
  }

  String _px(double v) {
    final s = v.toStringAsFixed(2);
    final parts = s.split('.');
    final whole = parts[0].replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+$)'), (m) => '${m[1]},');
    return '$whole.${parts[1]}';
  }

  String _sg(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final px = _n(_d['price']);
    final ch = _n(_d['change_pct']);
    final today = _n(_d['today_pnl']) ?? 0.0;
    final trades = (_d['today_trades'] is num) ? (_d['today_trades'] as num).toInt() : 0;
    final open = (_d['open'] is num) ? (_d['open'] as num).toInt() : 0;
    final pxColor = px == null ? p.textPrimary : (_up ? p.profit : p.loss);
    final todayColor = today > 0 ? p.profit : (today < 0 ? p.loss : p.textSecondary);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: OWLPressable(
        onTap: () => showCandleChartSheet(context, 'BTCUSDT'),   // tap the tile = BTC chart (full pan/zoom sheet)
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: p.surface,
            borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
            border: Border.all(color: p.accent.withOpacity(0.55)),
          ),
          child: Row(children: [
            Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(color: const Color(0xFFF7931A).withOpacity(0.16), shape: BoxShape.circle),
              child: const Icon(Icons.currency_bitcoin_rounded, size: 24, color: Color(0xFFF7931A)),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Text('BTC / USDT', style: context.type.metadata.copyWith(fontWeight: FontWeight.w700)),
                  if (ch != null) ...[
                    const SizedBox(width: 8),
                    Text('${_sg(ch)}%', style: context.type.metadata.copyWith(color: ch >= 0 ? p.profit : p.loss, fontWeight: FontWeight.w700)),
                  ],
                ]),
                AnimatedDefaultTextStyle(
                  duration: const Duration(milliseconds: 300),
                  style: context.type.primary.copyWith(fontWeight: FontWeight.w900, fontSize: 22, color: pxColor),
                  child: Text(px == null ? 'Waiting for price...' : _px(px)),
                ),
              ]),
            ),
            // Right part = BTC trades (the Signals tab with the BTC chip on). Left / middle = the chart.
            OWLPressable(
              onTap: () => context.read<AppProvider>().openBtcSignals(),
              child: Row(children: [
                Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text('BTC today', style: context.type.metadata),
                  Text('${_sg(today)} USDT', style: context.type.primary.copyWith(fontWeight: FontWeight.w800, color: todayColor)),
                  Text('$trades closed · $open open', style: context.type.metadata),
                ]),
                const SizedBox(width: 4),
                Icon(Icons.chevron_right, color: p.textSecondary),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}
