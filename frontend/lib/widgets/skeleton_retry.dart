import 'dart:async';
import 'package:flutter/material.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'owl_pressable.dart';
import 'owl_row.dart';
import 'owl_skeleton.dart';

/// Part 13c (owner: no endless spinner): grey shimmer shapes in the layout of a screen while the FIRST data loads, the plain line "Fetching latest data...",
/// and after [slowAfter] (default 8 s) a plain "Still loading" line with a Retry button. Replaces LoadSpinner where a screen has a known layout (Sniper first).
/// Later loads never show this: the screen keeps its last good data (LastGood) and the "Updated Xs ago" line. Dart NOT compiled.
class SkeletonRetry extends StatefulWidget {
  final VoidCallback onRetry;
  final String what;
  final Duration slowAfter;
  const SkeletonRetry({super.key, required this.onRetry, this.what = 'latest data', this.slowAfter = const Duration(seconds: 8)});

  @override
  State<SkeletonRetry> createState() => _SkeletonRetryState();
}

class _SkeletonRetryState extends State<SkeletonRetry> {
  Timer? _timer;
  bool _slow = false;

  @override
  void initState() {
    super.initState();
    _timer = Timer(widget.slowAfter, () {
      if (mounted) setState(() => _slow = true);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const OWLSkeleton(width: 120, height: 26),
      const SizedBox(height: AppSpacing.s),
      const OWLSkeleton(width: 220, height: 14),
      const SizedBox(height: AppSpacing.l),
      const OwlRowSkeleton(rows: 3),
      const SizedBox(height: AppSpacing.l),
      Row(children: [
        Expanded(child: Text(_slow ? 'Still loading. The backend is slow or not reachable.' : 'Fetching ${widget.what}...', style: context.type.metadata.copyWith(color: _slow ? p.warning : p.textMuted))),
        if (_slow) OWLPressable(onTap: widget.onRetry, pressedScale: 0.97, child: Padding(padding: const EdgeInsets.all(8), child: Text('Retry', style: context.type.primary.copyWith(color: p.accent, fontWeight: FontWeight.w700)))),
      ]),
    ]);
  }
}
