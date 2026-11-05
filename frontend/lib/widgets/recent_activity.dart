import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../screens/learning_progress_cards.dart' show lpList;
import '../screens/timeline_cards.dart' show tlEvent;
import '../screens/timeline_screen.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'owl_route.dart';
import 'owl_sub_page.dart';

/// Plan B: RECENT ACTIVITY block of the Dashboard (picture ref3). The newest few lines of the Brain and Activity timeline (GET /api/v2/brain_timeline, PAPER, today),
/// Brain and Bot named as they really are (never "AI"). Read only, no numbers made up: when the route is off or fails the block says "--" and nothing else.
/// "View all" opens the full timeline screen. Dart NOT compiled (the APK build is the proof).
class RecentActivity extends StatefulWidget {
  final int count;
  const RecentActivity({super.key, this.count = 5});

  @override
  State<RecentActivity> createState() => _RecentActivityState();
}

class _RecentActivityState extends State<RecentActivity> {
  Map<String, dynamic>? _r;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await context.read<AppProvider>().fetchBrainTimeline('PAPER', null).timeout(const Duration(seconds: 12));
      if (!mounted) return;
      final ok = r['ready'] == true && r['state'] == null && r['error'] == null;
      setState(() {
        if (ok) {
          _r = r;
          _failed = false;
        } else if (_r == null) {
          _failed = true; // last good data stays on screen if a later refresh fails
        }
      });
    } catch (_) {
      if (mounted && _r == null) setState(() => _failed = true);
    }
  }

  void _openAll() {
    Navigator.of(context).push(OwlRoute(builder: (_) => const OwlSubPage(title: 'Brain and Activity', child: TimelineScreen())));
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final events = _r == null ? <Map<String, dynamic>>[] : lpList(_r!['events']);
    final shown = events.take(widget.count).toList();
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.cardPad),
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('RECENT ACTIVITY', style: context.type.label.copyWith(letterSpacing: 1.0, fontWeight: FontWeight.w700))),
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: _openAll,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 4),
              child: Text('View all', style: context.type.metadata.copyWith(color: p.accent, fontWeight: FontWeight.w700)),
            ),
          ),
        ]),
        const SizedBox(height: 4),
        if (_r == null && !_failed) Text('Loading...', style: context.type.metadata),
        if (_r == null && _failed) Text('-- (timeline not available right now)', style: context.type.metadata.copyWith(color: p.textMuted)),
        if (_r != null && shown.isEmpty) Text('No activity yet today.', style: context.type.metadata),
        for (final e in shown) tlEvent(p, e),
      ]),
    );
  }
}
