import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../theme/app_spacing.dart';

Map<String, dynamic> _m(dynamic x) =>
    x is Map ? Map<String, dynamic>.from(x) : <String, dynamic>{};
double? _d(dynamic x) {
  if (x is num) return x.toDouble();
  if (x is String) return double.tryParse(x);
  return null;
}

/// Bot signals vs AI-own paper trades (Results tab section).
class VisionCompareView extends StatefulWidget {
  const VisionCompareView({super.key});

  @override
  State<VisionCompareView> createState() => _VisionCompareViewState();
}

class _VisionCompareViewState extends State<VisionCompareView> {
  Map<String, dynamic>? _data;
  String? _err;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final d = await context.read<AppProvider>().fetchVisionCompare();
      if (!mounted) return;
      setState(() {
        _data = d;
        _err = d == null ? 'Could not reach backend' : null;
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

  Future<void> _toggle(bool on) async {
    await context.read<AppProvider>().setVisionOwnEnabled(on);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (_loading && _data == null) {
      return const Padding(
        padding: EdgeInsets.all(24),
        child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
      );
    }
    if (_err != null && _data == null) {
      return Padding(
        padding: const EdgeInsets.all(AppSpacing.l),
        child: Text(_err!, style: TextStyle(color: p.loss)),
      );
    }
    final d = _data ?? {};
    final bot = _m(d['bot']);
    final own = _m(d['own']);
    final scan = _m(d['own_scan']);
    final on = d['own_enabled'] == true;

    return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Bot signals vs AI own', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(child: _srcCard(p, 'Bot signals', bot)),
              const SizedBox(width: 8),
              Expanded(child: _srcCard(p, 'AI own', own)),
            ],
          ),
          const SizedBox(height: 12),
          Container(
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
                    Expanded(
                      child: Text(
                        on
                            ? 'AI own scan: ON, scanned ${scan['scanned'] ?? 0}, took ${scan['took'] ?? 0}'
                            : 'AI own scan: OFF',
                        style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w600, fontSize: 13),
                      ),
                    ),
                    Switch(
                      value: on,
                      onChanged: _toggle,
                      activeColor: p.accent,
                    ),
                  ],
                ),
                if ((scan['err'] ?? '').toString().isNotEmpty)
                  Text('${scan['err']}', style: TextStyle(color: p.warning, fontSize: 12)),
              ],
            ),
          ),
        ],
    );
  }

  Widget _srcCard(AppPalette p, String title, Map<String, dynamic> s) {
    final n = (_d(s['closed']) ?? 0).toInt();
    final net = _d(s['net']) ?? 0;
    final wr = _d(s['win_rate']);
    final small = s['small_sample'] == true;
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
          Text(title, style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w700, fontSize: 13)),
          const SizedBox(height: 6),
          Text('Closed $n', style: TextStyle(color: p.textMuted, fontSize: 12)),
          Text(
            'Net ${net >= 0 ? '+' : ''}${net.toStringAsFixed(2)}',
            style: TextStyle(color: net >= 0 ? p.profit : p.loss, fontWeight: FontWeight.w700),
          ),
          Text(
            wr == null ? 'Win rate --' : 'Win rate ${wr.toStringAsFixed(1)}%',
            style: TextStyle(color: p.textSecondary, fontSize: 12),
          ),
          if (small)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('SMALL SAMPLE', style: TextStyle(color: p.warning, fontSize: 11, fontWeight: FontWeight.w600)),
            ),
          if (s['verdict_ready'] != true)
            Text('No verdict under 30 trades', style: TextStyle(color: p.textMuted, fontSize: 11)),
        ],
      ),
    );
  }
}


/// One line + switch for the Live tab: is the AI own scan on, and what did it do.
class VisionOwnScanLine extends StatefulWidget {
  /// When false, only status text (no switch). Switch lives on the AI Own tab so two switches cannot disagree.
  final bool showSwitch;
  final VoidCallback? onOpenOwnTab;
  const VisionOwnScanLine({super.key, this.showSwitch = true, this.onOpenOwnTab});

  @override
  State<VisionOwnScanLine> createState() => _VisionOwnScanLineState();
}

class _VisionOwnScanLineState extends State<VisionOwnScanLine> {
  Map<String, dynamic>? _data;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await context.read<AppProvider>().fetchVisionCompare();
    if (!mounted) return;
    setState(() {
      _data = d;
      _failed = d == null;
    });
  }

  Future<void> _toggle(bool on) async {
    await context.read<AppProvider>().setVisionOwnEnabled(on);
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (_failed) {
      return Padding(
        padding: const EdgeInsets.only(bottom: AppSpacing.s),
        child: Text('AI own scan: backend is old or not reachable', style: TextStyle(color: p.textMuted, fontSize: 12)),
      );
    }
    final d = _data;
    if (d == null) return const SizedBox.shrink();
    final scan = _m(d['own_scan']);
    final on = d['own_enabled'] == true;
    final err = (scan['err'] ?? '').toString();
    final status = on
        ? 'AI own scan: ON. Scanned ${scan['scanned'] ?? 0}, asked AI ${scan['asked'] ?? 0}, took ${scan['took'] ?? 0}${err.isNotEmpty ? ' ($err)' : ''}'
        : 'AI own scan: OFF (paper only, uses AI quota)';
    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.s),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: p.border),
      ),
      child: Row(
        children: [
          Expanded(
            child: GestureDetector(
              onTap: widget.showSwitch ? null : widget.onOpenOwnTab,
              child: Text(
                widget.showSwitch ? status : '$status  ·  see AI Own tab',
                style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w600, fontSize: 12.5),
              ),
            ),
          ),
          if (widget.showSwitch)
            Switch(value: on, onChanged: _toggle, activeColor: p.accent),
        ],
      ),
    );
  }
}
