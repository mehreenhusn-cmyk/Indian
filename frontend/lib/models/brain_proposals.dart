/// Part 68: the three Brain-to-trading proposals (B3, G1, G2) and whether the Ready Check says it is time to ASK the owner.
/// Pure Dart: no import, no provider, no network. It only READS the ready block the Brain view already has (rows with key and ok).
/// It never switches anything on. Every proposal changes trading behaviour, so each one needs the owner's own separate OK, always.
/// ok == true passed, false failed, null still collecting. A missing key or an empty block is "still collecting", never a made-up pass.
enum ProposalState { ready, waiting, notMeasured }

class BrainProposal {
  final String id;
  final String name;
  final String what;
  final ProposalState state;
  final List<String> missing;

  const BrainProposal({required this.id, required this.name, required this.what, required this.state, required this.missing});
}

List<Map<String, dynamic>> _rowsOf(Map<String, dynamic> ready) {
  final raw = ready['rows'];
  if (raw is! List) return <Map<String, dynamic>>[];
  return raw.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
}

bool? _okOf(List<Map<String, dynamic>> rows, String key) {
  for (final r in rows) {
    if ('${r['key']}' == key) {
      final v = r['ok'];
      return v is bool ? v : null;
    }
  }
  return null;
}

BrainProposal _gate(List<Map<String, dynamic>> rows, String id, String name, String what, Map<String, String> need) {
  final missing = <String>[];
  need.forEach((key, label) {
    final ok = _okOf(rows, key);
    if (ok != true) missing.add(ok == false ? '$label (not true yet)' : '$label (still collecting)');
  });
  return BrainProposal(id: id, name: name, what: what, state: missing.isEmpty ? ProposalState.ready : ProposalState.waiting, missing: missing);
}

/// B3, G1, G2 in this fixed order. Gates (README section 6): G1 needs checks 1, 2 and 3; G2 needs check 4; B3 needs Timing Sync stable
/// for 3+ days, which the Ready Check does not measure (its timing row is information only), so B3 is always "notMeasured" here.
List<BrainProposal> buildBrainProposals(Map<String, dynamic> ready) {
  final rows = _rowsOf(ready);
  return [
    const BrainProposal(
      id: 'B3',
      name: 'B3  Brain own trades prefer clean setups',
      what: 'The Brain\'s own paper trades softly prefer deep, clean setups.',
      state: ProposalState.notMeasured,
      missing: ['Timing sync stable for 3+ days (the Ready Check does not measure this)'],
    ),
    _gate(rows, 'G1', 'G1  Brain skips clearly bad signals', 'Paper only, switch default OFF. Turns itself off if trust falls back or the luck test says luck.',
        {'trust': 'Trust meter', 'luck': 'Luck test', 'whatif': 'What if the bot had listened'}),
    _gate(rows, 'G2', 'G2  Exit advice trails the stop', 'Paper only, switch default OFF. Exit advice may trail the stop.', {'exit': 'Exit advice hit-rate'}),
  ];
}
