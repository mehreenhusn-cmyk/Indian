// Part 25 (Diagnostics 3 of 4): bounded history of the 6 health checks.
// Pure Dart, no Flutter import, no provider, no network.
// Only CHANGES of level are stored (ok / warn / bad / unknown), never every tick.
// Memory only: the list is empty again after the app restarts (stated on the screen).

import 'diag_status.dart';

String diagLevelWord(DiagLevel? l) {
  switch (l) {
    case DiagLevel.ok:
      return 'OK';
    case DiagLevel.warn:
      return 'WARN';
    case DiagLevel.bad:
      return 'BAD';
    case DiagLevel.unknown:
      return 'UNKNOWN';
    case null:
      return 'START';
  }
}

class DiagEvent {
  final DateTime at;
  final String key;
  final String title;
  final DiagLevel? from; // null = first reading of this check
  final DiagLevel to;
  final String detail;

  const DiagEvent(this.at, this.key, this.title, this.from, this.to, this.detail);

  static String _two(int n) => n < 10 ? '0$n' : '$n';

  String get clock => '${_two(at.hour)}:${_two(at.minute)}:${_two(at.second)}';

  /// One plain line, safe to copy (no keys, no tokens, no private data).
  String get line => '$clock  $title  ${diagLevelWord(from)} -> ${diagLevelWord(to)}  $detail';
}

class DiagHistory {
  DiagHistory({this.maxEvents = 200});

  /// The one shared history (the Dashboard card and the detail screen both write into it).
  static final DiagHistory instance = DiagHistory();

  final int maxEvents;
  final List<DiagEvent> _events = []; // newest first
  final Map<String, DiagLevel> _last = {};
  final Map<String, DateTime> _since = {};
  int _total = 0;

  List<DiagEvent> get events => List.unmodifiable(_events);

  /// Counts every event ever recorded (does not go down when old ones are dropped).
  int get total => _total;

  /// When the check got its current level (null = never seen).
  DateTime? since(String key) => _since[key];

  /// Records only level changes. A first reading of UNKNOWN is not an event.
  /// Safe to call on every rebuild: the same status twice adds nothing.
  int record(DiagStatus s, {DateTime? now}) {
    final t = now ?? DateTime.now();
    var added = 0;
    for (final i in s.items) {
      final prev = _last[i.key];
      if (prev == i.level) continue;
      _last[i.key] = i.level;
      _since[i.key] = t;
      if (prev == null && i.level == DiagLevel.unknown) continue;
      _events.insert(0, DiagEvent(t, i.key, i.title, prev, i.level, i.detail));
      _total++;
      added++;
    }
    while (_events.length > maxEvents) {
      _events.removeLast();
    }
    return added;
  }

  /// Newest first. key = null gives all 6 checks.
  List<DiagEvent> forKey(String? key) =>
      key == null ? events : _events.where((e) => e.key == key).toList();

  String asText({String? key}) {
    final rows = forKey(key);
    if (rows.isEmpty) return 'No changes recorded yet.';
    return rows.map((e) => e.line).join('\n');
  }

  void clear() {
    _events.clear();
    _last.clear();
    _since.clear();
  }
}
