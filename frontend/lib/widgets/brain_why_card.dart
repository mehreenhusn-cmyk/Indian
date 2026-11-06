import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'owl_card.dart';

/// E6: "Why is the Brain not trading today?" Read only: GET /api/v2/brain_why (today's Brain decisions grouped by decision and reason, exactly as the Brain stored them).
/// Every sentence comes from the backend (lines[]); this file lays them out. It never trades. Loads once, then every 2 minutes while on screen. Dart NOT compiled.
class BrainWhyCard extends StatefulWidget {
  final String source;
  const BrainWhyCard({super.key, this.source = 'PAPER'});

  @override
  State<BrainWhyCard> createState() => _BrainWhyCardState();
}

class _BrainWhyCardState extends State<BrainWhyCard> {
  Map<String, dynamic> _r = {};
  Timer? _timer;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(minutes: 2), (_) => _load());
  }

  @override
  void didUpdateWidget(covariant BrainWhyCard old) {
    super.didUpdateWidget(old);
    if (old.source != widget.source) _load();
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
      final r = await context.read<AppProvider>().fetchBrainWhy(widget.source);
      if (mounted && r.isNotEmpty) setState(() => _r = r);
    } catch (_) {
      // keep the last good answer
    } finally {
      _busy = false;
    }
  }

  String _word(String d) {
    switch (d) {
      case 'SKIP':
        return 'Skipped';
      case 'WAIT':
        return 'Waited';
      case 'NO_OPINION':
        return 'No opinion';
      default:
        return d;
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final lines = _r['lines'] is List ? List<String>.from((_r['lines'] as List).map((e) => '$e')) : <String>[];
    final reasons = _r['reasons'] is List ? (_r['reasons'] as List).whereType<Map>().toList() : <Map>[];
    final state = '${_r['state'] ?? ''}';
    final taken = _r['taken'] is num ? (_r['taken'] as num).toInt() : 0;
    final edge = state == 'OK' ? (taken > 0 ? p.profit : p.warning) : p.textMuted;
    return OWLCard(
      edge: edge,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Why is the Brain not trading?', style: context.type.primary.copyWith(fontWeight: FontWeight.w800)),
        const SizedBox(height: 4),
        if (_r.isEmpty)
          Text('Loading...', style: context.type.metadata)
        else if (state == 'error' && lines.isEmpty)
          Text('This is not available from the backend yet. Install the newest backend zip and restart it.', style: context.type.metadata)
        else ...[
          for (final l in lines) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text(l, style: context.type.secondary)),
          if (reasons.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text('Reasons today (as the Brain wrote them)', style: context.type.label.copyWith(fontWeight: FontWeight.w800)),
            for (final x in reasons)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('${_word('${x['decision']}')} x${x['n']}: ${x['reason']}', style: context.type.metadata),
              ),
          ],
        ],
      ]),
    );
  }
}
