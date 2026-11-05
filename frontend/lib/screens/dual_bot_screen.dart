import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import '../utils/format.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/dual_summary_strip.dart';
import '../widgets/dual_trade_card.dart';
import '../widgets/dual_trade_chart.dart';
import '../widgets/opportunities_tab.dart';
import '../widgets/owl_text_tabs.dart';
import '../widgets/performance_tab.dart';
import '../widgets/simple_tab.dart';
import '../widgets/report_download_card.dart';
import '../widgets/smart_brain_view.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_route.dart';
import 'tag_lab_screen.dart';

part 'dual_now_part.dart';
part 'dual_learned_part.dart';
part 'dual_perf_part.dart';

// R19: shared helpers are top-level so the 'part' files (extensions) can call them.
Map<String, dynamic> _map(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _maps(dynamic v) =>
    v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
String _usdt(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)} USDT';

/// Dual Bot screen (paper only). A separate bot that reads BOTH indicators (main EMA50 chart + the Z pane with the
/// Z-EMA cloud and black candle), learns by itself when to trade and how to exit, and shows what it earned.
/// No AI key is needed, so a key limit can never stop it. It never touches the live bot.
/// Everything comes from GET /api/dual_lab (backend dual_lab.py). The screen only polls while it is open.
class DualBotScreen extends StatefulWidget {
  const DualBotScreen({super.key});

  @override
  State<DualBotScreen> createState() => _DualBotScreenState();
}

class _DualBotScreenState extends State<DualBotScreen> {
  // Last good reply is kept for the whole app session, so re-opening the tab shows data at once (no "Connecting...").
  static Map<String, dynamic> _cache = {};
  Map<String, dynamic> _st = Map<String, dynamic>.from(_cache);
  String _err = '';
  bool _busy = false;
  Timer? _retry;
  int _seg = 0; // R19: 0 = Simple, 1 = Now (+ Opportunities fold), 2 = Performance (+ Learned and Brain folds)
  Map<String, dynamic> _brain = {}; // last full Smart Brain reply (watch list, own trades, performance) for the Opportunities and Performance tabs
  Map<String, dynamic> _brainIds = {}; // Smart Brain opinion per trade (coin|timeframe|time), for the small badge on the open cards
  Map<String, dynamic> _desk = {}; // /api/dual_desk: today / last-7-days numbers for the strip on the Simple tab (Z2b)
  Map<String, dynamic> _arch = {}; // /api/archive: DATA SAFE chip (Z2c)
  String _brainTrust = ''; // Smart Brain trust verdict (earned / not_yet / learning) for the status bar
  int _filter = 0; // Now tab filter: 0 = All, 1 = Good only, 2 = Long, 3 = Short
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 8), (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _retry?.cancel();
    super.dispose();
  }

  Future<void> _poll({String action = ''}) async {
    if (!mounted) return;
    try {
      final base = context.read<AppProvider>().baseUrl;
      final q = action.isEmpty ? '' : '?action=$action';
      final res = await http.get(Uri.parse('$base/api/dual_lab$q')).timeout(const Duration(seconds: 20));
      if (res.statusCode != 200) throw 'HTTP ${res.statusCode}';
      final m = jsonDecode(utf8.decode(res.bodyBytes));
      if (m is! Map) throw 'unexpected reply';
      if (mounted) {
        setState(() {
          _st = Map<String, dynamic>.from(m);
          _cache = _st;
          _err = '${_st['error'] ?? ''}';
        });
      }
    } catch (e) {
      if (mounted) setState(() => _err = '$e');
    }
    // Nothing to show yet (backend just started): ask again in 3 s instead of waiting for the 8 s timer.
    if (mounted && _st.isEmpty) {
      _retry?.cancel();
      _retry = Timer(const Duration(seconds: 3), () => _poll());
    }
    await _pollBrain();
    await _pollDesk();
  }

  /// Small desk numbers from the archive. A failure is silent: the strip just keeps its last answer.
  Future<void> _pollDesk() async {
    if (!mounted) return;
    try {
      final base = context.read<AppProvider>().baseUrl;
      final res = await http.get(Uri.parse('$base/api/dual_desk')).timeout(const Duration(seconds: 10));
      final m = res.statusCode == 200 ? jsonDecode(utf8.decode(res.bodyBytes)) : null;
      if (m is Map && mounted) setState(() => _desk = Map<String, dynamic>.from(m));
    } catch (_) {}
    try {
      final base = context.read<AppProvider>().baseUrl;
      final res = await http.get(Uri.parse('$base/api/archive')).timeout(const Duration(seconds: 10));
      final m = res.statusCode == 200 ? jsonDecode(utf8.decode(res.bodyBytes)) : null;
      if (m is Map && mounted) setState(() => _arch = Map<String, dynamic>.from(m));
    } catch (_) {}
  }

  /// Only the small per-trade opinion map. A failure here is silent: the cards just show no badge.
  Future<void> _pollBrain() async {
    if (!mounted) return;
    try {
      final base = context.read<AppProvider>().baseUrl;
      final res = await http.get(Uri.parse('$base/api/smart_brain')).timeout(const Duration(seconds: 15));
      if (res.statusCode != 200) return;
      final m = jsonDecode(utf8.decode(res.bodyBytes));
      if (m is Map && m['by_key'] is Map && mounted) {
        setState(() {
          _brain = Map<String, dynamic>.from(m);
          _brainIds = Map<String, dynamic>.from(m['by_key'] as Map);
          _brainTrust = m['trust'] is Map ? '${(m['trust'] as Map)['verdict'] ?? ''}' : '';
        });
      }
    } catch (_) {}
  }

  void _setFilter(int i) => setState(() => _filter = i);

  Future<void> _toggle(bool on) async {
    setState(() => _busy = true);
    await _poll(action: on ? 'start' : 'stop');
    if (mounted) setState(() => _busy = false);
  }


  /// Margin of ONE trade: BTC has its own (the backend sends it per trade), the rest use the common margin.
  double _mg(Map t) => t['margin'] is num ? (t['margin'] as num).toDouble() : _n(_st['margin']);

  /// UI2b: with [headline] the card is a fold (one line with the key number when closed, details on tap).
  Widget _card(AppPalette p, {required String title, required List<Widget> children, Color? edge, String? headline, Color? headlineColor}) =>
      headline == null
          ? OwlSectionCard(title: title, edge: edge, children: children)
          : OwlFold(title: title, headline: headline, headlineColor: headlineColor, edge: edge, children: children);


  Widget _kv(String k, String v, {Color? color}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(children: [
        Expanded(child: Text(k, style: context.type.secondary)),
        Text(v, style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: color)),
      ]),
    );
  }

  Widget _segRow(AppPalette p) {
    // R25b: plain text tabs (same look as Positions): selected = bold + underline, the others grey. No box, no icon.
    const hints = [
      'Is the bot OK, the open trades, best and worst trades.',
      'Open trades now, today, BTC, what the Brain watches, start / stop.',
      'Results, past trades, what the bot learned, the Smart Brain, reports.',
    ];
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        OwlTextTabs(names: const ['Simple', 'Now', 'Performance'], index: _seg.clamp(0, 2), onChanged: (i) => setState(() => _seg = i)),
        const SizedBox(height: 6),
        Text(hints[_seg.clamp(0, 2)], style: context.type.metadata.copyWith(color: p.textMuted)),
      ]),
    );
  }

  /// R19: a closed fold (header card + cards inside) for everything that is not the one-glance part of a tab.
  Widget _group(String title, String headline, List<Widget> kids) => OwlFold(title: title, headline: headline, bare: true, children: kids);

  /// Body of the selected Dual Bot tab (moved out of build() so E2 can fade between tabs).
  List<Widget> _segBody(AppPalette p) {
    final recent = _maps(_st['recent']);
    final nOpen = recent.where((t) => '${t['status']}' == 'open').length;
    final today = _map(_map(_st['summary'])['today']);
    if (_st.isEmpty && _err.isNotEmpty) return [_failCard(p)]; // Plan D: failure = "--" + Retry, not zeros
    if (_seg == 0) {
      return [
        SimpleTab(
          today: _map(_map(_st['summary'])['today']),
          recent: recent,
          brainIds: _brainIds,
          sideways: _map(_brain['sideways']),
          bySrc: _map(_map(_st['summary'])['by_src']),
          desk: _desk,
          archive: _arch,
          marginOf: _mg,
          onOpen: (t) => showDualTradeChart(context, row: t, margin: _mg(t), lev: _n(_st['lev'])),
        ),
      ];
    }
    if (_seg == 1) {
      return [
        _stripCard(p),
        _openCard(p),
        _group('TODAY', today.isEmpty ? '--' : 'Closed ${_usdt(_n(today['realized']))}, open ${_usdt(_n(today['open_pnl']))}', [_todayCard(p), _btcDualCard(p)]),
        _group('OPPORTUNITIES', 'What the Brain is watching and its own pretend trades', [OpportunitiesTab(brain: _brain)]),
        _group('BOT CONTROL', '${_st['state_text'] ?? 'Connecting...'}', [_statusCard(p)]),
      ];
    }
    return [
      PerformanceTab(brain: _brain),
      _resultCard(p),
      _situationsCard(p),
      _recentCard(p),
      _group('WHAT IT LEARNED', 'Daily review, setups, retest check, scenarios, lessons, model', [
        _reviewCard(p),
        _setupCard(p),
        _retestCard(p),
        _scenCard(p),
        _lessonsCard(p),
        _modelCard(p),
      ]),
      _group('SMART BRAIN', 'Scores, probability, trust meter. Analysis only, no real trades.', const [SmartBrainView()]),
      _group('HOW TO READ', 'Short guide to the numbers', [_howToReadCard(p)]),
      OutlinedButton.icon(
        onPressed: _openReport,
        icon: const Icon(Icons.description_outlined, size: 18),
        label: const Text('Download Dual Bot report'),
      ),
      const SizedBox(height: 8),
      OutlinedButton.icon(
        onPressed: () => Navigator.of(context).push(OwlRoute(builder: (_) => const TagLabScreen())),
        icon: const Icon(Icons.hub_outlined, size: 18),
        label: const Text('Open Tag Lab (full test on old candles)'),
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(
        backgroundColor: p.bg,
        elevation: 0,
        centerTitle: false,
        title: Text('Dual Bot', style: context.type.section.copyWith(fontWeight: FontWeight.w800)),
      ),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _poll,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(12, 6, 12, 12),
            children: [
              _segRow(p),
              OwlDensity(
                compact: true,
                child: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 220),
                  switchInCurve: Curves.easeOut,
                  transitionBuilder: (child, anim) => FadeTransition(opacity: anim, child: child),
                  layoutBuilder: (cur, prev) => Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [if (cur != null) cur],
                  ),
                  child: Column(
                    key: ValueKey<int>(_seg),
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: _segBody(p),
                  ),
                ),
              ),
              const SizedBox(height: 8),
            ],
          ),
        ),
      ),
    );
  }
}
