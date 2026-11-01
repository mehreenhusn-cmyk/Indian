import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import 'sniper_panels.dart';

/// Part S6 (OwlSniper), part 2 of 2: read-only, on the Part S5 route /api/v2/sniper (the panels are in sniper_panels.dart, part 1 of 2).
/// The page asks the backend again every 30 seconds while it is open (a cheap read of two small files); the backend starts its own refresh by itself, so nothing has to be run by hand.
/// OwlSniper only WATCHES: nothing here sends an order, saves anything or switches anything. Dart NOT compiled (the APK build is the proof).
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
        return 'This backend does not have the OwlSniper route yet. Install the newest zip, say "mount ok" so the route is added to the backend, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
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
        SniperBanner(r: r!),
        SniperCards(r: r, showAll: _all, onToggle: () => setState(() => _all = !_all)),
        SniperEquity(r: r),
        SniperFloor(r: r),
        SniperReport(r: r),
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
