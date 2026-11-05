import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../navigation/app_routes.dart';
import '../providers/app_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'owl_number.dart';

/// Plan B (picture ref3): DIAGNOSTICS (left) and SYSTEM LOAD (right) side by side, small. Real values only; a value that is not known shows "--".
/// Left: backend link, mode, latency, errors. Tap = the full Diagnostics page. Right: CPU ring, memory, REST calls per minute, from GET /api/system (same source as SystemLoadCard).
/// The old big DiagSection and SystemLoadCard are NOT deleted: they sit in the MORE fold under Diagnostics details. Dart NOT compiled (the APK build is the proof).
class DiagLoadRow extends StatefulWidget {
  const DiagLoadRow({super.key});

  @override
  State<DiagLoadRow> createState() => _DiagLoadRowState();
}

class _DiagLoadRowState extends State<DiagLoadRow> {
  Timer? _timer;
  Map<String, dynamic>? _data;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 6), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (!mounted || _busy) return;
    if (!TickerMode.of(context)) return; // tab not visible
    final life = WidgetsBinding.instance.lifecycleState;
    if (life != null && life != AppLifecycleState.resumed) return;
    _busy = true;
    final res = await context.read<AppProvider>().fetchSystem();
    _busy = false;
    if (!mounted) return;
    if (res != null && res.isNotEmpty) setState(() => _data = res); // a failed refresh keeps the last data
  }

  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static double? _n(dynamic v) => v is num ? v.toDouble() : null;

  Widget _box(BuildContext context, String title, List<Widget> children, {VoidCallback? onTap}) {
    final p = context.palette;
    final box = Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.cardPad),
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Row(children: [
          Expanded(child: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.label.copyWith(fontSize: 11, letterSpacing: 0.8, fontWeight: FontWeight.w700))),
          if (onTap != null) Icon(Icons.chevron_right_rounded, size: 16, color: p.textMuted),
        ]),
        const SizedBox(height: 6),
        ...children,
      ]),
    );
    if (onTap == null) return box;
    return GestureDetector(behavior: HitTestBehavior.opaque, onTap: onTap, child: box);
  }

  Widget _kv(BuildContext context, String k, String v, [Color? c]) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(children: [
        Text(k, style: context.type.metadata.copyWith(color: p.textMuted, fontSize: 11.5)),
        const SizedBox(width: 6),
        Expanded(child: Text(v, textAlign: TextAlign.right, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata.copyWith(color: c ?? p.textPrimary, fontSize: 11.5, fontWeight: FontWeight.w700))),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final pr = context.read<AppProvider>();
    final left = Selector<AppProvider, String>(
      selector: (_, x) => '${x.error}|${x.wsLatencyMs}|${x.recentApiErrors.length}|${x.status['last_error']}|${x.statsMode}|${x.status.isEmpty}',
      builder: (context, _, __) {
        final offline = pr.error != null;
        final known = pr.status.isNotEmpty;
        final lat = pr.wsLatencyMs;
        final errs = pr.recentApiErrors.length;
        return _box(context, 'DIAGNOSTICS', [
          _kv(context, 'Backend', offline ? 'Offline' : (known ? 'Connected' : '--'), offline ? p.loss : (known ? p.profit : p.textMuted)),
          _kv(context, 'Mode', known ? pr.statsMode.toUpperCase() : '--'),
          _kv(context, 'Latency', lat == null ? '--' : '$lat ms'),
          _kv(context, 'Bot error', !known ? '--' : (pr.status['last_error'] == null ? 'None' : 'Yes'), pr.status['last_error'] == null ? null : p.loss),
          _kv(context, 'API errors', known ? '$errs' : '--', errs > 0 ? p.warning : null),
        ], onTap: () => pr.goToRoute(AppRoute.diagnostics));
      },
    );

    final d = _data;
    final cpu = _n(_m(d?['cpu'])['backend_pct']);
    final rss = _n(_m(d?['mem'])['rss']);
    final perMin = _m(d?['rest'])['per_min'];
    final ringTone = cpu == null ? '' : (cpu >= 85 ? 'bad' : (cpu >= 60 ? '' : 'good'));
    final right = _box(context, 'SYSTEM LOAD', [
      Row(children: [
        if (cpu != null) OwlRing(fraction: cpu / 100.0, center: '${cpu.toStringAsFixed(0)}%', caption: 'CPU', tone: ringTone, size: 52),
        if (cpu == null) Expanded(child: _kv(context, 'CPU', '--')),
      ]),
      const SizedBox(height: 4),
      _kv(context, 'Memory', rss == null ? '--' : '${(rss / 1048576).toStringAsFixed(0)} MB'),
      _kv(context, 'REST/min', perMin == null ? '--' : '$perMin'),
    ]);

    return IntrinsicHeight(
      child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Expanded(child: left),
        const SizedBox(width: AppSpacing.cardGap),
        Expanded(child: right),
      ]),
    );
  }
}
