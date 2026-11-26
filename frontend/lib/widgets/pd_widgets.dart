import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';

/// Small building blocks of the Pump / Dump tab (26 Nov 2026). Plain widgets, no provider, no timer. Dart NOT compiled in the sandbox.

double pdNum(dynamic v) => v is num ? v.toDouble() : (double.tryParse('$v') ?? 0.0);

/// BTCUSDT -> BTC
String pdCoin(String s) => s.endsWith('USDT') ? s.substring(0, s.length - 4) : s;

String pdSigned(double v, {int digits = 1}) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(digits)}%';

String pdPrice(double v) {
  if (v >= 100) return v.toStringAsFixed(2);
  if (v >= 1) return v.toStringAsFixed(3);
  if (v >= 0.01) return v.toStringAsFixed(4);
  return v.toStringAsPrecision(3);
}

/// 12345678 -> 12.3M
String pdMoney(double v) {
  if (v >= 1e9) return '${(v / 1e9).toStringAsFixed(1)}B';
  if (v >= 1e6) return '${(v / 1e6).toStringAsFixed(1)}M';
  if (v >= 1e3) return '${(v / 1e3).toStringAsFixed(0)}K';
  return v.toStringAsFixed(0);
}

String pdStageLabel(String stage, bool pump) {
  switch (stage) {
    case 'WATCH':
      return 'WATCH';
    case 'START':
      return pump ? 'PUMP START' : 'DUMP START';
    case 'RUNNING':
      return pump ? 'PUMP RUNNING' : 'DUMP RUNNING';
    case 'WEAK':
      return 'WEAK';
    default:
      return 'ENDED';
  }
}

Color pdStageColor(AppPalette p, String stage, bool pump) {
  switch (stage) {
    case 'START':
    case 'RUNNING':
      return pump ? p.profit : p.loss;
    case 'WEAK':
      return p.warning;
    default:
      return p.textMuted;
  }
}

class PdStageChip extends StatelessWidget {
  final String stage;
  final bool pump;
  const PdStageChip({super.key, required this.stage, required this.pump});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final c = pdStageColor(p, stage, pump);
    final strong = stage == 'START' || stage == 'RUNNING';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 2),
      decoration: BoxDecoration(color: c.withOpacity(strong ? 0.18 : 0.10), borderRadius: BorderRadius.circular(5)),
      child: Text(pdStageLabel(stage, pump), maxLines: 1, overflow: TextOverflow.clip, style: TextStyle(fontSize: 9, fontWeight: FontWeight.w800, color: c, letterSpacing: 0.2)),
    );
  }
}

/// One side of a two-column block: a coloured header (PUMP / DUMP + count) and the tiles under it.
class PdSideColumn extends StatelessWidget {
  final bool pump;
  final int count;
  final List<Widget> children;
  final String emptyText;
  const PdSideColumn({super.key, required this.pump, required this.count, required this.children, this.emptyText = 'None right now'});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final c = pump ? p.profit : p.loss;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        margin: const EdgeInsets.only(bottom: 6),
        decoration: BoxDecoration(color: c.withOpacity(0.12), borderRadius: BorderRadius.circular(8)),
        child: Row(children: [
          Icon(pump ? Icons.trending_up_rounded : Icons.trending_down_rounded, size: 16, color: c),
          const SizedBox(width: 5),
          Expanded(child: Text(pump ? 'PUMP' : 'DUMP', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: c))),
          Text('$count', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: c)),
        ]),
      ),
      if (children.isEmpty)
        Padding(padding: const EdgeInsets.symmetric(vertical: 14), child: Center(child: Text(emptyText, style: TextStyle(fontSize: 11.5, color: p.textMuted))))
      else
        ...children,
    ]);
  }
}

/// A coin that is in play RIGHT NOW (from /api/pd/live): stage, gain since the start, 5 min move, volume, how long.
class PdLiveTile extends StatelessWidget {
  final Map<String, dynamic> row;
  final bool pump;
  const PdLiveTile({super.key, required this.row, required this.pump});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final stage = '${row['stage']}';
    final gain = pdNum(row['gain']);
    final good = gain >= 0;
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: stage == 'START' || stage == 'RUNNING' ? pdStageColor(p, stage, pump).withOpacity(0.55) : p.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(pdCoin('${row['symbol']}'), maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800, color: p.textPrimary))),
          PdStageChip(stage: stage, pump: pump),
        ]),
        const SizedBox(height: 3),
        Text('${pdSigned(gain)} since ${stage == 'WATCH' ? 'watch' : 'start'}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: good ? p.profit : p.loss)),
        const SizedBox(height: 2),
        Text('5m ${pdSigned(pdNum(row['r5']))} · vol ${pdNum(row['vr5']).toStringAsFixed(1)}x', style: TextStyle(fontSize: 11, color: p.textSecondary)),
        const SizedBox(height: 2),
        Text('${pdPrice(pdNum(row['price']))} · ${pdNum(row['age_min']).toStringAsFixed(0)} min · score ${pdNum(row['score']).toStringAsFixed(0)}', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
      ]),
    );
  }
}

/// One saved event of a day (from /api/pd/day): coin, stage, move, volume, time (IST) and, for a START, the checked result. Tap = details.
class PdEventTile extends StatelessWidget {
  final Map<String, dynamic> e;
  final bool pump;
  const PdEventTile({super.key, required this.e, required this.pump});

  Widget _result(AppPalette p) {
    final r = e['result'];
    if (r is! Map) return Text('score ${pdNum(e['score']).toStringAsFixed(0)}', style: TextStyle(fontSize: 10.5, color: p.textMuted));
    final st = '${r['state']}';
    if (st == 'wait') return Text('checking... ${pdSigned(pdNum(r['mfe']))} best', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 10.5, color: p.warning));
    final real = st == 'real';
    return Text(real ? 'REAL ${pdSigned(pdNum(r['mfe']))}' : 'FAKE ${pdSigned(pdNum(r['mfe']))}', maxLines: 1, overflow: TextOverflow.ellipsis,
        style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: real ? p.profit : p.loss));
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final stage = '${e['stage']}';
    final c = pdStageColor(p, stage, pump);
    final time = '${e['time']}';
    return GestureDetector(
      onTap: () => showPdDetail(context, e, pump),
      child: Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: p.surface,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
          border: Border.all(color: stage == 'START' ? c.withOpacity(0.55) : p.border),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(pdCoin('${e['symbol']}'), maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary))),
            PdStageChip(stage: stage, pump: pump),
          ]),
          const SizedBox(height: 3),
          Text('${pdSigned(pdNum(e['r5']))} in 5m · ${pdNum(e['vr5']).toStringAsFixed(1)}x vol', style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
          const SizedBox(height: 3),
          Row(children: [
            Text(time.length >= 5 ? time.substring(0, 5) : time, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: p.textMuted)),
            const SizedBox(width: 6),
            Expanded(child: Align(alignment: Alignment.centerRight, child: _result(p))),
          ]),
        ]),
      ),
    );
  }
}

Widget _kv(AppPalette p, String k, String v) {
  return Padding(
    padding: const EdgeInsets.symmetric(vertical: 3),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SizedBox(width: 118, child: Text(k, style: TextStyle(fontSize: 12, color: p.textMuted))),
      Expanded(child: Text(v, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: p.textPrimary))),
    ]),
  );
}

String _pct(dynamic v) => v == null ? '-' : pdSigned(pdNum(v), digits: 2);

/// Bottom sheet with every number of one event.
void showPdDetail(BuildContext context, Map<String, dynamic> e, bool pump) {
  final p = context.palette;
  final stage = '${e['stage']}';
  final r = e['result'];
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
            Row(children: [
              Expanded(child: Text('${pdCoin('${e['symbol']}')}  ·  ${pump ? 'Pump' : 'Dump'}', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: p.textPrimary))),
              PdStageChip(stage: stage, pump: pump),
            ]),
            const SizedBox(height: 8),
            Text('${e['note'] ?? ''}', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
            const SizedBox(height: 10),
            _kv(p, 'Time (IST)', '${e['day']}  ${e['time']}'),
            _kv(p, 'Price', pdPrice(pdNum(e['price']))),
            _kv(p, 'Score', '${pdNum(e['score']).toStringAsFixed(0)} / 100'),
            _kv(p, 'Move 1m / 5m / 15m', '${pdSigned(pdNum(e['r1']), digits: 2)}  /  ${pdSigned(pdNum(e['r5']), digits: 2)}  /  ${pdSigned(pdNum(e['r15']), digits: 2)}'),
            _kv(p, 'Volume 1m / 5m', '${pdNum(e['vr1']).toStringAsFixed(1)}x  /  ${pdNum(e['vr5']).toStringAsFixed(1)}x of its own hour'),
            _kv(p, '24h turnover', '${pdMoney(pdNum(e['qv24']))} USDT'),
            _kv(p, 'Since start', pdSigned(pdNum(e['gain']), digits: 2)),
            _kv(p, 'Broke its range', e['brk'] == true ? 'yes' : 'no'),
            _kv(p, 'Flat before', e['flat'] == true ? 'yes' : 'no'),
            if (r is Map) ...[
              const Divider(height: 22),
              Text('Result (checked after the alert)', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
              const SizedBox(height: 4),
              _kv(p, 'Verdict', r['state'] == 'real' ? 'REAL (moved 2%+ the right way)' : (r['state'] == 'fake' ? 'FAKE (did not reach 2%)' : 'still being checked')),
              _kv(p, 'After 15 / 30 / 60 min', '${_pct(r['pct15'])}  /  ${_pct(r['pct30'])}  /  ${_pct(r['pct60'])}'),
              _kv(p, 'Best / worst', '${_pct(r['mfe'])}  /  ${_pct(r['mae'])}'),
            ],
            const SizedBox(height: 10),
            Text('A heads-up to open the chart, not a buy or sell order.', style: TextStyle(fontSize: 11, color: p.textMuted)),
          ]),
        ),
      ),
    ),
  );
}
