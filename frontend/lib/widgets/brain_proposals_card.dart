import 'package:flutter/material.dart';

import '../models/brain_proposals.dart';
import '../theme/app_theme.dart';
import 'owl_card.dart';

/// Part 68: "Proposals (need your OK)". Shows B3 / G1 / G2 and which Ready Check conditions are still missing.
/// Read only: this card has no button and no switch. "Ready to ask" only means: you may ask Claude about it. Nothing is turned on by it.
class BrainProposalsCard extends StatelessWidget {
  final Map<String, dynamic> ready; // _st['ready']

  const BrainProposalsCard({super.key, required this.ready});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final list = buildBrainProposals(ready);
    final nReady = list.where((e) => e.state == ProposalState.ready).length;
    return OwlFold(
      title: 'PROPOSALS (NEED YOUR OK)',
      headline: nReady == 0 ? 'None ready to ask yet' : '$nReady ready to ask',
      headlineColor: nReady == 0 ? p.textMuted : p.accent,
      children: [
        Text(
          'Each proposal changes how the bot trades, so each needs your own separate OK. This card only shows what is still missing. It never switches anything on.',
          style: context.type.metadata,
        ),
        for (final e in list)
          Container(
            width: double.infinity,
            margin: const EdgeInsets.only(top: 8),
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(border: Border.all(color: p.border), borderRadius: BorderRadius.circular(12)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                OwlChip(
                  e.state == ProposalState.ready ? 'READY TO ASK' : (e.state == ProposalState.waiting ? 'WAITING' : 'NOT MEASURED'),
                  e.state == ProposalState.ready ? p.accent : (e.state == ProposalState.waiting ? p.textMuted : p.warning),
                ),
                Text(e.name, style: context.type.secondary),
              ]),
              Padding(padding: const EdgeInsets.only(top: 4), child: Text(e.what, style: context.type.metadata)),
              for (final m in e.missing) Padding(padding: const EdgeInsets.only(top: 2), child: Text('Missing: $m', style: context.type.metadata)),
            ]),
          ),
      ],
    );
  }
}
