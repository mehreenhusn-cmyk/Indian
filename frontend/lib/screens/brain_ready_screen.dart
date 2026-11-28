import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part N2 (Brain Ready?): read-only, on the Part N2 route /api/v2/brain_ready.
/// ONE word (NOT RUNNING / NOT YET / CHECKS PASS) + one sentence, what the Brain does by itself (find chances, paper trades, manage the trade), five small numbers and 8 plain checks with a tick or a cross.
/// Live is always locked: even CHECKS PASS only means "ask the owner". Nothing here trades, saves or switches anything. Dart NOT compiled (the APK build is the proof).
class BrainReadyScreen extends StatefulWidget {
  const BrainReadyScreen({super.key});

  @override
  State<BrainReadyScreen> createState() => _BrainReadyScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
double _d(Object? v) => v is num ? v.toDouble() : 0.0;
String _sg(Object? v) => '${_d(v) >= 0 ? '+' : ''}${_d(v).toStringAsFixed(2)}';

class _BrainReadyScreenState extends State<BrainReadyScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchBrainReady('PAPER');
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  bool _bad(Map<String, dynamic>? r) => r == null || r['state'] != null || r['error'] != null || r['ready'] != true;

  String _problem(Map<String, dynamic>? r) {
    if (r != null && r['ready'] == false && r['note'] != null) return '${r['note']}';
    if (r != null && r['error'] != null) return '${r['error']}';
    switch (r?['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the Brain Ready route yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  Color _wordColor(AppPalette p, String w) => w == 'CHECKS PASS' ? p.profit : w == 'NOT RUNNING' ? p.loss : p.warning;

  Widget _verdict(AppPalette p, Map<String, dynamic> r) {
    final v = _m(r['verdict']);
    final w = '${v['word']}';
    final c = _wordColor(p, w);
    return OWLCard(
      edge: c,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Is the Brain ready?', style: TextStyle(fontSize: 13, color: p.textSecondary)),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
          decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
          child: Text(w, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: c)),
        ),
        const SizedBox(height: 8),
        Text('${v['text'] ?? ''}', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
        const SizedBox(height: 6),
        Text('${r['passed']} of ${r['total']} checks pass  |  LIVE: locked', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
      ]),
    );
  }

  Widget _line(AppPalette p, String label, bool on) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Icon(on ? Icons.check_circle : Icons.cancel, size: 18, color: on ? p.profit : p.loss),
          const SizedBox(width: 8),
          Expanded(child: Text(label, style: TextStyle(fontSize: 13, color: p.textPrimary))),
          Text(on ? 'ON' : 'OFF', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: on ? p.profit : p.loss)),
        ]),
      );

  Widget _stat(AppPalette p, String big, String label, [Color? c]) => Expanded(
        child: Column(children: [
          Text(big, style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: c ?? p.textPrimary)),
          const SizedBox(height: 2),
          Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
        ]),
      );

  Widget _doing(AppPalette p, Map<String, dynamic> r) {
    final b = _m(r['brain']);
    final auto = b['auto'] == true;
    final net = _d(b['net_usdt']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('What the Brain does by itself', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 6),
        _line(p, 'Looks for chances every 5 minutes', auto),
        _line(p, 'Opens paper trades (pretend money)', auto),
        _line(p, 'Manages the trade: hold, protect, close', auto && b['manager'] == true),
        const SizedBox(height: 10),
        Row(children: [
          _stat(p, '${b['open'] ?? 0}', 'open now'),
          _stat(p, '${b['trades'] ?? 0}', 'closed trades'),
          _stat(p, '${b['wins'] ?? 0} / ${b['losses'] ?? 0}', 'wins / losses'),
          _stat(p, _sg(net), 'net USDT', net >= 0 ? p.profit : p.loss),
          _stat(p, '${b['days'] ?? 0}', 'days'),
        ]),
      ]),
    );
  }

  Widget _checks(AppPalette p, Map<String, dynamic> r) {
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Checks', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 6),
        for (final c in _l(r['checks']))
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(c['ok'] == true ? Icons.check_circle : Icons.radio_button_unchecked, size: 18, color: c['ok'] == true ? p.profit : p.warning),
              const SizedBox(width: 8),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${c['label']}', style: TextStyle(fontSize: 13, color: p.textPrimary)),
                  Text('${c['note']}', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
                ]),
              ),
            ]),
          ),
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
      kids = [OWLCard(edge: p.warning, child: Text(_problem(r), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else {
      kids = [_verdict(p, r!), _doing(p, r), _checks(p, r), Text('${r['note'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textMuted))];
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
