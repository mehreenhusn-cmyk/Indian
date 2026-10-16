import 'format.dart';

enum SignalOutcomeKind { fresh, opened, open, win, loss, neutral, skipped }

/// What happened to a signal after it fired, derived from data the app
/// already has (no backend change): the trade alert that carries the same
/// `signal_no`, or a still-open position with that `signal_no`.
class SignalOutcome {
  final String label; // "SL HIT", "TP2 HIT", "OPEN - TP1", ...
  final SignalOutcomeKind kind;
  final double? pnl; // realized USDT, only for closed trades
  final Set<int> hitLevels; // TP levels the trade has touched

  const SignalOutcome(this.label, this.kind, {this.pnl, this.hitLevels = const {}});
}

Set<int> _hits(dynamic v) {
  if (v is! List) return <int>{};
  return {for (final e in v) if (int.tryParse('$e') != null) int.parse('$e')};
}

int _maxOf(Set<int> s) => s.reduce((a, b) => a > b ? a : b);

SignalOutcome resolveSignalOutcome(
  Map<String, dynamic> signal,
  List<dynamic> alerts,
  List<dynamic> positions,
) {
  final opened = signal['opened'] == true;
  if (!opened) {
    return signal['skip_reason'] != null
        ? const SignalOutcome('SKIPPED', SignalOutcomeKind.skipped)
        : const SignalOutcome('NEW', SignalOutcomeKind.fresh);
  }

  // Backend result (permanent closed-trade record) wins. It does not depend
  // on the Alerts list, which only keeps the last 250 alerts.
  final res = signal['result'];
  if (res is Map) {
    final state = '${res['state']}';
    final hit = _hits(res['tp_hit_levels']);
    final pnl = numOrNull(res['pnl']);
    if (state == 'open') {
      return SignalOutcome(hit.isEmpty ? 'OPEN' : 'OPEN · TP${_maxOf(hit)}', SignalOutcomeKind.open, hitLevels: hit);
    }
    if (state == 'closed') {
      SignalOutcomeKind byPnl() => (pnl ?? 0) > 0 ? SignalOutcomeKind.win : ((pnl ?? 0) < 0 ? SignalOutcomeKind.loss : SignalOutcomeKind.neutral);
      switch ('${res['exit_tag']}') {
        case 'TP':
          final lvl = int.tryParse('${res['target_level']}') ?? (hit.isEmpty ? null : _maxOf(hit));
          return SignalOutcome(lvl == null ? 'TP HIT' : 'TP$lvl HIT', SignalOutcomeKind.win, pnl: pnl, hitLevels: hit);
        case 'SCALP':
          return SignalOutcome('TP % HIT', SignalOutcomeKind.win, pnl: pnl, hitLevels: hit);
        case 'SL':
          return SignalOutcome(hit.isEmpty ? 'SL HIT' : 'TP${_maxOf(hit)} → SL', byPnl(), pnl: pnl, hitLevels: hit);
        case 'TSL':
          return SignalOutcome('TRAIL SL', byPnl(), pnl: pnl, hitLevels: hit);
        case 'REV':
          return SignalOutcome('REVERSED', SignalOutcomeKind.neutral, pnl: pnl, hitLevels: hit);
        case 'MAN':
          return SignalOutcome('MANUAL', byPnl(), pnl: pnl, hitLevels: hit);
        default:
          return SignalOutcome('CLOSED', byPnl(), pnl: pnl, hitLevels: hit);
      }
    }
    // Opened, but no trade record matches (very old signal): never call it open.
    return const SignalOutcome('OLD', SignalOutcomeKind.neutral);
  }

  final no = signal['signal_no'];
  final sym = signal['symbol'];
  if (no == null) return const SignalOutcome('OPENED', SignalOutcomeKind.opened);

  bool same(Map d) => '${d['signal_no']}' == '$no' && (d['symbol'] == null || sym == null || '${d['symbol']}' == '$sym');

  // Alerts are newest-first and one alert per trade (updated in place), but
  // prefer a closed one if more than one matches.
  Map<String, dynamic>? match;
  for (final a in alerts) {
    if (a is! Map || a['d'] is! Map) continue;
    final d = Map<String, dynamic>.from(a['d'] as Map);
    if (!same(d)) continue;
    if (d['exit_tag'] != null) {
      match = d;
      break;
    }
    match ??= d;
  }

  if (match != null) {
    final hit = _hits(match['tp_hit_levels']);
    final pnl = numOrNull(match['pnl']);
    final tag = match['exit_tag'];
    if (tag == null) {
      return SignalOutcome(hit.isEmpty ? 'OPEN' : 'OPEN · TP${_maxOf(hit)}', SignalOutcomeKind.open, hitLevels: hit);
    }
    SignalOutcomeKind byPnl() => (pnl ?? 0) > 0 ? SignalOutcomeKind.win : ((pnl ?? 0) < 0 ? SignalOutcomeKind.loss : SignalOutcomeKind.neutral);
    switch ('$tag') {
      case 'TP':
        final lvl = int.tryParse('${match['target_level']}') ?? (hit.isEmpty ? null : _maxOf(hit));
        return SignalOutcome(lvl == null ? 'TP HIT' : 'TP$lvl HIT', SignalOutcomeKind.win, pnl: pnl, hitLevels: hit);
      case 'SCALP':
        return SignalOutcome('TP % HIT', SignalOutcomeKind.win, pnl: pnl, hitLevels: hit);
      case 'SL':
        return SignalOutcome(hit.isEmpty ? 'SL HIT' : 'TP${_maxOf(hit)} → SL', byPnl(), pnl: pnl, hitLevels: hit);
      case 'TSL':
        return SignalOutcome('TRAIL SL', byPnl(), pnl: pnl, hitLevels: hit);
      case 'REV':
        return SignalOutcome('REVERSED', SignalOutcomeKind.neutral, pnl: pnl, hitLevels: hit);
      case 'MAN':
        return SignalOutcome('MANUAL', byPnl(), pnl: pnl, hitLevels: hit);
      default:
        return SignalOutcome('CLOSED', byPnl(), pnl: pnl, hitLevels: hit);
    }
  }

  // No alert (older than the alert cap) - maybe still an open position.
  for (final p in positions) {
    if (p is! Map) continue;
    if ('${p['signal_no']}' == '$no' && (p['symbol'] == null || sym == null || '${p['symbol']}' == '$sym')) {
      final hit = _hits(p['tp_hit_levels']);
      return SignalOutcome(hit.isEmpty ? 'OPEN' : 'OPEN · TP${_maxOf(hit)}', SignalOutcomeKind.open, hitLevels: hit);
    }
  }
  return const SignalOutcome('OPENED', SignalOutcomeKind.opened);
}
