import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_number.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_sentence.dart';

/// Part 17c: DATA AND LEARNING. One page that shows the things which were built but had no screen (everything is read only, paper money):
///  1. Live-test gate (v2_graduation.py): 7 checks per arm (Dual Bot trades, Brain own trades), verdict pill, tap = the 7 checks.
///  2. Automatic runs (v2_lab_auto.py): when the Scalp Lab and the Knowledge Ledger were filled by themselves last time.
///  3. Sniper learns from (route sniper_bridge): examples per source, sources never added together.
///  4. Dual Bot side data: Price Action layer, Volume layer, coin sources, archive check.
/// A row that cannot be read says so in words (off / old backend / no answer), never a made-up number. Dart NOT compiled.
class DataSourcesScreen extends StatefulWidget {
  const DataSourcesScreen({super.key});

  @override
  State<DataSourcesScreen> createState() => _DataSourcesScreenState();
}

class _DataSourcesScreenState extends State<DataSourcesScreen> {
  List<Map<String, dynamic>>? _r; // grad, bridge, pa, vol, universe, archive

  static Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final a = context.read<AppProvider>();
    final r = await Future.wait([a.fetchGradDual(), a.fetchSniperBridge(), a.fetchLayerPa(), a.fetchLayerVol(), a.fetchDualUniverse(), a.fetchArchiveCheck()]);
    if (mounted) setState(() => _r = r);
  }

  static String _problem(Map<String, dynamic> d) {
    final s = '${d['state']}';
    if (s == 'off') return 'The V2 data API is switched off.';
    if (s == 'old') return 'This backend does not have this route yet. Install the newest backend zip and restart.';
    if (s == 'busy') return 'Still being built. Pull down in a minute.';
    return 'Cannot read this right now. Pull down to try again.';
  }

  static bool _bad(Map<String, dynamic> d) => d['state'] == 'off' || d['state'] == 'old' || d['state'] == 'error' || d['state'] == 'busy';

  static String _ago(Object? ts) {
    final t = ts is num ? ts.toInt() : 0;
    if (t <= 0) return 'not yet';
    final s = DateTime.now().millisecondsSinceEpoch ~/ 1000 - t;
    if (s < 3600) return '${s ~/ 60} min ago';
    if (s < 172800) return '${s ~/ 3600} h ago';
    return '${s ~/ 86400} days ago';
  }

  void _sheet(String title, List<Widget> body, {String? pill, String tone = ''}) {
    final p = context.palette;
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: p.surface,
      isScrollControlled: true,
      builder: (ctx) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.l),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              Expanded(child: Text(title, style: ctx.type.section)),
              if (pill != null) OwlPill(pill, tone: tone),
            ]),
            const SizedBox(height: AppSpacing.m),
            ...body,
            Text('Report only. Nothing is switched or traded from here.', style: ctx.type.metadata),
          ]),
        ),
      ),
    );
  }

  Widget _line(String t) => Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(t, style: context.type.secondary.copyWith(height: 1.35)));

  // ---- 1. live-test gate -------------------------------------------------------------------------------------------------------------
  static String _verdictWord(String v) => v == 'GATE PASSED' ? 'PASSED' : v == 'NOT READY' ? 'NOT READY' : 'WAITING';

  static String _verdictTone(String v) => v == 'GATE PASSED' ? 'good' : v == 'NOT READY' ? 'bad' : 'warn';

  Widget _grad(Map<String, dynamic> d) {
    if (_bad(d)) return Text(_problem(d), style: context.type.secondary);
    final arms = _m(_m(d['grad'])['arms']);
    if (arms.isEmpty) return Text('No report yet.', style: context.type.secondary);
    const names = {'current_bot': 'Dual Bot (current bot)', 'brain_own': 'Brain own paper trades'};
    return OwlListCard(children: [
      for (final k in arms.keys)
        () {
          final a = _m(arms[k]);
          final v = '${a['verdict']}';
          final n = _m(a['numbers'])['trades'] ?? 0;
          final checks = a['checks'] is List ? (a['checks'] as List).map(_m).toList() : <Map<String, dynamic>>[];
          return OwlRow(
            title: names[k] ?? k,
            sub: 'pass ${a['passed'] ?? 0}, fail ${a['failed'] ?? 0}, wait ${a['waiting'] ?? 0}, $n trades',
            trailing: OwlPill(_verdictWord(v), tone: _verdictTone(v)),
            onTap: () => _sheet(names[k] ?? k, [
              for (final c in checks) _line('${c['state'] == 'pass' ? 'PASS' : c['state'] == 'fail' ? 'FAIL' : 'WAIT'}  ${c['label']}: ${c['value']} (needs ${c['need']})'),
              _line('PASSED does not switch anything and is not a promise. A tiny live test needs your own OK and a daily loss cap.'),
            ], pill: _verdictWord(v), tone: _verdictTone(v)),
          );
        }(),
    ]);
  }

  // ---- 2. automatic runs -------------------------------------------------------------------------------------------------------------
  Widget _auto(Map<String, dynamic> d) {
    if (_bad(d)) return Text(_problem(d), style: context.type.secondary);
    final au = _m(d['auto']);
    final steps = _m(au['steps']);
    final fail = steps.values.any((s) => _m(s)['ok'] == false);
    return OwlListCard(children: [
      OwlRow(
        title: 'Scalp Lab and Ledger fill',
        sub: au.isEmpty ? 'Not run yet. The first run comes about 5 minutes after the runner starts.' : 'Last run ${_ago(au['last_run_ts'])}, every ${au['every_hours'] ?? 6} h',
        trailing: OwlPill(au.isEmpty ? 'WAITING' : fail ? 'CHECK' : 'AUTO', tone: au.isEmpty ? 'warn' : fail ? 'bad' : 'good'),
        onTap: au.isEmpty
            ? null
            : () => _sheet('Automatic runs', [
                  for (final k in steps.keys) _line('${k == 'scalp_lab' ? 'Scalp Lab' : 'Knowledge Ledger'}: ${_m(steps[k])['ok'] == true ? '' : 'FAILED. '}${_m(steps[k])['note']}'),
                  _line('Switch it off: create an empty file v2_lab_auto_off in the data folder.'),
                ]),
      ),
    ]);
  }

  // ---- 3. Sniper learns from ---------------------------------------------------------------------------------------------------------
  Widget _bridge(Map<String, dynamic> d) {
    if (_bad(d)) return Text(_problem(d), style: context.type.secondary);
    final by = _m(d['by_source']);
    if (by.isEmpty) return Text(d['lines'] is List && (d['lines'] as List).isNotEmpty ? '${(d['lines'] as List).first}' : 'No examples from the other bots yet.', style: context.type.secondary);
    const names = {'dual': 'Dual Bot trades', 'brain': 'Brain trades', 'main': 'Main bot trades'};
    final lines = [for (final x in (d['lines'] is List ? d['lines'] as List : const [])) '$x'];
    return OwlListCard(children: [
      for (final k in by.keys)
        OwlRow(
          title: names[k] ?? k,
          sub: '${_m(by[k])['records'] ?? 0} trades read, ${_m(by[k])['examples'] ?? 0} usable examples',
          onTap: () => _sheet('Sniper learns from: ${names[k] ?? k}', [for (final l in lines) _line(l)]),
        ),
    ]);
  }

  // ---- 4. Dual Bot side data ---------------------------------------------------------------------------------------------------------
  Widget _layer(String title, Map<String, dynamic> d) {
    final run = d['running'] == true;
    final err = '${d['error'] ?? ''}';
    final rep = _m(d['report']);
    final facts = [for (final e in rep.entries) if (e.value is num || e.value is String || e.value is bool) '${e.key}: ${e.value}'].take(12).toList();
    return OwlRow(
      title: title,
      sub: err.isNotEmpty ? err : (run ? 'Running' : 'Not running (starts when the Dual Bot works)'),
      trailing: OwlPill(run ? 'RUNNING' : 'IDLE', tone: run ? 'good' : ''),
      onTap: facts.isEmpty ? null : () => _sheet(title, [for (final f in facts) _line(f)]),
    );
  }

  Widget _side(Map<String, dynamic> pa, Map<String, dynamic> vol, Map<String, dynamic> uni, Map<String, dynamic> arc) {
    if (_bad(pa) && _bad(vol) && _bad(uni) && _bad(arc)) return Text(_problem(pa), style: context.type.secondary);
    final days = uni['days'] is List ? (uni['days'] as List).length : 0;
    final st = '${arc['state']}';
    return OwlListCard(children: [
      if (!_bad(pa)) _layer('Price Action layer', pa),
      if (!_bad(vol)) _layer('Volume layer', vol),
      if (!_bad(uni))
        OwlRow(
          title: 'Dual Bot coin sources',
          sub: '${uni['saved_days'] ?? days} day lists saved, cap ${uni['cap'] ?? '?'}${'${uni['err'] ?? ''}'.isEmpty ? '' : ', error: ${uni['err']}'}',
        ),
      if (!_bad(arc))
        OwlRow(
          title: 'Archive check',
          sub: '${arc['text'] ?? ''}',
          trailing: OwlPill(st == 'match' ? 'MATCH' : st == 'differ' ? 'DIFFERENT' : st == 'error' ? 'ERROR' : 'NONE', tone: st == 'match' ? 'good' : st == 'differ' || st == 'error' ? 'bad' : ''),
        ),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final r = _r;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.m, AppSpacing.l, AppSpacing.xl),
        children: [
          const OwlSentence('What teaches the Sniper, and when a live test is allowed', lines: ['Read only. All numbers are paper money.']),
          if (r == null)
            const Padding(padding: EdgeInsets.only(top: AppSpacing.l), child: OwlRowSkeleton(rows: 4))
          else ...[
            const OwlSectionLabel('Live-test gate (paper)'),
            _grad(r[0]),
            const OwlSectionLabel('Automatic runs'),
            _auto(r[0]),
            const OwlSectionLabel('Sniper learns from'),
            _bridge(r[1]),
            const OwlSectionLabel('Dual Bot side data'),
            _side(r[2], r[3], r[4], r[5]),
          ],
        ],
      ),
    );
  }
}
