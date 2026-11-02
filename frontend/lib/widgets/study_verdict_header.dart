import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/verdict_card.dart';
import '../providers/app_provider.dart';
import 'purpose_strip.dart';
import 'verdict_header_card.dart';

/// Round 10a: the top of an OLD study screen (Tag Lab, Stop-wick, Setup Finder). Drop it in as the first child:
///   const StudyVerdictHeader(cardId: 'stopwick', why: '...', what: '...')
/// It shows the PURPOSE STRIP (WHY / WHAT, UI rule 10) at once, then loads GET /api/v2/verdicts once and adds the VerdictHeaderCard of [cardId]
/// (verdict badge, headline, and for NOT ENOUGH DATA: what is missing, how much, when, what to do). If the route is off, old or fails, only the
/// purpose strip stays: the screen below never breaks because of this header. It loads when the screen opens (pull-to-refresh does not reload it).
class StudyVerdictHeader extends StatefulWidget {
  final String cardId;
  final String why;
  final String what;

  const StudyVerdictHeader({super.key, required this.cardId, required this.why, required this.what});

  @override
  State<StudyVerdictHeader> createState() => _StudyVerdictHeaderState();
}

class _StudyVerdictHeaderState extends State<StudyVerdictHeader> {
  VerdictCard? _card;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchVerdicts();
    if (!mounted) return;
    VerdictCard? hit;
    for (final c in VerdictCard.listFrom(r['cards'])) {
      if (c.id == widget.cardId) hit = c;
    }
    if (hit != null) setState(() => _card = hit);
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PurposeStrip(why: widget.why, what: widget.what),
        if (_card != null) ...[const SizedBox(height: 10), VerdictHeaderCard(card: _card!)],
      ],
    );
  }
}
