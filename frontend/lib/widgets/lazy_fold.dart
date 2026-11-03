import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Part 46 (FILE 55): ONE closed fold that builds its content only when the owner opens it the first time (so the page asks the backend for nothing until then),
/// and keeps it built after that (closing and opening again does not ask again; the card has its own Retry). Study Lab rule: summary on top, detail collapsed below.
/// Use: LazyFold(title: 'Risk Box', sub: 'BTCUSDT', builder: () => RiskBox(symbol: 'BTCUSDT')). Dart NOT compiled (the APK build is the proof).
class LazyFold extends StatefulWidget {
  final String title;
  final String sub;
  final Widget Function() builder;
  const LazyFold({super.key, required this.title, this.sub = '', required this.builder});

  @override
  State<LazyFold> createState() => _LazyFoldState();
}

class _LazyFoldState extends State<LazyFold> {
  Widget? _child;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: p.textMuted.withOpacity(0.25))),
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 14),
          childrenPadding: const EdgeInsets.fromLTRB(8, 0, 8, 10),
          maintainState: true,
          title: Text(widget.title, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
          subtitle: widget.sub.isEmpty ? null : Text(widget.sub, style: TextStyle(fontSize: 11.5, color: p.textMuted)),
          expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
          onExpansionChanged: (open) {
            if (open && _child == null) setState(() => _child = widget.builder());
          },
          children: [if (_child != null) _child!],
        ),
      ),
    );
  }
}
