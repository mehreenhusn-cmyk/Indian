import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';

/// Round D (26 Nov 2026): the Dashboard block that replaces "Recent Activity" in LITE (the Brain timeline behind it is switched off).
/// It shows ONLY today's signals of the current bot (trading day = 00:00 UTC = 5:30 AM IST), newest first, max 5, with the IST time.
/// Read only: the numbers come from provider.signals (the list the Signals tab already uses). No new call, no timer.
class DashTodaySignals extends StatelessWidget {
  const DashTodaySignals({super.key});

  static String _today() {
    final d = DateTime.now().toUtc();
    return '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  }

  /// How many signals of the current trading day (00:00 UTC = 5:30 AM IST) the list holds.
  static int countToday(List<dynamic> signals) {
    final key = _today();
    return signals.whereType<Map>().where((s) => '${s['date_str']}' == key).length;
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final prov = context.watch<AppProvider>();
    final key = _today();
    final todays = prov.signals.whereType<Map>().where((s) => '${s['date_str']}' == key).toList();
    final shown = todays.take(5).toList();
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.cardPad),
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text("TODAY'S SIGNALS", style: context.type.label.copyWith(letterSpacing: 1.0, fontWeight: FontWeight.w700))),
          Text('${todays.length} today', style: context.type.metadata.copyWith(color: p.textMuted)),
        ]),
        const SizedBox(height: AppSpacing.s),
        if (shown.isEmpty) Text('No signal yet today (day starts 5:30 AM IST).', style: context.type.metadata.copyWith(color: p.textMuted)),
        for (final s in shown)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(children: [
              Container(width: 7, height: 7, margin: const EdgeInsets.only(right: 8), decoration: BoxDecoration(shape: BoxShape.circle, color: s['action'] == 'BUY' ? p.profit : p.loss)),
              Expanded(child: Text('${s['symbol'] ?? '-'}', maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata.copyWith(fontWeight: FontWeight.w700, color: p.textPrimary))),
              Text(s['action'] == 'BUY' ? 'BUY' : 'SELL', style: context.type.metadata.copyWith(fontWeight: FontWeight.w700, color: s['action'] == 'BUY' ? p.profit : p.loss)),
              const SizedBox(width: AppSpacing.m),
              Text('${s['ist_time_str'] ?? ''}', style: context.type.metadata.copyWith(color: p.textMuted)),
            ]),
          ),
      ]),
    );
  }
}
