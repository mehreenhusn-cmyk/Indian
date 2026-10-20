import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../services/jank_meter.dart';
import '../theme/app_theme.dart';

/// "Where is the load?" sheet (Backend panel > LOAD REPORT). One look answers: is the backend slow, is the phone busy,
/// or is the app screen itself choppy. COPY puts a plain-text report on the clipboard that any AI can read with no other context.
/// Numbers: backend /api/load_report (load_report.py) + this phone's frame counter (jank_meter.dart).
Future<void> showLoadReportSheet(BuildContext context) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (_) => const _LoadReportSheet(),
  );
}

class _LoadReportSheet extends StatefulWidget {
  const _LoadReportSheet();

  @override
  State<_LoadReportSheet> createState() => _LoadReportSheetState();
}

class _LoadReportSheetState extends State<_LoadReportSheet> {
  double _hours = 4;
  Map<String, dynamic>? _r;
  List<dynamic> _days = const [];
  bool _loading = true;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _failed = false;
    });
    final pr = context.read<AppProvider>();
    final r = await pr.fetchLoadReport(_hours);
    final days = await pr.fetchLoadDaily();
    if (!mounted) return;
    setState(() {
      _r = r;
      _days = days;
      _failed = r == null;
      _loading = false;
    });
  }

  Color _lc(AppPalette p, String level) => level == 'bad' ? p.loss : (level == 'warn' ? p.warning : p.profit);

  String _copyText() {
    final r = _r;
    final app = JankMeter.instance.summary(_hours)['text'];
    if (r == null) return 'OWL load report: backend NOT ANSWERING.\n$app';
    return '${r['text'] ?? ''}\n\n$app';
  }

  Widget _meter(AppPalette p, AppText t, String label, String value, num score, String level, String hint) {
    final c = _lc(p, level);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Expanded(child: Text(label, style: TextStyle(color: p.textPrimary, fontSize: 12.5, fontWeight: FontWeight.w800))),
            Text(level == 'ok' ? 'GOOD' : (level == 'warn' ? 'WATCH' : 'BAD'), style: TextStyle(color: c, fontSize: 10.5, fontWeight: FontWeight.w800)),
          ]),
          const SizedBox(height: 4),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(value: (score / 100).clamp(0.0, 1.0).toDouble(), minHeight: 6, backgroundColor: p.border, color: c),
          ),
          const SizedBox(height: 3),
          Text(value, style: t.metadata.copyWith(color: p.textPrimary, fontSize: 11.5)),
          Text(hint, style: t.metadata.copyWith(fontSize: 10.5)),
        ],
      ),
    );
  }

  Widget _card(AppPalette p, {required Widget child, Color? glow}) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: glow != null ? glow.withOpacity(0.5) : p.border),
      ),
      child: child,
    );
  }

  Widget _label(AppText t, String s) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(s, style: t.metadata.copyWith(fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.7)),
      );

  Widget _hoursChip(AppPalette p, String text, double h) {
    final on = _hours == h;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ChoiceChip(
        label: Text(text),
        selected: on,
        onSelected: (_) {
          setState(() => _hours = h);
          _load();
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final r = _r;
    final app = JankMeter.instance.summary(_hours);
    final verdict = (r != null && r['verdict'] is Map) ? Map<String, dynamic>.from(r['verdict'] as Map) : <String, dynamic>{};
    final meters = (r != null && r['meters'] is List) ? (r['meters'] as List).whereType<Map>().toList() : <Map>[];
    final slow = (r != null && r['slow'] is List) ? (r['slow'] as List).whereType<Map>().toList() : <Map>[];
    final stalls = (r != null && r['stalls'] is List) ? (r['stalls'] as List).whereType<Map>().toList() : <Map>[];
    final vLevel = (verdict['level'] ?? 'ok').toString();

    return DraggableScrollableSheet(
      initialChildSize: 0.88,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      expand: false,
      builder: (ctx, scroll) => Container(
        decoration: BoxDecoration(color: p.bg, borderRadius: const BorderRadius.vertical(top: Radius.circular(22))),
        child: ListView(
          controller: scroll,
          padding: const EdgeInsets.fromLTRB(14, 10, 14, 24),
          children: [
            Center(child: Container(width: 38, height: 4, decoration: BoxDecoration(color: p.border, borderRadius: BorderRadius.circular(2)))),
            const SizedBox(height: 10),
            Row(children: [
              Expanded(child: Text('Load report', style: TextStyle(color: p.textPrimary, fontSize: 20, fontWeight: FontWeight.w800))),
              TextButton(
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: _copyText()));
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Report copied. Paste it to any AI.')));
                },
                child: const Text('COPY REPORT'),
              ),
            ]),
            Row(children: [_hoursChip(p, '1 hour', 1), _hoursChip(p, '4 hours', 4), _hoursChip(p, '24 hours', 24)]),
            const SizedBox(height: 10),
            if (_loading)
              const Padding(padding: EdgeInsets.all(30), child: Center(child: CircularProgressIndicator(strokeWidth: 2)))
            else if (_failed)
              _card(p,
                  glow: p.loss,
                  child: Text('The backend did not answer, so no backend report. Open Termux and run:  bash ~/owl_auto.sh status\n\n${app['text']}',
                      style: t.metadata.copyWith(color: p.textPrimary, height: 1.4)))
            else ...[
              _card(
                p,
                glow: _lc(p, vLevel),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  _label(t, 'MAIN BOTTLENECK  ·  LAST ${_hours.toStringAsFixed(0)} H'),
                  Text((verdict['title'] ?? '-').toString(), style: TextStyle(color: _lc(p, vLevel), fontSize: 17, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 6),
                  Text((verdict['why'] ?? '').toString(), style: t.metadata.copyWith(color: p.textPrimary, height: 1.4, fontSize: 12)),
                  if ((verdict['fix'] ?? '').toString().isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text('What to do: ${verdict['fix']}', style: t.metadata.copyWith(height: 1.4, fontSize: 11.5)),
                  ],
                ]),
              ),
              if (meters.isNotEmpty)
                _card(p, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  _label(t, 'BACKEND METERS  (0 = fine, 100 = bad)'),
                  for (final m in meters)
                    _meter(p, t, (m['label'] ?? '').toString(), (m['value'] ?? '').toString(), (m['score'] is num) ? m['score'] as num : 0, (m['level'] ?? 'ok').toString(), (m['hint'] ?? '').toString()),
                ])),
              _card(p, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                _label(t, 'APP SCREEN  (this phone)'),
                _meter(p, t, 'Choppy frames', (app['text'] ?? '').toString(), (app['score'] is num) ? app['score'] as num : 0, (app['level'] ?? 'ok').toString(),
                    'If this is bad but the backend is good, the slowness is inside the app screen.'),
              ])),
              if (stalls.isNotEmpty)
                _card(p, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  _label(t, 'WHERE THE BACKEND FROZE'),
                  for (final s in stalls)
                    Padding(padding: const EdgeInsets.only(bottom: 4), child: Text('${s['n']}x  ${s['where']}', style: t.metadata.copyWith(color: p.warning, fontSize: 11))),
                ])),
              if (slow.isNotEmpty)
                _card(p, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  _label(t, 'SLOWEST ANSWERS TO THE APP'),
                  for (final s in slow)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Text('${s['ep']}\n${s['calls']} calls · typical ${s['avg_ms']} ms · slowest ${s['max_ms']} ms · total ${s['total_s']} s',
                          style: t.metadata.copyWith(color: p.textPrimary, fontSize: 11, height: 1.3)),
                    ),
                ])),
              if (_days.isNotEmpty)
                _card(p, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  _label(t, 'DAILY SUMMARY'),
                  for (final d in _days.reversed.take(7))
                    if (d is Map)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 5),
                        child: Text('${d['day']}  ·  ${d['title']}', style: t.metadata.copyWith(color: p.textPrimary, fontSize: 11.5)),
                      ),
                ])),
              Text('Samples: ${r?['samples'] ?? 0} (one every 30 seconds, kept 26 hours). The first minutes after a restart have little data.',
                  style: t.metadata.copyWith(fontSize: 10.5, height: 1.35)),
            ],
          ],
        ),
      ),
    );
  }
}
