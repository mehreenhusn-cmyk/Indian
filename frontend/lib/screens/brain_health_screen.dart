import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import 'brain_health_cards.dart';

/// Part 90b + 90c (Brain Health): read-only, on the Part 90a route /api/v2/brain_health.
/// Shows the LEARNING PIPELINE (SIGNAL > PAPER TRADE > OUTCOME > HOLDOUT TEST > GRADUATION GATE, a step is lit only with evidence), the SAMPLE COVERAGE per market state
/// (closed paper trades against the 30-trade rule, 5m / 15m switch), the safety grid, the graduation checklist (cards in brain_health_cards.dart, Part 90c), the one honest headline sentence and the missing-data list.
/// Nothing here trades, saves or switches anything; LIVE stays locked. Dart NOT compiled (the APK build is the proof).
class BrainHealthScreen extends StatefulWidget {
  const BrainHealthScreen({super.key});

  @override
  State<BrainHealthScreen> createState() => _BrainHealthScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];

const Map<String, IconData> _stepIcons = {
  'signal': Icons.bar_chart,
  'paper': Icons.description_outlined,
  'outcome': Icons.show_chart,
  'holdout': Icons.science_outlined,
  'gate': Icons.school_outlined,
};

class _BrainHealthScreenState extends State<BrainHealthScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;
  String _iv = '5m';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchBrainHealth(_iv);
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  String _problem(Map<String, dynamic> r) {
    if (r['error'] != null) return '${r['error']}';
    switch (r['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the Brain Health route yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  bool _bad(Map<String, dynamic>? r) => r == null || r['state'] != null || r['error'] != null || r['ready'] != true;

  Widget _msg(AppPalette p, Map<String, dynamic>? r) {
    final note = r != null && r['ready'] == false && r['note'] != null ? '${r['note']}' : _problem(r ?? <String, dynamic>{'state': 'error'});
    return OWLCard(edge: p.warning, child: Text(note, style: TextStyle(fontSize: 13, color: p.textPrimary)));
  }

  Widget _title(AppPalette p, String t, [String? sub]) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
          if (sub != null) Text(sub, style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        ]),
      );

  Widget _step(AppPalette p, Map<String, dynamic> s) {
    final done = s['done'] == true;
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Container(
        width: 40,
        height: 40,
        decoration: BoxDecoration(shape: BoxShape.circle, color: done ? p.accent : p.surfaceHigher),
        child: Icon(_stepIcons['${s['key']}'] ?? Icons.circle_outlined, size: 20, color: done ? Colors.white : p.textMuted),
      ),
      const SizedBox(height: 6),
      Text('${s['title']}', textAlign: TextAlign.center, maxLines: 2, style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w800, color: done ? p.textPrimary : p.textMuted)),
      Text(done ? 'done' : 'not yet', textAlign: TextAlign.center, style: TextStyle(fontSize: 9.5, color: done ? p.profit : p.textMuted)),
    ]);
  }

  Widget _pipeline(AppPalette p, Map<String, dynamic> r) {
    final steps = _l(r['pipeline']);
    final kids = <Widget>[];
    for (var i = 0; i < steps.length; i++) {
      kids.add(Expanded(child: _step(p, steps[i])));
      if (i < steps.length - 1) kids.add(Icon(Icons.chevron_right, size: 14, color: p.textMuted));
    }
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'Learning pipeline', 'A step lights up only when there is evidence for it.'),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: kids),
      ]),
    );
  }

  Widget _box(AppPalette p, Map<String, dynamic> s, double w) {
    final n = (s['n'] as num?)?.toInt() ?? 0;
    final need = (s['need'] as num?)?.toInt() ?? 30;
    final ok = s['enough'] == true;
    final c = ok ? p.profit : p.warning;
    return Container(
      width: w,
      padding: const EdgeInsets.all(AppSpacing.m),
      decoration: BoxDecoration(color: p.surfaceElevated, borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 4), border: Border.all(color: p.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${s['label']}', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
        const SizedBox(height: 2),
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text('$n', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, color: p.textPrimary)),
          Text(' / $need', style: TextStyle(fontSize: 12, color: p.textMuted)),
        ]),
        const SizedBox(height: 6),
        LinearProgressIndicator(value: (n / need).clamp(0.0, 1.0).toDouble(), minHeight: 5, color: c, backgroundColor: p.surfaceHigher),
        const SizedBox(height: 4),
        Text(ok ? 'enough trades' : 'needs ${need - n} more', style: TextStyle(fontSize: 11, color: c)),
      ]),
    );
  }

  Widget _coverage(AppPalette p, Map<String, dynamic> r) {
    final cov = _m(r['coverage']);
    final states = _l(cov['states']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'Sample coverage', '${cov['total'] ?? 0} closed paper trades on $_iv'),
        Row(children: [
          for (final t in const ['5m', '15m'])
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(label: Text(t), selected: _iv == t, onSelected: (_) {
                if (_iv == t) return;
                _iv = t;
                _load();
              }),
            ),
        ]),
        const SizedBox(height: 8),
        LayoutBuilder(builder: (context, c) {
          final w = (c.maxWidth - 8) / 2;
          return Wrap(spacing: 8, runSpacing: 8, children: [for (final s in states) _box(p, s, w)]);
        }),
        const SizedBox(height: 8),
        Text('${cov['rule'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }

  Widget _headline(AppPalette p, Map<String, dynamic> r) {
    final h = _m(r['headline']);
    final ready = h['verdict'] == 'CHECKS PASS';
    return OWLCard(
      edge: ready ? p.profit : p.warning,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${h['title'] ?? ''}', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 4),
        Text('${h['text'] ?? ''}', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    } else if (_bad(r)) {
      kids = [_msg(p, r)];
    } else {
      kids = [_pipeline(p, r!), _coverage(p, r), BrainSafetyCard(data: r), BrainGraduationCard(data: r), _headline(p, r), BrainMissingCard(data: r)];
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.l),
        children: [
          Text('Data. Discipline. Safer decisions.', style: TextStyle(fontSize: 12.5, color: p.textMuted)),
          const SizedBox(height: AppSpacing.m),
          for (final k in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: k),
        ],
      ),
    );
  }
}
