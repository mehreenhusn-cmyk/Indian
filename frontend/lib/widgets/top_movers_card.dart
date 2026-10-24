import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';

/// "Today: best and worst coins". Plain sum of today's FINISHED trades per coin (from the alerts the app already loaded),
/// top 5 winners on the left, top 5 losers on the right. Nothing is fetched, nothing is guessed: if no trade finished
/// today the card says so. Trading day = UTC date (same as the Today ring).
class TopMoversCard extends StatelessWidget {
  const TopMoversCard({super.key});

  static String _ymd(num ts) {
    final d = DateTime.fromMillisecondsSinceEpoch((ts * 1000).toInt(), isUtc: true);
    return '${d.year}-${d.month}-${d.day}';
  }

  static String _short(String s) => s.endsWith('USDT') ? s.substring(0, s.length - 4) : s;

  @override
  Widget build(BuildContext context) {
    context.select<AppProvider, int>((p) => p.alertsRev);
    final alerts = context.read<AppProvider>().alerts;
    final today = _ymd(DateTime.now().millisecondsSinceEpoch / 1000);
    final sum = <String, double>{};
    final cnt = <String, int>{};
    for (final a in alerts) {
      if (a is! Map || a['d'] is! Map) continue;
      final d = a['d'] as Map;
      final ts = a['ts'];
      if (d['exit_tag'] == null || d['symbol'] == null || d['pnl'] is! num || ts is! num || _ymd(ts) != today) continue;
      final s = '${d['symbol']}';
      sum[s] = (sum[s] ?? 0) + (d['pnl'] as num).toDouble();
      cnt[s] = (cnt[s] ?? 0) + 1;
    }
    final win = sum.entries.where((e) => e.value > 0).toList()..sort((a, b) => b.value.compareTo(a.value));
    final lose = sum.entries.where((e) => e.value < 0).toList()..sort((a, b) => a.value.compareTo(b.value));
    final p = context.palette;
    final t = context.type;

    Widget col(String title, Color c, List<MapEntry<String, double>> l) {
      return Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: t.label.copyWith(color: c, fontWeight: FontWeight.w800, letterSpacing: 0.8)),
          const SizedBox(height: 6),
          if (l.isEmpty) Text('none', style: t.metadata),
          for (final e in l.take(5))
            Container(
              margin: const EdgeInsets.only(bottom: 4),
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              decoration: BoxDecoration(color: c.withOpacity(0.10), borderRadius: BorderRadius.circular(6)),
              child: Row(children: [
                Expanded(child: Text(_short(e.key), maxLines: 1, overflow: TextOverflow.ellipsis, style: t.primary.copyWith(fontSize: 12.5, fontWeight: FontWeight.w700))),
                Text(fmtSigned(e.value), style: t.primary.copyWith(fontSize: 12.5, fontWeight: FontWeight.w800, color: c)),
              ]),
            ),
        ]),
      );
    }

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: p.border.withOpacity(0.6)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('TODAY: BEST AND WORST COINS', style: t.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 0.6)),
        const SizedBox(height: 8),
        if (sum.isEmpty)
          Text('No trade has finished today yet.', style: t.secondary)
        else
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            col('WINNERS (USDT)', p.profit, win),
            const SizedBox(width: 12),
            col('LOSERS (USDT)', p.loss, lose),
          ]),
        if (sum.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text('Sum of finished trades per coin, today only.', style: t.metadata),
        ],
      ]),
    );
  }
}
