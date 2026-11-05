import 'package:flutter/material.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'owl_number.dart';
import 'owl_row.dart';

/// Part 17a: EXPECTED vs ACTUAL on the Sniper tab (inside an OwlFold). Data = GET /api/v2/sniper_eva: when a Sniper paper trade opens, the Risk Box answer is frozen;
/// when the trade closes, the real result (R = paper P&L / 1R in USDT) is compared with it. One row per lane (EXPLORE / LEARN / REAL, never added together).
/// Below 30 compared trades a lane shows only "N of 30 compared" and NO number. From 30: verdict pill ON TRACK / BELOW / ABOVE, tap = all lines (expected R, actual R, gap, win %).
/// Report only: nothing is paused or changed from here. Paper money. Dart NOT compiled.
class SniperEvaCard extends StatelessWidget {
  final Map<String, dynamic>? e;

  const SniperEvaCard({super.key, required this.e});

  static Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};

  static String _word(String s) => s == 'BELOW_EXPECTED' ? 'BELOW' : s == 'ABOVE_EXPECTED' ? 'ABOVE' : s == 'ON_TRACK' ? 'ON TRACK' : 'NOT ENOUGH';

  static String _tone(String s) => s == 'BELOW_EXPECTED' ? 'bad' : (s == 'ABOVE_EXPECTED' || s == 'ON_TRACK') ? 'good' : '';

  /// The one-line summary for the fold header.
  static String headline(Map<String, dynamic>? e) {
    if (e == null) return 'Did the Risk Box expectation come true?';
    final lanes = _m(e['lanes']);
    final verdicts = [for (final v in lanes.values) '${_m(v)['state']}'].where((s) => s != 'NOT_ENOUGH_DATA' && s != 'null').toList();
    if (verdicts.isNotEmpty) return verdicts.map(_word).toSet().join(', ');
    if (e['n_compared'] == null) return 'Not available yet';
    return '${e['n_compared']} of ${e['min_n'] ?? 30} compared';
  }

  String _problem(String? st, Object? text) {
    switch (st) {
      case 'off':
        return text == null ? 'The Sniper is switched off.' : '$text';
      case 'old':
        return 'This backend has no expected-vs-actual route yet. Install the newest backend zip and restart it.';
      default:
        return 'Cannot read this right now. Pull down to try again.';
    }
  }

  void _open(BuildContext context, String lane, Map<String, dynamic> c) {
    final p = context.palette;
    final lines = [for (final x in (c['lines'] is List ? c['lines'] as List : const [])) '$x'];
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: p.surface,
      isScrollControlled: true,
      builder: (_) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.l),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              Expanded(child: Text('$lane  expected vs actual', style: context.type.section)),
              OwlPill(_word('${c['state']}'), tone: _tone('${c['state']}')),
            ]),
            const SizedBox(height: AppSpacing.m),
            for (final l in lines) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(l, style: context.type.secondary.copyWith(height: 1.35))),
            Text('Report only. Nothing is paused. Paper money, not a promise.', style: context.type.metadata),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final d = e;
    if (d == null) return const OwlRowSkeleton(rows: 2);
    if (d['state'] != 'OK' && d['state'] != 'NOT_ENOUGH_DATA') {
      return Text(_problem('${d['state']}', d['text']), style: context.type.secondary);
    }
    final lanes = _m(d['lanes']);
    final min = d['min_n'] ?? 30;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('${d['text'] ?? ''}', style: context.type.secondary),
      const SizedBox(height: AppSpacing.s),
      if (lanes.isEmpty)
        Text('No trade has closed with a saved expectation yet. A verdict needs $min compared trades per lane; before that, no number is shown.', style: context.type.metadata)
      else
        OwlListCard(children: [
          for (final k in lanes.keys)
            OwlRow(
              title: k,
              sub: _m(lanes[k])['state'] == 'NOT_ENOUGH_DATA' ? '${_m(lanes[k])['n'] ?? 0} of $min compared. No number yet.' : '${_m(lanes[k])['text'] ?? ''}',
              onTap: () => _open(context, k, _m(lanes[k])),
              trailing: OwlPill(_word('${_m(lanes[k])['state']}'), tone: _tone('${_m(lanes[k])['state']}')),
            ),
        ]),
      const SizedBox(height: AppSpacing.s),
      Text('Expected = the Risk Box answer saved when the trade opened. Actual = the real paper result. Report only.', style: context.type.metadata),
    ]);
  }
}
