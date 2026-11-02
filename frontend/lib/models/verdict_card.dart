/// Round 7a: one verdict card of GET /api/v2/verdicts (see backend/v2_verdicts.py for the schema).
/// Parsing is forgiving on purpose: a missing field becomes '' or 0, never the text "None" or "null".
class VerdictCard {
  final String id;
  final String title;
  final String verdict;
  final String headline;
  final String detail;
  final int n;
  final String caveat;
  final String reasonMissing;
  final int updatedAgoSec; // -1 = unknown
  final int needN;
  final int haveN;
  final String etaText;
  final String nextAction;

  const VerdictCard({
    required this.id,
    required this.title,
    required this.verdict,
    required this.headline,
    required this.detail,
    required this.n,
    required this.caveat,
    required this.reasonMissing,
    required this.updatedAgoSec,
    required this.needN,
    required this.haveN,
    required this.etaText,
    required this.nextAction,
  });

  static String _s(dynamic v) {
    if (v == null) return '';
    final t = v.toString().replaceAll(RegExp(r'\bNone\b'), 'n/a').replaceAll(RegExp(r'\bnull\b'), 'n/a');
    return t.trim();
  }

  static int _i(dynamic v, [int fallback = 0]) {
    if (v is int) return v;
    if (v is num) return v.toInt();
    return int.tryParse(_s(v)) ?? fallback;
  }

  factory VerdictCard.fromJson(Map<String, dynamic> j) => VerdictCard(
        id: _s(j['id']),
        title: _s(j['title']),
        verdict: _s(j['verdict']),
        headline: _s(j['headline']),
        detail: _s(j['detail']),
        n: _i(j['n']),
        caveat: _s(j['caveat']),
        reasonMissing: _s(j['reason_missing']),
        updatedAgoSec: _i(j['updated_ago_sec'], -1),
        needN: _i(j['need_n']),
        haveN: _i(j['have_n']),
        etaText: _s(j['eta_text']),
        nextAction: _s(j['next_action']),
      );

  /// True when the card could not decide: the screen then shows reasonMissing, have / need, eta and nextAction.
  bool get needsData => verdict.toUpperCase().replaceAll(' ', '_') == 'NOT_ENOUGH_DATA';

  /// 'n of need' text for a progress line, or '' when there is no target.
  String get progressText => needN > 0 ? '$haveN of $needN' : '';

  /// Parses the whole 'cards' list of the route answer; anything that is not a map is skipped.
  static List<VerdictCard> listFrom(dynamic cards) {
    if (cards is! List) return const [];
    return [
      for (final c in cards)
        if (c is Map) VerdictCard.fromJson(Map<String, dynamic>.from(c)),
    ];
  }
}
