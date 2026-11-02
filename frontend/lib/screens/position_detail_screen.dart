import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import '../utils/trade_metrics.dart';
import '../widgets/stat_tile.dart';

/// Round 16: ONE open PAPER trade in detail. Opened from the "Trade details" button inside an expanded PositionRow.
///   top      coin, LONG / SHORT, profit (hero number) + ROI
///   metrics  MFE (best point), MAE (worst dip), give-back (how much of the best point was lost), candles held
///   health   EMA cloud, TSI and Z-Score: do they stand WITH the trade or AGAINST it (same numbers as the Owl Sniper engine)
///   buttons  ONLY the two existing paper endpoints: Move SL to break-even (/api/move_sl_breakeven) and Close (/api/close). Nothing new on the backend.
/// Honest limits: MFE / MAE come from candle wicks (not ticks) of the full candles after the entry plus the price now; a trade older than the loaded candles shows only a part of its path.
/// The screen re-reads its position from AppProvider.positions by id, so profit and price stay live. A missing number prints "--", never "None".
class PositionDetailScreen extends StatefulWidget {
  final Map<String, dynamic> pos;
  const PositionDetailScreen({super.key, required this.pos});

  @override
  State<PositionDetailScreen> createState() => _PositionDetailScreenState();
}

class _PositionDetailScreenState extends State<PositionDetailScreen> {
  List<dynamic> _candles = [];
  bool _loading = true;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prov = Provider.of<AppProvider>(context, listen: false);
    setState(() { _loading = true; _error = null; });
    final c = await prov.fetchCandles('${widget.pos['symbol']}', limit: 400);
    if (!mounted) return;
    setState(() {
      _candles = c;
      _loading = false;
      _error = c.isEmpty ? (prov.lastCandleError ?? 'No candles came back.') : null;
    });
  }

  static double? _n(dynamic v) => v is num ? v.toDouble() : null;

  Map<String, dynamic> _live(AppProvider prov) {
    final id = widget.pos['id'];
    for (final x in prov.positions) {
      if (x is Map && x['id'] == id) return Map<String, dynamic>.from(x);
    }
    return widget.pos;
  }

  Future<void> _breakeven(Object id) async {
    setState(() => _busy = true);
    final ok = await Provider.of<AppProvider>(context, listen: false).moveSlToBreakeven(id);
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(ok ? 'Stop loss moved to break-even.' : 'Nothing changed: the stop is already at or past entry, or the request failed.')));
  }

  Future<void> _close(Object id, String symbol) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Close $symbol?'),
        content: const Text('The paper trade closes now at the current price.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Close')),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    setState(() => _busy = true);
    final res = await Provider.of<AppProvider>(context, listen: false).closePosition(id);
    if (!mounted) return;
    setState(() => _busy = false);
    if (res['ok'] == true) {
      Navigator.pop(context);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Could not close $symbol: ${res['error'] ?? 'unknown error'}')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final prov = Provider.of<AppProvider>(context); // listens: the profit and the price move
    final p = context.palette;
    final pos = _live(prov);
    final id = pos['id'];
    final symbol = (pos['symbol'] ?? '--').toString();
    final isLong = pos['action'] == 'BUY';
    final pnl = _n(pos['pnl_usdt']), roi = _n(pos['roi_pct']), invest = _n(pos['invest_usdt']);
    final entry = _n(pos['entry_price']), ltp = _n(pos['ltp']);
    final pnlColor = pnl == null || pnl == 0 ? p.textPrimary : (pnl > 0 ? p.profit : p.loss);
    final m = tradeMetrics(candles: _candles, isLong: isLong, entry: entry, ltp: ltp, openedSec: _n(pos['opened_at_ts']));
    var lev = _n(pos['leverage']) ?? 1.0;
    if (lev <= 0) lev = 1.0;
    String pct(double? v) => v == null ? '--' : '${v.toStringAsFixed(2)}%';
    String usdt(double? v) => (v == null || invest == null) ? '' : '${fmtSigned(invest * v / 100 * lev)} USDT'; // price move x invest x leverage, like the position card
    final health = indicatorHealth(candles: _candles, isLong: isLong);
    final paper = id is int; // a live position has the symbol as its id: its buttons stay on the old card

    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(
        title: Row(children: [
          Flexible(child: Text(symbol, overflow: TextOverflow.ellipsis)),
          const SizedBox(width: 8),
          _chip(context, isLong ? 'LONG' : 'SHORT', isLong ? p.profit : p.loss),
        ]),
        actions: [IconButton(onPressed: _loading ? null : _load, icon: const Icon(Icons.refresh_rounded))],
      ),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.screenPad),
        children: [
          Text(pnl == null ? '--' : '${fmtSigned(pnl)} USDT', style: context.type.number.copyWith(fontSize: 32, fontWeight: FontWeight.w800, color: pnlColor)),
          Text(roi == null ? '--' : '${fmtSigned(roi, 1)}% ROI', style: context.type.metadata.copyWith(color: pnlColor)),
          const SizedBox(height: AppSpacing.s),
          Text('${entry == null ? '--' : fmtPrice(entry)} -> ${ltp == null ? '--' : fmtPrice(ltp)}', style: context.type.metadata),
          const SizedBox(height: AppSpacing.l),
          if (_loading) const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()))
          else if (_error != null) _note(context, 'Candles could not be loaded ($_error). The numbers below need candles.')
          else ...[
            Row(children: [
              Expanded(child: StatTile(label: 'Best point (MFE)', value: pct(m.mfePct), sub: usdt(m.mfePct), tone: 'good')),
              const SizedBox(width: AppSpacing.cardGap),
              Expanded(child: StatTile(label: 'Worst dip (MAE)', value: pct(m.maePct == null ? null : -m.maePct!), sub: usdt(m.maePct == null ? null : -m.maePct!), tone: 'bad')),
            ]),
            const SizedBox(height: AppSpacing.cardGap),
            Row(children: [
              Expanded(child: StatTile(label: 'Given back', value: pct(m.givebackPct), sub: m.givebackShare == null ? '' : '${m.givebackShare!.toStringAsFixed(0)}% of the best point', tone: (m.givebackShare ?? 0) >= 50 ? 'warn' : '')),
              const SizedBox(width: AppSpacing.cardGap),
              Expanded(child: StatTile(label: 'Candles held', value: '${m.candlesHeld}', sub: 'candles after entry: ${m.candlesUsed}')),
            ]),
            const SizedBox(height: AppSpacing.s),
            _note(context, m.olderThanCandles
                ? 'This trade is older than the loaded candles, so best point and worst dip show only the part we can see. They come from candle wicks, not every tick.'
                : 'Best point and worst dip come from candle wicks after the entry candle plus the price now, not from every tick.'),
          ],
          const SizedBox(height: AppSpacing.l),
          Text('Indicator health', style: context.type.primary.copyWith(fontWeight: FontWeight.w800)),
          const SizedBox(height: AppSpacing.s),
          for (final h in health) _healthRow(context, h),
          const SizedBox(height: AppSpacing.l),
          if (paper) ...[
            OutlinedButton.icon(
              onPressed: _busy ? null : () => _breakeven(id as Object),
              icon: const Icon(Icons.shield_outlined),
              label: const Text('Move stop to break-even'),
            ),
            const SizedBox(height: AppSpacing.s),
            FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: p.loss),
              onPressed: _busy ? null : () => _close(id as Object, symbol),
              icon: const Icon(Icons.close_rounded),
              label: const Text('Close position'),
            ),
          ] else
            _note(context, 'This is a live position. Use the position card on the Positions tab to change or close it.'),
        ],
      ),
    );
  }

  Widget _healthRow(BuildContext context, HealthLine h) {
    final p = context.palette;
    final c = h.state == 'with' ? p.profit : h.state == 'against' ? p.loss : p.textMuted;
    final word = h.state == 'with' ? 'WITH' : h.state == 'against' ? 'AGAINST' : 'UNKNOWN';
    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.cardGap),
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.cardPad, vertical: AppSpacing.m),
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
      child: Row(children: [
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(h.label, style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 2),
          Text(h.text, style: context.type.metadata),
        ])),
        const SizedBox(width: 8),
        _chip(context, word, c),
      ]),
    );
  }

  Widget _note(BuildContext context, String text) => Text(text, style: context.type.metadata.copyWith(color: context.palette.textMuted));

  Widget _chip(BuildContext context, String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(AppSpacing.radiusSmall - 2)),
        child: Text(text, style: context.type.label.copyWith(color: c, fontSize: 10.5, fontWeight: FontWeight.w700)),
      );
}
