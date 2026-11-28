import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'owl_card.dart';

/// R24b: SNIPER GRADUATION CHECKLIST (Study Lab). Shows what GET /api/v2/sniper_grad sends (backend owl_sniper_grad.py).
/// 7 checks, each PASS / FAIL / WAIT (WAIT = not enough data yet, never counted as pass). The headline word comes ONLY from the backend:
/// READY TO DISCUSS (all 7 pass) / NOT YET (any FAIL) / COLLECTING. The app never swaps the bots by itself: the owner decides.
/// Folded by default (one line); asks once, then every 5 minutes while on screen. Read only, nothing trades. Dart NOT compiled (the APK build is the proof).
class SniperGraduationCard extends StatefulWidget {
  const SniperGraduationCard({super.key});

  @override
  State<SniperGraduationCard> createState() => _SniperGraduationCardState();
}

class _SniperGraduationCardState extends State<SniperGraduationCard> {
  Map<String, dynamic> _d = {};
  Timer? _timer;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(minutes: 5), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_busy) return;
    _busy = true;
    try {
      final d = await context.read<AppProvider>().fetchSniperGrad();
      if (mounted && d.isNotEmpty && d['overall'] != null) setState(() => _d = d);
    } catch (_) {
      // keep the last good answer
    } finally {
      _busy = false;
    }
  }

  static String _word(String v) {
    switch (v) {
      case 'READY_TO_DISCUSS':
        return 'READY TO DISCUSS';
      case 'NOT_YET':
        return 'NOT YET';
      case 'COLLECTING':
        return 'COLLECTING DATA';
      default:
        return v.toUpperCase();
    }
  }

  Widget _row(AppPalette p, Map<String, dynamic> c) {
    final s = '${c['status']}';
    final col = s == 'PASS' ? p.profit : s == 'FAIL' ? p.loss : p.textSecondary;
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 44, child: Text(s, style: context.type.metadata.copyWith(color: col, fontWeight: FontWeight.w800))),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${c['name']}', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
            Text('${c['text'] ?? ''}', style: context.type.metadata),
          ]),
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final overall = '${_d['overall'] ?? ''}';
    final checks = _d['checks'] is List ? (_d['checks'] as List).whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
    final passed = _d['passed'] is num ? (_d['passed'] as num).toInt() : 0;
    final total = _d['total'] is num ? (_d['total'] as num).toInt() : checks.length;
    final reasons = _d['reasons'] is List ? List<String>.from((_d['reasons'] as List).map((e) => '$e')) : <String>[];
    final head = _d.isEmpty ? 'Loading' : '${_word(overall)}  ·  $passed of $total passed';
    final tone = overall == 'READY_TO_DISCUSS' ? p.profit : overall == 'NOT_YET' ? p.warning : null;
    return OwlFold(
      title: 'SNIPER GRADUATION CHECKLIST',
      headline: head,
      headlineColor: tone,
      children: [
        Text('Rules for the Sniper to replace the Current Bot. WAIT = not enough data yet (not a pass). The app never swaps the bots: you decide. Paper trades, a hint, not a profit promise.', style: context.type.metadata),
        for (final c in checks) _row(p, c),
        for (final r in reasons) Padding(padding: const EdgeInsets.only(top: 6), child: Text(r, style: context.type.metadata)),
      ],
    );
  }
}
