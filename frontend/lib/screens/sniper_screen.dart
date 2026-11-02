import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import '../widgets/signal_card.dart';
import 'sniper_compare.dart';
import 'sniper_panels.dart';
import 'sniper_pillars.dart';

/// OwlSniper tab. Part S6 made it; Round 27 rebuilt it on the 3 pillars (Round 25) and the Sniper vs Main Bot panel. Read-only, on GET /api/v2/sniper.
/// Order: headline -> Pillar B Volatility Guard -> order cards -> Pillar C Terminal Insight -> Sniper vs Main Bot -> Pillar A Capital Shield -> TEST-day equity -> 85% floor -> insight report -> auto-trade strip.
/// The page asks the backend again every 30 seconds while it is open (a cheap read of small files); the backend starts its own refresh by itself, so nothing has to be run by hand.
/// OwlSniper only WATCHES: nothing here sends an order, saves anything or switches anything (the auto-trade strip only SHOWS the executor state; arming is a Termux command, never a button).
/// Dart NOT compiled (the APK build is the proof).
class SniperScreen extends StatefulWidget {
  const SniperScreen({super.key});

  @override
  State<SniperScreen> createState() => _SniperScreenState();
}

class _SniperScreenState extends State<SniperScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;
  bool _all = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 30), (_) => _load(silent: true));
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    if (!silent) setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchSniper();
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  bool _bad(Map<String, dynamic>? r) => r == null || r['state'] != null || r['error'] != null;

  String _problem(Map<String, dynamic>? r) {
    if (r != null && r['error'] != null) return '${r['error']}';
    switch (r?['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the OwlSniper route yet. Install the newest backend zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  String _ago(Object? s) {
    if (s is! num) return 'not yet';
    final n = s.toInt();
    if (n < 90) return '${n}s ago';
    if (n < 5400) return '${(n / 60).round()} min ago';
    return '${(n / 3600).toStringAsFixed(1)} h ago';
  }

  Widget _head(AppPalette p, Map<String, dynamic> r) {
    final stale = r['stale_coins'] is num ? (r['stale_coins'] as num).toInt() : 0;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('${r['headline'] ?? ''}', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: p.textPrimary)),
      const SizedBox(height: 4),
      Text('OwlSniper (watch only)  |  checked ${_ago(r['updated_ago_sec'])}  |  learned ${_ago(r['model_ago_sec'])}${r['refreshing'] == true ? '  |  working in the background...' : ''}${stale > 0 ? '  |  $stale coins have old candles' : ''}',
          style: TextStyle(fontSize: 11, color: p.textMuted)),
    ]);
  }

  /// Shows what the executor is doing. No button: arming is a two-step Termux command on purpose.
  Widget _auto(AppPalette p, Map<String, dynamic> r) {
    final ex = r['executor'] is Map ? Map<String, dynamic>.from(r['executor'] as Map) : <String, dynamic>{};
    final kill = ex['kill'] is Map && (ex['kill'] as Map)['on'] == true;
    final armed = ex['armed'] == true;
    final String text;
    final Color c;
    if (ex.isEmpty || ex['state'] != null || ex['ok'] == false) {
      text = 'Auto-trade: not available in this backend. OwlSniper is watch only.';
      c = p.textMuted;
    } else if (kill) {
      text = 'Auto-trade: STOPPED by the kill switch (${(ex['kill'] as Map)['reason'] ?? ''}).';
      c = p.loss;
    } else if (armed) {
      text = 'Auto-trade: ARMED in paper mode only. It opens a paper trade only when every check passes (85% or more, proven on the TEST days).';
      c = p.warning;
    } else {
      text = 'Auto-trade: OFF. It stays off until you arm it in two steps from Termux. Paper mode only, live orders do not exist.';
      c = p.textSecondary;
    }
    return OWLCard(edge: armed || kill ? c : null, child: Text(text, style: TextStyle(fontSize: 12, color: c)));
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    } else if (_bad(r)) {
      kids = [OWLCard(edge: p.warning, child: Text(_problem(r), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else {
      kids = [
        _head(p, r!),
        SniperVolatilityGuard(r: r),
        SniperSignalList(r: r, showAll: _all, onToggle: () => setState(() => _all = !_all)),
        SniperInsightConsole(r: r),
        SniperComparePanel(r: r),
        SniperCapitalShield(r: r),
        SniperEquity(r: r),
        SniperFloor(r: r),
        SniperReport(r: r),
        _auto(p, r),
        Text('${r['note'] ?? 'WATCH ONLY: this page never sends an order.'}', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ];
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.l),
        children: [for (final k in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: k)],
      ),
    );
  }
}
