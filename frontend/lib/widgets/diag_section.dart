import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/diag_status.dart';
import '../providers/app_provider.dart';
import '../screens/app_problems_screen.dart';
import '../screens/system_health_screen.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'diagnostics_card.dart';
import 'owl_card.dart';
import 'owl_pressable.dart';
import 'owl_route.dart';
import 'owl_sub_page.dart';
import 'system_load_card.dart';

/// R28c (Part 10): the DIAGNOSTICS section lower on the Dashboard (owner rule 31: Diagnostics is NOT removed, it moved from the bottom bar into the Dashboard, organized, leaks stay visible).
/// Four labelled groups, each loaded on its own so one missing route never hides the others:
///   1 CONNECTIONS  the 6 live checks (backend, WebSocket, market data, scanner, strategy, execution) from buildDiagStatus: green / amber / red / grey (grey = not known, never a made-up green)
///   2 LEAKS        GET /api/v2/app_problems: BAD / WARN counts + the 3 worst lines; tap = the full App Problems page (copy for Claude)
///   3 THIS APP     the app's own failed or slow fetches (AppErrorLog, memory only)
///   4 SNIPER       GET /api/v2/sniper_health overall (OK / WARN / BAD)
/// Below: a closed fold DETAILS with the old engineering card (DiagnosticsCard) and the system load card, moved here from the MORE fold (nothing deleted). Link: Full diagnostics = the old Diagnostics page. Read only. Dart NOT compiled.
Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(Object? v) => v is List ? v : const [];
int _i(Object? v) => v is num ? v.toInt() : 0;

class DiagSection extends StatefulWidget {
  const DiagSection({super.key});

  @override
  State<DiagSection> createState() => _DiagSectionState();
}

class _DiagSectionState extends State<DiagSection> {
  Map<String, dynamic>? _prob, _snip, _slow;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final pr = context.read<AppProvider>();
    pr.fetchAppProblems().then((r) {
      if (mounted) setState(() => _prob = r);
    });
    pr.fetchSniperHealth().then((r) {
      if (mounted) setState(() => _snip = r);
    });
    pr.fetchSlowCalls().then((r) {
      if (mounted) setState(() => _slow = r);
    });
  }

  Color _c(AppPalette p, DiagLevel l) => l == DiagLevel.ok ? p.profit : (l == DiagLevel.warn ? p.warning : (l == DiagLevel.bad ? p.loss : p.textMuted));

  Color _sev(AppPalette p, String s) => s == 'BAD' ? p.loss : (s == 'WARN' ? p.warning : p.textMuted);

  Widget _group(BuildContext context, String name, {String? right, Color? rightColor, VoidCallback? onTap}) {
    final p = context.palette;
    final row = Padding(
      padding: const EdgeInsets.only(top: AppSpacing.m, bottom: 4),
      child: Row(children: [
        Expanded(child: Text(name, style: context.type.label.copyWith(letterSpacing: 1.0))),
        if (right != null) Text(right, style: context.type.metadata.copyWith(color: rightColor ?? p.textMuted, fontWeight: FontWeight.w700)),
        if (onTap != null) Icon(Icons.chevron_right_rounded, size: 18, color: p.textMuted),
      ]),
    );
    return onTap == null ? row : OWLPressable(pressedScale: 0.99, onTap: onTap, child: row);
  }

  Widget _dotRow(BuildContext context, Color c, String title, String detail) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(margin: const EdgeInsets.only(top: 5), width: 8, height: 8, decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
          const SizedBox(width: 8),
          SizedBox(width: 96, child: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.primary.copyWith(fontWeight: FontWeight.w600))),
          Expanded(child: Text(detail, maxLines: 2, overflow: TextOverflow.ellipsis, style: context.type.metadata)),
        ]),
      );

  /// Part 2: SLOW CALLS = which backend calls are still waiting right now and which routes keep the phone busy. One short line each, nothing invented.
  Widget _slowCalls(BuildContext context, AppPalette p) {
    final d = _m(_slow);
    if (_slow == null) return Text('Loading...', style: context.type.metadata);
    if ('${d['state']}' != 'OK') return Text('Not available from this backend (update the backend).', style: context.type.metadata);
    final w = _l(d['waiting']), tp = _l(d['top']);
    final rows = <Widget>[];
    for (final x in w.take(2)) {
      rows.add(_dotRow(context, p.loss, 'waiting', '${_m(x)['route']} for ${_i(_m(x)['waiting_sec'])} s'));
    }
    for (final x in tp.take(3)) {
      final t = _m(x);
      rows.add(_dotRow(context, p.textMuted, 'busy', '${t['route']}: ${t['per_min']}/min, avg ${_i(t['avg_ms'])} ms, ${t['busy_sec_min']} s per minute'));
    }
    if (rows.isEmpty) return Text('${d['headline'] ?? 'No slow calls.'}', style: context.type.metadata);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: rows);
  }

  void _openProblems() => Navigator.of(context).push(OwlRoute(builder: (_) => const AppProblemsScreen()));

  void _openFull() => Navigator.of(context).push(OwlRoute(builder: (_) => const OwlSubPage(title: 'Diagnostics', child: SystemHealthScreen())));

  Widget _leaks(BuildContext context) {
    final p = context.palette;
    final d = _prob;
    final st = d == null ? '' : '${d['state']}';
    if (d == null) return Text('Loading...', style: context.type.metadata);
    if (st != 'OK' && st != 'PROBLEMS') {
      return Text(st == 'off' ? 'The V2 data API is off.' : (st == 'busy' ? 'The backend is still building this list.' : 'Not available from this backend (update the backend or check the link).'), style: context.type.metadata);
    }
    final items = _l(d['items']);
    if (items.isEmpty) return Text('${d['headline'] ?? 'No problems found.'}', style: context.type.metadata);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final it in items.take(3)) _dotRow(context, _sev(p, '${_m(it)['sev']}'), '${_m(it)['area'] ?? ''}', '${_m(it)['text'] ?? ''}'),
      if (items.length > 3) Padding(padding: const EdgeInsets.only(top: 2), child: Text('+${items.length - 3} more in All problems', style: context.type.metadata)),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final prov = context.read<AppProvider>();
    return Selector<AppProvider, String>(
      selector: (_, x) => buildDiagStatus(x).items.map((i) => i.level.index).join(),
      builder: (context, _, __) {
        final ds = buildDiagStatus(prov);
        final counts = _m(_m(_prob)['counts']);
        final bad = _i(counts['BAD']), warn = _i(counts['WARN']);
        final worst = ds.overall == DiagLevel.bad || bad > 0 ? DiagLevel.bad : (ds.overall == DiagLevel.warn || warn > 0 ? DiagLevel.warn : ds.overall);
        final word = worst == DiagLevel.ok ? 'ALL OK' : (worst == DiagLevel.warn ? 'WATCH' : (worst == DiagLevel.bad ? 'PROBLEM' : 'UNKNOWN'));
        final errs = AppErrorLog.items;
        final sh = _m(_snip);
        final shLevel = '${sh['overall'] ?? ''}';
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('DIAGNOSTICS', style: context.type.section.copyWith(fontWeight: FontWeight.w800))),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
              decoration: BoxDecoration(color: _c(p, worst).withOpacity(0.14), borderRadius: BorderRadius.circular(AppSpacing.radiusPill)),
              child: Text(word, style: context.type.metadata.copyWith(color: _c(p, worst), fontWeight: FontWeight.w800)),
            ),
          ]),
          const SizedBox(height: AppSpacing.s),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(AppSpacing.l, 0, AppSpacing.l, AppSpacing.m),
            decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _group(context, 'CONNECTIONS', right: '${ds.count(DiagLevel.ok)} of ${ds.items.length} OK'),
              for (final i in ds.items) _dotRow(context, _c(p, i.level), i.title, i.detail),
              _group(context, 'LEAKS', right: _prob == null ? '' : '$bad bad, $warn warn', rightColor: bad > 0 ? p.loss : (warn > 0 ? p.warning : p.profit), onTap: _openProblems),
              _leaks(context),
              _group(context, 'THIS APP', right: errs.isEmpty ? 'no failed fetch' : '${errs.length} failed / slow', rightColor: errs.isEmpty ? p.profit : p.warning),
              for (final e in errs.take(2)) _dotRow(context, e.slow ? p.warning : p.loss, e.path.split('/').last, e.what),
              if (errs.isEmpty) Text('Since the app started, every fetch answered in time.', style: context.type.metadata),
              _group(context, 'SLOW CALLS', right: _slow == null ? '' : (_l(_m(_slow)['waiting']).isNotEmpty ? '${_l(_m(_slow)['waiting']).length} waiting' : (_l(_m(_slow)['slow']).isNotEmpty ? 'slow' : 'ok')), rightColor: _l(_m(_slow)['waiting']).isNotEmpty ? p.loss : (_l(_m(_slow)['slow']).isNotEmpty ? p.warning : p.profit)),
              _slowCalls(context, p),
              _group(context, 'SNIPER', right: shLevel.isEmpty ? '' : shLevel, rightColor: shLevel == 'OK' ? p.profit : (shLevel == 'WARN' ? p.warning : (shLevel == 'BAD' ? p.loss : null))),
              Text(_snip == null ? 'Loading...' : (shLevel.isEmpty ? 'Sniper health is not available from this backend yet.' : 'Model, scan, candles and switches: ${shLevel == 'OK' ? 'all fine' : 'open Full diagnostics for the detail'}.'), style: context.type.metadata),
              const SizedBox(height: AppSpacing.s),
              Row(children: [
                Expanded(child: OWLPressable(pressedScale: 0.98, onTap: _openProblems, child: Text('All problems', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)))),
                OWLPressable(pressedScale: 0.98, onTap: _openFull, child: Text('Full diagnostics', style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
              ]),
            ]),
          ),
          const SizedBox(height: AppSpacing.cardGap),
          const OwlFold(title: 'DETAILS', headline: 'Engineering numbers, system load', bare: true, children: [DiagnosticsCard(), SystemLoadCard()]),
        ]);
      },
    );
  }
}
