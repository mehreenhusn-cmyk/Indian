import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'candle_chart.dart';

/// TradingView-style trade view (replaces the old "replay" sheets).
///
/// Opens the SAME full chart the live positions use (candles, EMA30/50, SD bands, TSI + Z-score panes, pinch zoom,
/// drag, crosshair) but starts a few candles before the ENTRY and adds:
///   ENTRY / SL / TP lines   - from the signal
///   orange "B" flag         - where the BOT exited (price + P&L)
///   purple "A" flag         - where the AI exited (price + P&L)
/// plus ENTRY triangles (B IN / A IN / IN when both entered together), a dashed entry->exit path per side,
/// and one plain line on top: who made how much, and who left first.
/// Read-only: nothing here opens or closes a trade.
const Color kBotFlagColor = Color(0xFFF59E0B);
const Color kAiFlagColor = Color(0xFF7C3AED);
const Color kBothInColor = Color(0xFF2563EB);

/// HH:mm in IST (the app's trading clock) from epoch seconds.
String _hm(double sec) {
  final d = DateTime.fromMillisecondsSinceEpoch((sec * 1000).round(), isUtc: true).add(const Duration(hours: 5, minutes: 30));
  return '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
}

double? _n(dynamic v) => v is num ? v.toDouble() : (v is String ? double.tryParse(v) : null);

/// [t] = a Bot-vs-AI pair row (api: /api/ai/coach -> pairs) OR a Trade Book row (ai_book _compact).
void showTradeChart(BuildContext context, Map<String, dynamic> t) {
  final isPair = t.containsKey('bot') && t['bot'] is Map;
  final sym = '${t['sym'] ?? t['symbol'] ?? ''}';
  final sideRaw = '${t['side'] ?? ''}'.toUpperCase();
  final isLong = sideRaw == 'BUY' || sideRaw == 'LONG';
  final opened = _n(isPair ? t['t0'] : t['opened']);

  double? entry, sl;
  final tps = <int, double?>{};
  Map? bot, ai;
  if (isPair) {
    final lv = (t['plevels'] is Map) ? t['plevels'] as Map : const {};
    entry = _n(lv['entry']);
    sl = _n(lv['sl']);
    for (var k = 1; k <= 4; k++) {
      tps[k] = _n(lv['tp$k']);
    }
    bot = t['bot'] as Map?;
    ai = t['ai'] as Map?;
  } else {
    entry = _n(t['entry']);
    sl = _n(t['sl']);
    for (var k = 1; k <= 4; k++) {
      tps[k] = _n(t['tp$k']);
    }
    final closed = _n(t['closed']);
    bot = {
      'state': t['state'] ?? 'closed',
      'exit_px': t['exit'],
      'closed_ts': closed,
      'pnl': t['pnl'],
      'roi': t['roi'],
      'reason': t['reason'],
      'exit_sec': (opened != null && closed != null) ? closed - opened : null,
    };
  }

  final exits = <ChartExitMark>[];
  final links = <ChartTradeLink>[];
  final entries = <ChartEntryMark>[];
  String money(dynamic v) {
    final d = _n(v);
    return d == null ? '' : '${fmtSigned(d)} USDT';
  }

  // ---- ENTRY points (where each side got in) ----
  final botEntryTs = opened;
  final botEntryPx = _n(bot?['entry']) ?? entry;
  double? aiEntryTs;
  double? aiEntryPx;
  if (isPair && ai != null && ai['state'] != 'none') {
    aiEntryPx = _n(ai['entry']);
    aiEntryTs = _n(ai['entry_ts']) ?? (opened != null ? opened + (_n(ai['copy_after']) ?? 0) : null);
  }

  // ---- EXIT points (where each side got out) ----
  ({int ts, double px})? addExit(Map? side, String label, Color c) {
    if (side == null || side['state'] != 'closed') return null;
    final ts = _n(side['closed_ts']) ?? ((opened != null && _n(side['exit_sec']) != null) ? opened + _n(side['exit_sec'])! : null);
    final px = _n(side['exit_px']);
    if (ts == null || px == null) return null;
    final ms = (ts * 1000).round();
    exits.add(ChartExitMark(
      tsMs: ms,
      price: px,
      label: label,
      color: c,
      note: '${label == 'B' ? 'BOT' : 'AI'} OUT ${money(side['pnl'])}',
    ));
    return (ts: ms, px: px);
  }

  final botOut = addExit(bot, 'B', kBotFlagColor);
  final aiOut = addExit(ai, 'A', kAiFlagColor);

  final bothSame = botEntryTs != null &&
      botEntryPx != null &&
      aiEntryTs != null &&
      aiEntryPx != null &&
      (aiEntryTs - botEntryTs).abs() < 90 &&
      (aiEntryPx - botEntryPx).abs() <= botEntryPx.abs() * 0.0005;

  if (botEntryTs != null && botEntryPx != null) {
    final bms = (botEntryTs * 1000).round();
    entries.add(ChartEntryMark(
      tsMs: bms,
      price: botEntryPx,
      label: bothSame ? 'IN' : 'B',
      color: bothSame ? kBothInColor : kBotFlagColor,
      isLong: isLong,
      note: bothSame ? 'BOT + AI IN ${fmtPrice(botEntryPx)}' : 'BOT IN ${fmtPrice(botEntryPx)}',
    ));
    if (botOut != null) {
      links.add(ChartTradeLink(fromTsMs: bms, fromPrice: botEntryPx, toTsMs: botOut.ts, toPrice: botOut.px, color: kBotFlagColor));
    }
  }
  if (aiEntryTs != null && aiEntryPx != null) {
    final ams = (aiEntryTs * 1000).round();
    if (!bothSame) {
      entries.add(ChartEntryMark(
        tsMs: ams,
        price: aiEntryPx,
        label: 'A',
        color: kAiFlagColor,
        isLong: isLong,
        note: 'AI IN ${fmtPrice(aiEntryPx)}',
      ));
    }
    if (aiOut != null) {
      links.add(ChartTradeLink(fromTsMs: ams, fromPrice: aiEntryPx, toTsMs: aiOut.ts, toPrice: aiOut.px, color: kAiFlagColor));
    }
  }

  String tf = '${t['tf_chart'] ?? t['tf'] ?? ''}';
  if (!const ['1m', '3m', '5m', '15m', '1h'].contains(tf)) tf = '';

  // one short "in -> out" line per side for the summary box under the title
  String? route(double? inTs, double? inPx, Map? side) {
    if (inTs == null || inPx == null) return null;
    final outTs = _n(side?['closed_ts']) ?? ((opened != null && _n(side?['exit_sec']) != null) ? opened + _n(side!['exit_sec'])! : null);
    final outPx = _n(side?['exit_px']);
    final head = 'IN ${_hm(inTs)}  ${fmtPrice(inPx)}';
    if (side?['state'] == 'closed' && outTs != null && outPx != null) {
      return '$head  →  OUT ${_hm(outTs)}  ${fmtPrice(outPx)}';
    }
    return side?['state'] == 'open' ? '$head  →  still open' : head;
  }

  showCandleChartSheet(
    context,
    sym,
    entry: entry,
    sl: sl,
    tpLevels: tps.values.any((v) => v != null) ? tps : null,
    isLong: isLong,
    entryTsMs: opened == null ? null : (opened * 1000).round(),
    focusTsMs: opened == null ? null : (opened * 1000).round() - 6 * 60 * 1000,
    exits: exits.isEmpty ? null : exits,
    entries: entries.isEmpty ? null : entries,
    links: links.isEmpty ? null : links,
    initialTf: tf.isEmpty ? null : tf,
    title: '$sym  ${isLong ? 'LONG' : 'SHORT'}',
    summary: _TradeSummary(
      bot: bot,
      ai: ai,
      isPair: isPair,
      isLong: isLong,
      botRoute: route(botEntryTs, botEntryPx, bot),
      aiRoute: route(aiEntryTs, aiEntryPx, ai),
    ),
  );
}

class _TradeSummary extends StatelessWidget {
  final Map? bot;
  final Map? ai;
  final bool isPair;
  final bool isLong;
  final String? botRoute;
  final String? aiRoute;
  const _TradeSummary({required this.bot, required this.ai, required this.isPair, required this.isLong, this.botRoute, this.aiRoute});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    String state(Map? m) {
      if (m == null) return '-';
      final s = '${m['state']}';
      if (s == 'open') return 'still in the trade';
      if (s == 'closed') {
        // keep it short: "TRAIL (trailing stop after TP4, profit locked)" -> "TRAIL"
        final r = '${m['reason'] ?? ''}'.split(RegExp(r'[ (]')).first;
        return r.isEmpty ? 'exited' : 'exited $r';
      }
      return 'no trade';
    }

    Color pc(Map? m) {
      final v = _n(m?['pnl']) ?? _n(m?['roi']);
      if (v == null) return p.textMuted;
      return v > 0 ? p.profit : (v < 0 ? p.loss : p.textMuted);
    }

    String val(Map? m) {
      final v = _n(m?['pnl']);
      if (v != null) return '${fmtSigned(v)} USDT';
      final r = _n(m?['roi']);
      return r == null ? '-' : '${fmtSigned(r)}%';
    }

    Widget row(String flag, Color c, String name, Map? m, String? route) => Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 18,
              height: 18,
              alignment: Alignment.center,
              decoration: BoxDecoration(color: c, shape: BoxShape.circle),
              child: Text(flag, style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w800)),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('$name: ${state(m)}', maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: p.textSecondary, fontSize: 12)),
                  if (route != null) Text(route, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: p.textMuted, fontSize: 10.5)),
                ],
              ),
            ),
            Text(val(m), style: TextStyle(color: pc(m), fontSize: 13, fontWeight: FontWeight.w800)),
          ],
        );

    // who left first / who made more - only when both finished
    String? verdict;
    if (isPair && bot?['state'] == 'closed' && ai?['state'] == 'closed') {
      final bp = _n(bot!['pnl']);
      final ap = _n(ai!['pnl']);
      final bs = _n(bot!['exit_sec']);
      final as_ = _n(ai!['exit_sec']);
      if (bp != null && ap != null) {
        final d = ap - bp;
        final when = (bs != null && as_ != null && (bs - as_).abs() >= 60)
            ? (as_ < bs ? 'AI left ${((bs - as_) / 60).round()} min earlier. ' : 'AI stayed ${((as_ - bs) / 60).round()} min longer. ')
            : '';
        verdict = d.abs() < 0.005 ? '${when}Same result.' : '$when${d > 0 ? 'AI did better' : 'Bot did better'} by ${d.abs().toStringAsFixed(2)} USDT.';
      }
    } else if (isPair && ai?['state'] == 'none') {
      verdict = '${ai?['why'] ?? 'The AI has no copy of this trade.'}';
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(color: p.surfaceElevated, borderRadius: BorderRadius.circular(10), border: Border.all(color: p.border)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          row('B', kBotFlagColor, 'Bot', bot, botRoute),
          if (isPair) ...[const SizedBox(height: 5), row('A', kAiFlagColor, 'AI', ai, aiRoute)],
          if (verdict != null) ...[
            const SizedBox(height: 5),
            Text(verdict, style: TextStyle(color: p.textPrimary, fontSize: 12, fontWeight: FontWeight.w700)),
          ],
        ],
      ),
    );
  }
}
