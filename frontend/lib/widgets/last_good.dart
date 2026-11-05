import 'dart:async';
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// R8: keep the LAST GOOD answer of a screen. A failed refresh never wipes the screen: the old numbers stay, the line on top says
/// "Could not refresh" and offers Retry. Use: final _lg = LastGood();  in _load():  _lg.take(r, _bad(r)); _r = _lg.data;
/// Nothing here talks to the backend. Dart NOT compiled (the APK build is the proof).
class LastGood {
  Map<String, dynamic>? data; // what the screen shows (last good answer, or the first bad one when nothing good exists yet)
  DateTime? at; // when the last GOOD answer arrived
  bool failed = false; // the newest try failed while an older good answer is kept
  bool hasGood = false;

  void reset() {
    data = null;
    at = null;
    failed = false;
    hasGood = false;
  }

  void take(Map<String, dynamic>? r, bool isBad) {
    if (!isBad) {
      data = r;
      at = DateTime.now();
      failed = false;
      hasGood = true;
    } else if (hasGood) {
      failed = true; // keep the old data
    } else {
      data = r;
      failed = false;
    }
  }

  /// "40s", "5 min", "2 h 10 min" (over 60 minutes = hours + minutes, owner rule).
  static String ago(DateTime? t) {
    if (t == null) return 'not yet';
    final s = DateTime.now().difference(t).inSeconds;
    if (s < 5) return 'just now';
    if (s < 90) return '${s}s ago';
    final m = (s / 60).round();
    if (m < 60) return '$m min ago';
    if (m < 1440) return '${m ~/ 60} h ${m % 60} min ago';
    return '${m ~/ 1440} d ago';
  }
}

/// Part 6: THE one stale mark for a card (Dashboard cards use it, same words everywhere). [at] = when the last GOOD answer arrived.
///   failed + old data  ->  "Last known, 5 min ago" (amber)      refreshing + old data  ->  "Updating..." (grey)      otherwise nothing.
/// It never shows when there is no old data yet (then the card shows its own Loading / -- line). No number is made up.
class StaleMark extends StatelessWidget {
  final DateTime? at;
  final bool failed, updating;
  const StaleMark({super.key, required this.at, this.failed = false, this.updating = false});

  @override
  Widget build(BuildContext context) {
    if (at == null || (!failed && !updating)) return const SizedBox.shrink();
    final p = context.palette;
    final text = failed ? 'Last known, ${LastGood.ago(at)}' : 'Updating...';
    return Text(text, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata.copyWith(fontSize: 11, color: failed ? p.warning : p.textMuted));
  }
}

/// ONE small line on top of a screen: optional 1-line summary, then "Updated 40s ago". After a failed refresh it turns into
/// "Could not refresh. Showing data from 40s ago." with a Retry button. The label moves on by itself every 5 seconds.
class UpdatedLine extends StatefulWidget {
  final LastGood lg;
  final VoidCallback onRetry;
  final String summary;
  const UpdatedLine({super.key, required this.lg, required this.onRetry, this.summary = ''});

  @override
  State<UpdatedLine> createState() => _UpdatedLineState();
}

class _UpdatedLineState extends State<UpdatedLine> {
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(const Duration(seconds: 5), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final lg = widget.lg;
    final failed = lg.failed;
    final text = failed ? 'Could not refresh. Showing data from ${LastGood.ago(lg.at)}.' : 'Updated ${LastGood.ago(lg.at)}';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (widget.summary.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 2),
          child: Text(widget.summary, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: p.textPrimary)),
        ),
      Row(children: [
        Expanded(child: Text(text, style: TextStyle(fontSize: 11, color: failed ? p.warning : p.textMuted))),
        if (failed) TextButton(onPressed: widget.onRetry, style: TextButton.styleFrom(visualDensity: VisualDensity.compact, padding: const EdgeInsets.symmetric(horizontal: 8)), child: const Text('Retry')),
      ]),
    ]);
  }
}
