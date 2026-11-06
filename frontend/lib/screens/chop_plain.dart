// Part E1 (README_CHOP): plain-English words for the b3 (Chop Bot) screens. Pure text helpers, no widgets, no network.
// The backend keeps its short technical rule names and why-texts (chop_filter.py / chop_bot.py); only the app changes how they read.
// Unknown texts fall back to the raw backend text, so a new rule never shows an empty line. Dart NOT compiled (the APK build is the proof).

/// Short friendly name of a backend rule (chop_bot.rule_of).
String chopRuleName(String rule) {
  switch (rule) {
    case 'chop gate':
      return 'Sideways market';
    case 'Z+TSI both against':
      return 'Indicators disagree';
    case 'late chase':
      return 'Price already ran';
    case 'fee check':
      return 'Too small after fees';
    case 'score cut-off':
      return 'Score too low';
    case 'bigger timeframe':
      return 'Bigger trend against';
    case 'late entry rejected':
      return 'Late entry not confirmed';
    case 'late entry':
      return 'Late entry';
    case 'breakout key':
      return 'Breakout entry';
    case 'take':
      return 'Clean entry';
    case 'other':
      return 'Other';
    default:
      return rule; // already a plain text (for example "not enough candles yet")
  }
}

String _num(String s) => s.trim();

/// One plain sentence for a decision. [d] = one row of GET /api/v2/chop_log decisions.
String chopPlainWhy(Map<String, dynamic> d) {
  final rule = '${d['rule'] ?? ''}';
  final why = '${d['why'] ?? ''}';
  final take = d['action'] == 'TAKE';
  if (take) {
    final z = RegExp(r'Z (\w+)').firstMatch(why)?.group(1) ?? '';
    final t = RegExp(r'TSI (\w+)').firstMatch(why)?.group(1) ?? '';
    final parts = <String>[];
    if (z == 'AGREE' && t == 'AGREE') {
      parts.add('Both the Z and TSI indicators agree with the signal.');
    } else if (t == 'AGREE') {
      parts.add('TSI agrees with the signal, Z is neutral, so half size.');
    } else {
      parts.add('The signal passed all checks.');
    }
    if (why.contains('breakout key')) parts.add('Price broke out of a sideways range.');
    if (rule == 'late entry') parts.add('Entered late, after the indicators confirmed.');
    return parts.join(' ');
  }
  switch (rule) {
    case 'chop gate':
      final bits = <String>[];
      if (why.contains('EMA flat')) bits.add('the trend line is flat');
      final m = RegExp(r'(\d+) EMA crosses in (\d+)').firstMatch(why);
      if (m != null) bits.add('price crossed the trend line ${m.group(1)} times in the last ${m.group(2)} candles');
      if (why.contains('stuck at SD middle')) bits.add('price is stuck in the middle of its range');
      return bits.isEmpty ? 'The market is moving sideways, so most signals here are fake.' : 'The market is moving sideways: ${bits.join(', ')}.';
    case 'Z+TSI both against':
      return 'The signal says one way, but both the Z and TSI indicators point the other way.';
    case 'late chase':
      final m = RegExp(r'past (\d+) SD').firstMatch(why);
      return 'Price had already moved ${m == null ? 'far' : 'past ${m.group(1)} SD'} in this direction. Too late to chase.';
    case 'fee check':
      final m = RegExp(r'target (\S+)% is under (\S+)%').firstMatch(why);
      return m == null ? 'The possible profit is too small to cover the trading fee.' : 'The target is only ${_num(m.group(1)!)}%, less than the ${_num(m.group(2)!)}% needed to cover fees.';
    case 'score cut-off':
      final m = RegExp(r'score (\S+) is under (\S+)').firstMatch(why);
      final brake = why.contains('brake') ? ' This coin lost 3 times in a row, so it needs a higher score.' : '';
      return m == null ? 'The quality score is too low.$brake' : 'Quality score ${m.group(1)} is below the ${m.group(2)} needed.$brake';
    case 'bigger timeframe':
      return 'The bigger timeframe trend points the other way.';
    case 'late entry rejected':
      if (why.contains('left the trigger side')) return 'Waited for confirmation, but price went back across the trend line.';
      if (why.contains('Z and TSI')) return 'Waited for confirmation, but the two indicators did not both agree.';
      return 'Waited for confirmation, but it did not come.';
    default:
      return why;
  }
}

/// Headline of a decision: "Taken, full size" / "Skipped: Sideways market".
String chopHeadline(Map<String, dynamic> d) {
  if (d['action'] == 'TAKE') {
    final size = '${d['size']}' == 'HALF' ? 'half size' : 'full size';
    return 'Taken, $size';
  }
  return 'Skipped: ${chopRuleName('${d['rule'] ?? ''}')}';
}

/// Score is shown only where it decided something: a taken trade, or a skip for a low score.
bool chopShowScore(Map<String, dynamic> d) => d['action'] == 'TAKE' || d['rule'] == 'score cut-off';

/// What the verdict means in words. -> (pill text, detail, good). pill null = still waiting.
({String? pill, String detail, bool good}) chopVerdict(Map<String, dynamic> d) {
  final v = d['verdict'];
  final label = '${d['v_label'] ?? ''}';
  final net = d['v_net'] is num ? (d['v_net'] as num).toDouble() : null;
  String pct(double x) => '${x >= 0 ? '+' : '-'}${x.abs().toStringAsFixed(2)}%';
  if (v == null || net == null) return (pill: null, detail: '', good: false);
  if (d['action'] == 'TAKE') {
    return label == 'WIN' ? (pill: 'WON', detail: pct(net), good: true) : (pill: 'LOST', detail: pct(net), good: false);
  }
  if (label == 'LOSS_AVOIDED') return (pill: 'GOOD SKIP', detail: 'it would have lost ${net.abs().toStringAsFixed(2)}%', good: true);
  if (label == 'RALLY_MISSED') return (pill: 'MISSED', detail: 'it would have made ${pct(net)}', good: false);
  return (pill: null, detail: '', good: false);
}

/// Plain name of how a closed trade ended.
String chopExitName(String reason) {
  switch (reason) {
    case 'STOP':
      return 'Stop hit';
    case 'TARGET':
      return 'Target hit';
    case 'REVERSED':
      return 'Closed: opposite signal';
    case 'TIME':
      return 'Time ran out';
    default:
      return reason;
  }
}

/// One line over the decision list: what happened in these decisions and why there may be no trade.
String chopSummaryLine(List<Map<String, dynamic>> dec, int openTrades) {
  if (dec.isEmpty) return '';
  var taken = 0, skipped = 0;
  final why = <String, int>{};
  for (final d in dec) {
    if (d['action'] == 'TAKE') {
      taken++;
    } else if (d['v_label'] != 'NA') {
      skipped++;
      final r = '${d['rule'] ?? ''}';
      why[r] = (why[r] ?? 0) + 1;
    }
  }
  var top = '';
  var topN = 0;
  why.forEach((k, v) {
    if (v > topN) {
      top = k;
      topN = v;
    }
  });
  final b = StringBuffer('Last ${dec.length} signals: $taken taken, $skipped skipped.');
  if (topN > 0) b.write(' Main reason for skipping: ${chopRuleName(top).toLowerCase()} ($topN).');
  if (taken == 0 && top == 'chop gate') b.write(' No trade yet because the market is sideways. That is the filter doing its job.');
  return b.toString();
}
