import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../theme/app_spacing.dart';
import '../utils/format.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_refresh.dart';

/// Pump / Dump memory + Playbook for Vision AI.
/// Shows measured past pumps/dumps, outcomes (reverse / continue / sideways),
/// and a short playbook the AI uses. All numbers come from /api/vision/pumpdump.

Map<String, dynamic> _m(dynamic x) =>
    x is Map ? Map<String, dynamic>.from(x) : <String, dynamic>{};
List _l(dynamic x) => x is List ? x : const [];
double? _d(dynamic x) {
  if (x is num) return x.toDouble();
  if (x is String) return double.tryParse(x);
  return null;
}

String _hm(dynamic t) {
  final v = _d(t);
  if (v == null || v <= 0) return '';
  final dt = DateTime.fromMillisecondsSinceEpoch(
      (v > 1e12 ? v : v * 1000).round());
  final h = dt.hour.toString().padLeft(2, '0');
  final m = dt.minute.toString().padLeft(2, '0');
  return '$h:$m';
}

class VisionPumpdumpView extends StatefulWidget {
  const VisionPumpdumpView({super.key});

  @override
  State<VisionPumpdumpView> createState() => _VisionPumpdumpViewState();
}

class _VisionPumpdumpViewState extends State<VisionPumpdumpView> {
  bool _loading = false;
  String? _err;
  Map<String, dynamic> _data = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _err = null;
    });
    try {
      final p = context.read<AppProvider>();
      final d = await p.fetchVisionPumpdump();
      if (!mounted) return;
      setState(() {
        if (d == null) {
          _err = 'Could not load Pump/Dump memory. Update + restart the backend, then pull to refresh.';
        } else {
          _data = _m(d);
        }
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _err = e.toString();
        _loading = false;
      });
    }
  }

  Future<void> _seed(String symbol) async {
    setState(() => _loading = true);
    try {
      final p = context.read<AppProvider>();
      await p.seedVisionPumpdump(symbol);
      await _load();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _err = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (_loading && _data.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_err != null && _data.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.l),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_err!, style: TextStyle(color: p.loss)),
              const SizedBox(height: 12),
              OWLPressable(onTap: _load, child: Text('Retry', style: TextStyle(color: p.accent))),
            ],
          ),
        ),
      );
    }
    final playbook = _l(_data['playbook']).map((e) => e.toString()).toList();
    final plain = _l(_data['plain']).map((e) => e.toString()).toList();
    final events = _l(_data['events']).map(_m).toList();
    final stats = _m(_data['stats']);
    final total = _data['total'] ?? events.length;
    final by = _m(stats['by_kind']);
    final empty = events.isEmpty;

    return OWLRefresh(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
        children: [
          _header(p, total),
          const SizedBox(height: 12),
          if (plain.isNotEmpty) ...[
            _plainCard(p, plain),
            const SizedBox(height: 12),
          ],
          if (empty) ...[
            _emptySeedCard(p),
            const SizedBox(height: 12),
          ] else ...[
            _playbookCard(p, playbook),
            const SizedBox(height: 12),
            _statsRow(p, by),
            const SizedBox(height: 12),
            _seedRow(p),
            const SizedBox(height: 16),
            Text('Recent events', style: TextStyle(color: p.textSecondary, fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            ...events.take(30).map((e) => _eventCard(p, e)),
          ],
        ],
      ),
    );
  }


  Widget _plainCard(AppPalette p, List<String> lines) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: p.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('In plain words', style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          for (final line in lines)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(line, style: TextStyle(color: p.textSecondary, height: 1.35, fontSize: 13)),
            ),
        ],
      ),
    );
  }

  Widget _emptySeedCard(AppPalette p) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: p.accent.withOpacity(0.5)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('No pump/dump events yet', style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w700, fontSize: 15)),
          const SizedBox(height: 6),
          Text(
            'Seed from ~15 days of 15m candles to learn what usually happens after a pump or dump. Or wait for live 15m signals.',
            style: TextStyle(color: p.textMuted, height: 1.35, fontSize: 13),
          ),
          const SizedBox(height: 14),
          Text('Seed now', style: TextStyle(color: p.accent, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'].map((s) {
              return OWLPressable(
                onTap: _loading ? null : () => _seed(s),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: p.accent.withOpacity(0.18),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: p.accent.withOpacity(0.5)),
                  ),
                  child: Text(s, style: TextStyle(color: p.accent, fontWeight: FontWeight.w700, fontSize: 13)),
                ),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }

  Widget _header(AppPalette p, dynamic total) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: p.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Pump / Dump memory', style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w700, fontSize: 16)),
          const SizedBox(height: 6),
          Text(
            'Measured from 15m candles (TSI, Z, Z-SMA, SD zone, volume). '
            'After each pump or dump we record what happened next: reverse, continue or sideways. '
            'Vision AI sees this as a short prompt block — it does not change the bot.',
            style: TextStyle(color: p.textSecondary, fontSize: 13, height: 1.35),
          ),
          const SizedBox(height: 8),
          Text('Stored events: $total', style: TextStyle(color: p.accent, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }

  Widget _playbookCard(AppPalette p, List<String> lines) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: p.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Playbook', style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          if (lines.isEmpty)
            Text('Not enough events yet for a playbook.', style: TextStyle(color: p.textMuted))
          else
            ...lines.map((line) => Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('• ', style: TextStyle(color: p.accent)),
                      Expanded(child: Text(line, style: TextStyle(color: p.textSecondary, height: 1.3))),
                    ],
                  ),
                )),
        ],
      ),
    );
  }

  Widget _statsRow(AppPalette p, Map<String, dynamic> by) {
    Widget cell(String title, Map<String, dynamic> d) {
      final n = d['n'] ?? 0;
      return Expanded(
        child: Container(
          margin: const EdgeInsets.symmetric(horizontal: 4),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: p.surfaceElevated,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: p.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w600)),
              const SizedBox(height: 4),
              Text('n=$n', style: TextStyle(color: p.textMuted, fontSize: 12)),
              const SizedBox(height: 6),
              Text('rev ${d['reverse'] ?? 0}', style: TextStyle(color: p.warning, fontSize: 12)),
              Text('cont ${d['continue'] ?? 0}', style: TextStyle(color: p.profit, fontSize: 12)),
              Text('side ${d['sideways'] ?? 0}', style: TextStyle(color: p.textSecondary, fontSize: 12)),
            ],
          ),
        ),
      );
    }
    return Row(
      children: [
        cell('Pumps', _m(by['pump'])),
        cell('Dumps', _m(by['dump'])),
      ],
    );
  }

  Widget _seedRow(AppPalette p) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: p.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Seed from history', style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          Text(
            'Download ~15 days of 15m candles and learn pumps/dumps immediately (no need to wait for live trades).',
            style: TextStyle(color: p.textMuted, fontSize: 12),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT'].map((s) {
              return OWLPressable(
                onTap: _loading ? null : () => _seed(s),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: p.accent.withOpacity(0.12),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: p.accent.withOpacity(0.4)),
                  ),
                  child: Text(s, style: TextStyle(color: p.accent, fontWeight: FontWeight.w600, fontSize: 12)),
                ),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }

  Widget _eventCard(AppPalette p, Map<String, dynamic> e) {
    final kind = (e['kind'] ?? '').toString();
    final outcome = (e['outcome'] ?? '').toString();
    final before = _m(e['before']);
    final isPump = kind == 'pump';
    final color = isPump ? p.profit : p.loss;
    Color outColor;
    switch (outcome) {
      case 'reverse':
        outColor = p.warning;
        break;
      case 'continue':
        outColor = p.profit;
        break;
      default:
        outColor = p.textSecondary;
    }
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: p.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: color.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(kind.toUpperCase(), style: TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 11)),
              ),
              const SizedBox(width: 8),
              Text(e['symbol']?.toString() ?? '', style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w600)),
              const Spacer(),
              Text(_hm(e['ts']), style: TextStyle(color: p.textMuted, fontSize: 11)),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            'Move ${e['move_pct']}% · vol ${e['vol_ratio']}x · BEFORE the move: SD ${before['sd_label'] ?? '?'} · '
            'Z ${before['z'] ?? '?'} · TSI ${before['tsi'] ?? '?'}',
            style: TextStyle(color: p.textSecondary, fontSize: 12),
          ),
          const SizedBox(height: 4),
          Text(
            'After → $outcome (${e['after_ret'] ?? 0}%)  max↑ ${e['after_max_up']}%  max↓ ${e['after_max_dn']}%',
            style: TextStyle(color: outColor, fontSize: 12, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}
