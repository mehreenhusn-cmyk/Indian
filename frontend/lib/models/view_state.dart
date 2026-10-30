// Part 28: ONE rule for "what must this screen show right now?" (pure Dart: no import, no provider, no network).
// Before: every screen decided by itself, so a screen with no data and a dead backend could say "No open positions"
// (looks like a real empty list) instead of "Backend offline". Now they all ask this function.

enum ViewState { content, loading, empty, error, offline }

/// Order of the rules when there is NO data to show:
/// offline first (the backend is not reachable, an empty list would be a lie), then error, then loading (first load
/// not finished yet), else the list is really empty. When there IS data the screen shows it (content), always.
ViewState decideViewState({
  required bool hasData,
  bool firstLoadDone = true,
  bool offline = false,
  bool hasError = false,
}) {
  if (hasData) return ViewState.content;
  if (offline) return ViewState.offline;
  if (hasError) return ViewState.error;
  if (!firstLoadDone) return ViewState.loading;
  return ViewState.empty;
}

/// True when the last update is older than [afterSec]. Unknown age (null) is NOT called stale: no guessing.
bool isStaleAge(num? ageSec, {num afterSec = 30}) => ageSec != null && ageSec > afterSec;

/// Plain age text. Owner rule: over 60 minutes = hours + minutes ("2 h 10 min"), never "130 min".
String ageText(num sec) {
  final s = sec < 0 ? 0 : sec.floor();
  if (s < 60) return '$s s';
  final m = s ~/ 60;
  if (m < 60) return '$m min';
  final h = m ~/ 60;
  final r = m % 60;
  return r == 0 ? '$h h' : '$h h $r min';
}
