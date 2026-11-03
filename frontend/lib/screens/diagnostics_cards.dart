import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 16 (FILE 33): the SMALL cards of the Diagnostics tab (screens/system_health_screen.dart). Read only, nothing is measured or guessed here.
///  - DiagCompactCards: ALL measured checks in ONE card, one thin row each (state dot, title, small line, value on the right). It replaces the old two-by-two big cards, so the whole list fits on one screen.
///  - DiagNotMeasured: the old big "Not measured yet" card is now ONE small closed line "Not measured yet (N)"; tap it to open the list with the reasons. Nothing is hidden for good and nothing is faked.
/// The data is the backend's own (GET /api/v2/sys_health): cards {title, value, sub, state OK / WARN / BAD / NOT AVAILABLE} and not_measured {title, why}. Dart NOT compiled (the APK build is the proof).

Color _col(AppPalette p, String s) => s == 'OK' ? p.profit : s == 'WARN' ? p.warning : s == 'BAD' ? p.loss : p.textMuted;

class DiagCompactCards extends StatelessWidget {
  final List<Map<String, dynamic>> cards;
  const DiagCompactCards({super.key, required this.cards});

  Widget _row(AppPalette p, Map<String, dynamic> x) {
    final s = '${x['state'] ?? 'NOT AVAILABLE'}';
    final sub = '${x['sub'] ?? ''}';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
        Icon(Icons.circle, size: 9, color: _col(p, s)),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${x['title'] ?? ''}', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textPrimary)),
            if (sub.isNotEmpty) Text(sub, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
          ]),
        ),
        const SizedBox(width: 8),
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 140),
          child: Text('${x['value'] ?? '-'}',
              textAlign: TextAlign.right, maxLines: 2, overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800, color: s == 'NOT AVAILABLE' ? p.textMuted : p.textPrimary)),
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (cards.isEmpty) return const SizedBox.shrink();
    return OWLCard(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Column(children: [
        for (var i = 0; i < cards.length; i++) ...[
          if (i > 0) Divider(height: 1, thickness: 0.5, color: p.border),
          _row(p, cards[i]),
        ],
      ]),
    );
  }
}

class DiagNotMeasured extends StatefulWidget {
  final List<Map<String, dynamic>> items;
  const DiagNotMeasured({super.key, required this.items});

  @override
  State<DiagNotMeasured> createState() => _DiagNotMeasuredState();
}

class _DiagNotMeasuredState extends State<DiagNotMeasured> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (widget.items.isEmpty) return const SizedBox.shrink();
    return OWLCard(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        InkWell(
          onTap: () => setState(() => _open = !_open),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(children: [
              Expanded(child: Text('Not measured yet (${widget.items.length})', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textSecondary))),
              Icon(_open ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 20, color: p.textMuted),
            ]),
          ),
        ),
        if (_open) ...[
          Text('These are never faked: the backend has no real number for them.', style: TextStyle(fontSize: 11, color: p.textMuted)),
          const SizedBox(height: 6),
          for (final x in widget.items)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text('${x['title']}: ${x['why']}', style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
            ),
          const SizedBox(height: 6),
        ],
      ]),
    );
  }
}
