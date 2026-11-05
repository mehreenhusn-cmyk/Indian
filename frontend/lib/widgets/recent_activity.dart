import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../screens/learning_progress_cards.dart' show lpList;
import '../screens/timeline_cards.dart' show tlEvent;
import '../screens/timeline_screen.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'owl_route.dart';
import 'last_good.dart';
import 'owl_sub_page.dart';

/// Plan B: RECENT ACTIVITY block of the Dashboard (picture ref3). The newest few lines of the Brain and Activity timeline (GET /api/v2/brain_timeline, PAPER, today),
/// Brain and Bot named as they really are (never "AI"). Read only, no numbers made up: when the route is off or fails the block says "--" and nothing else.
/// "View all" opens the full timeline screen. Dart NOT compiled (the APK build is the proof).
class RecentActivity extends StatefulWidget {
  final int count;
  const RecentActivity({super.key, this.count = 6}); // Part 6: 6 lines (was 5), then View all

  @override
  State<RecentActivity> createState() => _RecentActivityState();
}

class _RecentActivityState extends State<RecentActivity> {
  static Map<String, dynamic>? _cache; // Part 6: last good answer + its time, shown at once on the next visit
  static DateTime? _cacheAt;
  Map<String, dynamic>? _r = _cache;
  DateTime? _at = _cacheAt;
  bool _failed = false; // nothing good to show yet and the try failed
  bool _stale = false; // old data on screen and the newest try failed
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (_busy) return;
    _busy = true; // only called from initState, so no setState needed before the first build
    try {
      final r = await context.read<AppProvider>().fetchBrainTimeline('PAPER', null).timeout(const Duration(seconds: 12));
      if (!mounted) return;
      final ok = r['ready'] == true && r['state'] == null && r['error'] == null;
      setState(() {
        _busy = false;
        if (ok) {
          _r = r;
          _at = DateTime.now();
          _cache = r;
          _cacheAt = _at;
          _failed = false;
          _stale = false;
        } else if (_r == null) {
          _failed = true;
        } else {
          _stale = true; // last good data stays on screen, marked "Last known"
        }
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          _busy = false;
          if (_r == null) {
            _failed = true;
          } else {
            _stale = true;
          }
        });
      }
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
          Flexible(child: StaleMark(at: _at, failed: _stale, updating: _busy && !_stale)),
          const SizedBox(width: 8),
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
