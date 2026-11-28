import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_button.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_row.dart';

// Part 8B-1 (README_FILTER): shared helpers for every Filter Lab tab (Fakes, Moves now; Filters, Exits, Decisions in 8B-2). Public names start with fl.
Map<String, dynamic> flM(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> flMl(dynamic v) => v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
double flN(dynamic v) => v is num ? v.toDouble() : 0.0;
String flS(dynamic v) => v == null ? '' : '$v';
bool flHas(dynamic v) => v is num;

/// "12.5%" or "-" when the number is missing.
String flPct(dynamic v) => v is num ? '${v.toStringAsFixed(1)}%' : '-';

/// "+1.20" / "-0.40" USDT.
String flUsdt(dynamic v) => v is num ? '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}' : '-';

/// Durations over 60 min are written as hours + minutes (owner rule), never "220 min".
String flDur(num sec) {
  final mins = (sec / 60).round();
  if (mins < 1) return '${sec.round()} s';
  if (mins < 60) return '$mins min';
  final h = mins ~/ 60, m = mins % 60;
  return m == 0 ? '$h h' : '$h h $m min';
}

String flAgo(dynamic ts) {
  if (ts is! num) return 'never';
  final sec = DateTime.now().millisecondsSinceEpoch / 1000 - ts;
  return sec < 60 ? 'just now' : '${flDur(sec)} ago';
}

/// Small grey line under a block: a bucket with fewer trades than the backend minimum says NOT ENOUGH DATA; the app shows it as a muted tag.
bool flThin(Map<String, dynamic> b) => flS(b['label']) == 'NOT ENOUGH DATA';

/// One row of a bucket table: title = bucket name, sub = the small facts, trailing = the one number that matters.
Widget flRow(BuildContext context, String title, String sub, String trailing, {Color? color}) {
  return OwlRow(title: title, sub: sub, trailing: Text(trailing, style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: color)));
}

Widget flNote(BuildContext context, String text, {bool bad = false}) {
  final p = context.palette;
  return OWLCard(edge: bad ? p.warning : null, padding: const EdgeInsets.all(AppSpacing.m), child: Text(text, style: context.type.secondary));
}

/// Loads the saved summaries of the given Parts ONE AT A TIME (a summary can be a few hundred KB) from GET /api/v2/filter_part?id= and hands them to [builder].
/// builder gets {id: data map} of the Parts that were found; a Part that was not made yet is simply missing from the map ([missing] lists those ids).
/// The last good answer of each Part is kept for the app session (static cache), pull-down or the Reload button loads again. Never throws.
class FilterPartView extends StatefulWidget {
  final List<String> ids;
  final Widget Function(BuildContext context, Map<String, Map<String, dynamic>> data, List<String> missing) builder;

  const FilterPartView({super.key, required this.ids, required this.builder});

  @override
  State<FilterPartView> createState() => _FilterPartViewState();
}

class _FilterPartViewState extends State<FilterPartView> {
  static final Map<String, Map<String, dynamic>> _cache = {}; // id -> {saved_ts, data}
  bool _loading = false;
  String _err = '';

  bool get _all => widget.ids.every(_cache.containsKey);

  @override
  void initState() {
    super.initState();
    if (!_all) _load();
  }

  Future<void> _load() async {
    if (_loading) return;
    setState(() {
      _loading = true;
      _err = '';
    });
    final pr = context.read<AppProvider>();
    String err = '';
    for (final id in widget.ids) {
      final r = await pr.fetchFilterPart(id);
      if (!mounted) return;
      if (r['data'] is Map) {
        _cache[id] = {'saved_ts': r['saved_ts'], 'data': r['data']};
      } else if (r['state'] == 'none') {
        _cache.remove(id);
      } else if (r['state'] == 'off') {
        err = 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder.';
      } else if (r['state'] != null || r['error'] != null) {
        err = r['error'] != null ? 'The backend says: ${r['error']}' : 'Cannot reach the backend right now.';
      }
    }
    if (!mounted) return;
    setState(() {
      _loading = false;
      _err = err;
    });
  }

  @override
  Widget build(BuildContext context) {
    final have = <String, Map<String, dynamic>>{};
    final missing = <String>[];
    for (final id in widget.ids) {
      final c = _cache[id];
      if (c != null) {
        have[id] = flM(c['data']);
      } else {
        missing.add(id);
      }
    }
    if (_loading && have.isEmpty) {
      return const Padding(padding: EdgeInsets.all(AppSpacing.xl), child: Center(child: CircularProgressIndicator()));
    }
    final saved = widget.ids.map((id) => _cache[id]?['saved_ts']).whereType<num>().toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const SizedBox(height: AppSpacing.s),
      if (_err.isNotEmpty) flNote(context, _err, bad: true),
      if (have.isEmpty && !_loading && _err.isEmpty)
        flNote(context, 'No saved summary yet (${widget.ids.join(', ')}). The study run makes it: open Overview and press "Run study now", or wait for the daily auto run.'),
      if (have.isNotEmpty) widget.builder(context, have, missing),
      const SizedBox(height: AppSpacing.m),
      Row(children: [
        Expanded(child: Text(saved.isEmpty ? '' : 'Summary saved ${flAgo(saved.reduce((a, b) => a < b ? a : b))}. Numbers are from saved trades, not live.', style: context.type.caption)),
        SizedBox(width: 120, child: OWLButton(text: 'Reload', isLoading: _loading, onPressed: _load, icon: Icons.refresh_rounded)),
      ]),
    ]);
  }
}

/// A closed-by-default group of rows (one bucket table). The title says what it is, the headline says how many buckets.
Widget flFold(BuildContext context, String title, String headline, List<Widget> rows) {
  return Padding(
    padding: const EdgeInsets.only(bottom: AppSpacing.s),
    child: OWLCard(child: OwlFold(title: title, headline: headline, bare: true, children: [OwlListCard(children: rows)])),
  );
}

/// Part 8B-2a: one colour per verdict word (Part 4 filters, Part 5A / 5B exit rules). Green = good in both halves, amber = good but costs something, red = failed, grey = unknown / too few.
Color flVerdictColor(BuildContext context, String v) {
  final p = context.palette;
  switch (v) {
    case 'PASS':
    case 'PASS_NO_MOVE_CHECK':
    case 'BETTER':
      return p.profit;
    case 'HELPS_BUT_LOSES_MOVES':
    case 'TRADEOFF':
      return p.warning;
    case 'FAILS_TEST':
    case 'UNSTABLE':
    case 'WORSE':
    case 'NO_HELP':
      return p.loss;
    default:
      return p.textMuted;
  }
}
