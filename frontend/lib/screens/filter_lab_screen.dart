import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_status_pill.dart';
import '../widgets/owl_text_tabs.dart';
import 'filter_decisions_tab.dart';
import 'filter_exits_tab.dart';
import 'filter_fakes_tab.dart';
import 'filter_filters_tab.dart';
import 'filter_moves_tab.dart';
import 'filter_overview_tab.dart';

/// Part 8A-2 (README_FILTER): the FILTER LAB shell, shown inside the Study Lab tab (second tab, next to the Results board).
/// The shell owns the data: it reads GET /api/v2/filter (gate, study run, saved Parts, gate log) and GET /api/v2/filter_rules every 10 s while it is open,
/// keeps the last good answer for the app session, and hands both to the tab that is showing. Pull down = reload now.
/// Tab 1 = Overview (filter_overview_tab.dart). Part 8B-1: Fakes (Part 2) and Moves (3A + 3B). Part 8B-2a: Filters (Part 4) and Exits (5A + 5B). Part 8B-2b: Decisions (Part 6 four words + Part 1B Sniper LEARN / b3 log).
/// The study is READ ONLY. The only thing here that can change trading is the gate mode switch (Overview), default OFF, and it asks before BLOCK.
/// Dart NOT compiled (the APK build is the proof).
class FilterLabScreen extends StatefulWidget {
  const FilterLabScreen({super.key});

  @override
  State<FilterLabScreen> createState() => _FilterLabScreenState();
}

class _FilterLabScreenState extends State<FilterLabScreen> {
  // Last good replies are kept for the app session, so re-opening the tab shows data at once.
  static Map<String, dynamic> _cacheMain = {};
  static Map<String, dynamic> _cacheRules = {};
  Map<String, dynamic> _main = Map<String, dynamic>.from(_cacheMain);
  Map<String, dynamic> _rules = Map<String, dynamic>.from(_cacheRules);
  String _err = '';
  bool _loaded = false;
  bool _polling = false;
  int _tab = 0;
  Timer? _timer;

  static const List<String> _tabNames = ['Overview', 'Fakes', 'Moves', 'Filters', 'Exits', 'Decisions'];

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 10), (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  bool _bad(Map<String, dynamic> r) => r['state'] != null || r['error'] != null;

  String _problem(Map<String, dynamic> r) {
    if (r['error'] != null) return 'The backend says: ${r['error']}';
    switch ('${r['state']}') {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down.';
      case 'old':
        return 'This backend does not have the Filter Lab routes yet. Install the newest zip and restart the backend.';
      default:
        return 'Cannot reach the backend right now. It will try again.';
    }
  }

  Future<void> _poll() async {
    if (!mounted || _polling) return;
    _polling = true;
    try {
      final pr = context.read<AppProvider>();
      final rs = await Future.wait([pr.fetchFilter(), pr.fetchFilterRules()]);
      if (!mounted) return;
      setState(() {
        _loaded = true;
        if (_bad(rs[0])) {
          _err = _problem(rs[0]);
        } else {
          _err = '';
          _main = rs[0];
          _cacheMain = rs[0];
        }
        // The rules file may not exist yet ({state: none}); that is a normal answer, not an error. Keep it as it is.
        if (rs[1]['state'] == 'none' || !_bad(rs[1])) {
          _rules = rs[1];
          _cacheRules = rs[1];
        }
      });
    } finally {
      _polling = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: _poll,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, AppSpacing.xl),
        children: [
          _header(context),
          if (_err.isNotEmpty) Padding(padding: const EdgeInsets.only(top: AppSpacing.s), child: _notice(context, _err, bad: true)),
          OwlTextTabs(names: _tabNames, index: _tab, fontSize: 13, onChanged: (i) => setState(() => _tab = i)),
          if (!_loaded && _main.isEmpty)
            const Padding(padding: EdgeInsets.all(AppSpacing.xl), child: Center(child: CircularProgressIndicator()))
          else if (_main.isEmpty)
            const SizedBox.shrink()
          else if (_tab == 0)
            FilterOverviewTab(data: _main, rules: _rules, onReload: _poll)
          else if (_tab == 1)
            const FilterFakesTab()
          else if (_tab == 2)
            const FilterMovesTab()
          else if (_tab == 3)
            const FilterFiltersTab()
          else if (_tab == 4)
            const FilterExitsTab()
          else
            const FilterDecisionsTab(),
        ],
      ),
    );
  }

  // ---------------------------------------------------------------- header
  Widget _header(BuildContext context) {
    final p = context.palette;
    final gate = _m(_main['gate']);
    final mode = '${gate['mode'] ?? 'off'}';
    final run = _m(_main['run']);
    final running = run['running'] == true;
    final color = mode == 'block' ? p.warning : (mode == 'log' ? p.accent : p.textMuted);
    return OWLCard(
      edge: mode == 'off' ? null : color,
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text('Filter Lab', style: context.type.section.copyWith(fontWeight: FontWeight.w800)),
              const SizedBox(width: AppSpacing.s),
              OWLStatusPill(text: 'GATE ${mode.toUpperCase()}', color: color),
              if (running) ...[
                const SizedBox(width: AppSpacing.xs),
                OWLStatusPill(text: 'STUDY RUNNING', color: p.accent, showDot: false),
              ],
            ]),
            const SizedBox(height: 4),
            Text('Why signals are fake, and which rules cut them without killing the long rallies. The study is read only.', style: context.type.metadata),
          ]),
        ),
      ]),
    );
  }

  Widget _notice(BuildContext context, String text, {bool bad = false}) {
    final p = context.palette;
    return OWLCard(edge: bad ? p.warning : null, padding: const EdgeInsets.all(AppSpacing.m), child: Text(text, style: context.type.secondary));
  }
}

Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
