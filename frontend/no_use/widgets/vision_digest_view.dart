import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../theme/app_spacing.dart';
import 'owl_refresh.dart';

/// Notebook digest: what the closed AI trades and the pump/dump memory say, and how to use it.
/// Every line comes from the backend (ai_notebook_digest.py). Small samples are labelled. The phone only draws it.
class VisionDigestView extends StatefulWidget {
  const VisionDigestView({super.key});

  @override
  State<VisionDigestView> createState() => _VisionDigestViewState();
}

class _VisionDigestViewState extends State<VisionDigestView> {
  Map<String, dynamic>? _data;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchVisionNotebookDigest();
    if (!mounted) return;
    setState(() {
      if (r != null) {
        _data = r;
        _failed = false;
      } else if (_data == null) {
        _failed = true;
      }
    });
  }

  List<String> _lines(dynamic x) => x is List ? x.map((e) => e.toString()).toList() : <String>[];

  Widget _card(AppPalette p, String title, List<String> lines, {Color? glow}) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: AppSpacing.cardGap),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
        border: Border.all(color: glow != null ? glow.withOpacity(0.45) : p.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: context.type.metadata.copyWith(fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.7)),
          const SizedBox(height: 8),
          for (final l in lines)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text(l, style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.4, fontSize: 12.5)),
            ),
          if (lines.isEmpty) Text('Nothing yet.', style: context.type.metadata),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    if (d == null) {
      return Center(
        child: _failed
            ? Column(mainAxisSize: MainAxisSize.min, children: [
                Text('Could not load the digest. It needs the newest backend.', style: context.type.metadata),
                TextButton(onPressed: _load, child: const Text('Retry')),
              ])
            : const CircularProgressIndicator(strokeWidth: 2),
      );
    }
    return OWLRefresh(
      onRefresh: _load,
      child: ListView(
        physics: owlPullPhysics,
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 96),
        children: [
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.s),
            child: Text('Plain counts from the AI\'s finished trades and the pump/dump memory. It is advice for you, it changes nothing in trading.',
                style: context.type.metadata.copyWith(height: 1.4)),
          ),
          _card(p, 'USE IT THIS WAY', _lines(d['use']), glow: p.accent),
          _card(p, 'AI TRADES (${d['closed_n'] ?? 0} FINISHED)', _lines(d['trade_lines'])),
          _card(p, 'PUMP / DUMP MEMORY', _lines(d['pump_lines'])),
        ],
      ),
    );
  }
}
