import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Top of the crypto Strategy Doctor: (1) the 3 things to know, (2) timeframe / coin filter chips,
/// (3) a small OK / SLOW health line. Reads /api/doctor_summary and /api/health_meter only. Nothing here changes the bot.
class DoctorTopCard extends StatefulWidget {
  final String tf;
  final String coin;
  final void Function(String tf, String coin) onFilter;
  const DoctorTopCard({super.key, required this.tf, required this.coin, required this.onFilter});

  @override
  State<DoctorTopCard> createState() => _DoctorTopCardState();
}

class _DoctorTopCardState extends State<DoctorTopCard> {
  Map<String, dynamic> _sum = {};
  Map<String, dynamic> _health = {};
  bool _loading = true;
  bool _showHealth = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 30), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<Map<String, dynamic>> _get(String base, String path, int secs) async {
    final res = await http.get(Uri.parse('$base$path')).timeout(Duration(seconds: secs));
    if (res.statusCode != 200) throw 'HTTP ${res.statusCode}';
    final m = jsonDecode(utf8.decode(res.bodyBytes));
    return m is Map ? Map<String, dynamic>.from(m) : <String, dynamic>{};
  }

  Future<void> _load() async {
    if (!mounted) return;
    final base = context.read<AppProvider>().baseUrl;
    Map<String, dynamic>? s, h;
    try {
      s = await _get(base, '/api/doctor_summary', 25);
    } catch (_) {}
    try {
      h = await _get(base, '/api/health_meter', 8);
    } catch (_) {}
    if (!mounted) return;
    setState(() {
      if (s != null) _sum = s;
      if (h != null) _health = h;
      _loading = false;
    });
  }

  Color _kindColor(BuildContext c, String k) {
    final p = c.palette;
    switch (k) {
      case 'AVOID':
        return p.loss;
      case 'DO':
        return p.profit;
      case 'WAIT':
        return p.warning;
      default:
        return p.textMuted;
    }
  }

  Widget _chip(String label, bool on, VoidCallback tap) => Padding(
        padding: const EdgeInsets.only(right: 6),
        child: ChoiceChip(label: Text(label, style: const TextStyle(fontSize: 12)), selected: on, onSelected: (_) => tap(), visualDensity: VisualDensity.compact),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final acts = (_sum['actions'] is List) ? (_sum['actions'] as List).whereType<Map>().toList() : <Map>[];
    final opts = (_sum['options'] is Map) ? Map<String, dynamic>.from(_sum['options'] as Map) : <String, dynamic>{};
    final tfs = (opts['tfs'] is List) ? (opts['tfs'] as List).map((e) => '$e').toList() : <String>[];
    final coins = (opts['coins'] is List) ? (opts['coins'] as List).map((e) => '$e').toList() : <String>[];
    final slow = '${_health['state']}' == 'SLOW';
    final hLines = (_health['lines'] is List) ? (_health['lines'] as List).map((e) => '$e').toList() : <String>[];
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: p.accent.withOpacity(0.35))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('3 things to know', style: context.type.primary.copyWith(fontWeight: FontWeight.w800))),
          if (_health.isNotEmpty)
            InkWell(
              onTap: () => setState(() => _showHealth = !_showHealth),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                    color: (slow ? p.warning : p.profit).withOpacity(0.15), borderRadius: BorderRadius.circular(8)),
                child: Text(slow ? 'Backend SLOW' : 'Backend OK',
                    style: TextStyle(color: slow ? p.warning : p.profit, fontSize: 10.5, fontWeight: FontWeight.w800)),
              ),
            ),
        ]),
        if (_showHealth)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(hLines.join('\n'), style: context.type.metadata),
          ),
        const SizedBox(height: 8),
        if (_loading)
          const LinearProgressIndicator()
        else if (acts.isEmpty)
          Text('Could not build the summary yet. Pull down to retry.', style: context.type.secondary)
        else
          for (final a in acts)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Container(
                  width: 52,
                  margin: const EdgeInsets.only(right: 8, top: 1),
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  decoration: BoxDecoration(color: _kindColor(context, '${a['kind']}').withOpacity(0.15), borderRadius: BorderRadius.circular(6)),
                  child: Text('${a['kind']}',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: _kindColor(context, '${a['kind']}'), fontSize: 10, fontWeight: FontWeight.w800)),
                ),
                Expanded(child: Text('${a['text']}', style: context.type.secondary)),
              ]),
            ),
        if (tfs.isNotEmpty || coins.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text('Show Doctor for', style: context.type.metadata),
          const SizedBox(height: 4),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(children: [
              _chip('All', widget.tf.isEmpty && widget.coin.isEmpty, () => widget.onFilter('', '')),
              for (final t in tfs) _chip(t, widget.tf == t, () => widget.onFilter(widget.tf == t ? '' : t, widget.coin)),
              for (final c in coins) _chip(c.replaceAll('USDT', ''), widget.coin == c, () => widget.onFilter(widget.tf, widget.coin == c ? '' : c)),
            ]),
          ),
          if (widget.tf.isNotEmpty || widget.coin.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                  'Showing only ${[if (widget.tf.isNotEmpty) widget.tf, if (widget.coin.isNotEmpty) widget.coin].join(' + ')}. The 3 lines above use all trades.',
                  style: context.type.metadata),
            ),
        ],
      ]),
    );
  }
}
