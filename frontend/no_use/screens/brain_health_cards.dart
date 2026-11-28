import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 90c (Brain Health, screen part 2 of 2): the three cards under the pipeline and the coverage boxes, all read-only, all fed by the Part 90a answer of /api/v2/brain_health.
/// BrainSafetyCard = the safety chips of the guard (kill switch, daily loss cap, max open trades, ...) + the auto-runner (last 5-minute tick).
/// BrainGraduationCard = PAPER / SHADOW / LIVE. LIVE always says OFF: no card, button or check here can switch anything.
/// BrainMissingCard = plain lines about what to collect next. A check that is not built or not measured says so (NOT_CHECKED / WAIT / PENDING), never a made-up PASS.
/// Dart NOT compiled (the APK build is the proof).

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];

const Map<String, String> _titles = {
  'no_lookahead': 'No look-ahead',
  'data_quality': 'Data quality',
  'stale_data_pause': 'Stale-data pause',
  'kill_switch': 'Kill switch',
  'daily_loss_cap': 'Daily loss cap',
  'max_open_trades': 'Max open trades',
  'reconciliation': 'Reconciliation',
  'decision_version': 'Decision version',
};

Color _stateColor(AppPalette p, String s) {
  switch (s) {
    case 'PASS':
    case 'RUNNING':
      return p.profit;
    case 'FAIL':
    case 'TRIPPED':
    case 'OFF':
      return p.loss;
    case 'ARMED':
    case 'WARN':
    case 'WAIT':
    case 'PENDING':
    case 'STALE':
    case 'NOT_RUNNING':
    case 'NOT_CHECKED':
      return p.warning;
    default:
      return p.accent;
  }
}

Widget _pill(AppPalette p, String s) {
  final c = _stateColor(p, s);
  return Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
    decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(AppSpacing.radiusPill), border: Border.all(color: c.withOpacity(0.5))),
    child: Text(s.replaceAll('_', ' '), style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: c)),
  );
}

Widget _tile(AppPalette p, String title, String state, String note, double w) => Container(
      width: w,
      padding: const EdgeInsets.all(AppSpacing.m),
      decoration: BoxDecoration(color: p.surfaceElevated, borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 4), border: Border.all(color: p.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textPrimary)),
        const SizedBox(height: 6),
        _pill(p, state),
        const SizedBox(height: 6),
        Text(note, style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );

Widget _head(AppPalette p, String t, String sub) => Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(t, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
        Text(sub, style: TextStyle(fontSize: 11.5, color: p.textMuted)),
      ]),
    );

class BrainSafetyCard extends StatelessWidget {
  final Map<String, dynamic> data;
  const BrainSafetyCard({super.key, required this.data});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final safety = _m(data['safety']);
    final run = _m(data['runner']);
    final chips = _l(safety['chips']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(p, 'Safety and data integrity', 'Live is ${data['live'] ?? 'LOCKED'}. The limits are starting values, not validated; you may change them.'),
        if (chips.isEmpty) Text('${safety['note'] ?? 'No safety information yet.'}', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
        LayoutBuilder(builder: (context, c) {
          final w = (c.maxWidth - 8) / 2;
          return Wrap(spacing: 8, runSpacing: 8, children: [
            for (final x in chips) _tile(p, _titles['${x['key']}'] ?? '${x['key']}', '${x['state']}', '${x['note'] ?? ''}', w),
            if (run.isNotEmpty) _tile(p, 'Auto-runner', '${run['state']}', '${run['note'] ?? ''}', w),
          ]);
        }),
      ]),
    );
  }
}

class BrainGraduationCard extends StatelessWidget {
  final Map<String, dynamic> data;
  const BrainGraduationCard({super.key, required this.data});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final g = _l(data['graduation']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(p, 'Graduation checklist', 'PAPER first, then SHADOW. LIVE needs every check and then your own OK.'),
        LayoutBuilder(builder: (context, c) {
          final w = (c.maxWidth - 16) / 3;
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (var i = 0; i < g.length; i++) ...[
              if (i > 0) const SizedBox(width: 8),
              _tile(p, '${g[i]['label']}', '${g[i]['state']}', '${g[i]['note'] ?? ''}', w),
            ],
          ]);
        }),
      ]),
    );
  }
}

class BrainMissingCard extends StatelessWidget {
  final Map<String, dynamic> data;
  const BrainMissingCard({super.key, required this.data});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final xs = data['missing'] is List ? [for (final e in data['missing'] as List) '$e'] : <String>[];
    return OWLCard(
      edge: xs.isEmpty ? p.profit : p.warning,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(p, 'Missing / insufficient data', xs.isEmpty ? 'Nothing is missing right now.' : '${xs.length} thing(s) to collect'),
        for (final s in xs)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('- ', style: TextStyle(fontSize: 12.5, color: p.textMuted)),
              Expanded(child: Text(s, style: TextStyle(fontSize: 12.5, color: p.textPrimary))),
            ]),
          ),
      ]),
    );
  }
}
