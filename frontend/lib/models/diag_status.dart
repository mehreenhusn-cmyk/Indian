// Part 23 (Diagnostics 1 of 4): ONE shared status model for the 6 health checks.
// Pure Dart, no Flutter import, no provider, no network. Nothing reads it yet:
// Part 24 (health strip) and Part 25 (detail screen) will use it.
// Rule: a value that is not known is UNKNOWN (grey), never a made-up green.

enum DiagLevel { ok, warn, bad, unknown }

class DiagItem {
  final String key; // fixed id, e.g. 'ws'
  final String title; // short name shown on screen
  final DiagLevel level;
  final String detail; // one plain line: why this level

  const DiagItem(this.key, this.title, this.level, this.detail);
}

class DiagStatus {
  /// The 6 separate checks, always in this order.
  final List<DiagItem> items;

  const DiagStatus(this.items);

  static const List<String> keys = [
    'backend',
    'ws',
    'market_data',
    'scanner',
    'strategy',
    'execution',
  ];

  DiagItem? byKey(String k) {
    for (final i in items) {
      if (i.key == k) return i;
    }
    return null;
  }

  /// Worst level of all 6 (bad > warn > unknown > ok). Unknown is never counted as ok.
  DiagLevel get overall {
    var worst = DiagLevel.ok;
    for (final i in items) {
      if (i.level == DiagLevel.bad) return DiagLevel.bad;
      if (i.level == DiagLevel.warn) worst = DiagLevel.warn;
      if (i.level == DiagLevel.unknown && worst == DiagLevel.ok) worst = DiagLevel.unknown;
    }
    return worst;
  }

  int count(DiagLevel l) => items.where((i) => i.level == l).length;

  /// Builds the 6 items from plain values. null = not known.
  /// marketDataState = backend words: CONNECTING / LIVE / RECONNECTING / STALE / DISCONNECTED / REST.
  factory DiagStatus.fromInputs({
    bool? backendReachable,
    bool? wsConnected,
    double? liveAgeSec,
    String? marketDataState,
    bool? scannerActive,
    bool? strategyReady,
    bool? executionHealthy,
  }) {
    return DiagStatus([
      _flag('backend', 'Backend', backendReachable, 'Answering', 'Not answering'),
      _ws(wsConnected, liveAgeSec),
      _market(marketDataState),
      _flag('scanner', 'Scanner', scannerActive, 'Scanning coins', 'Not scanning'),
      _flag('strategy', 'Strategy', strategyReady, 'Ready', 'Not ready'),
      _flag('execution', 'Execution', executionHealthy, 'Healthy', 'Problem reported'),
    ]);
  }

  static DiagItem _flag(String key, String title, bool? v, String yes, String no) {
    if (v == null) return DiagItem(key, title, DiagLevel.unknown, 'Not known yet');
    return DiagItem(key, title, v ? DiagLevel.ok : DiagLevel.bad, v ? yes : no);
  }

  static DiagItem _ws(bool? connected, double? ageSec) {
    const t = 'WebSocket';
    if (connected == null) return const DiagItem('ws', t, DiagLevel.unknown, 'Not known yet');
    if (!connected) return const DiagItem('ws', t, DiagLevel.bad, 'Disconnected');
    if (ageSec == null) return const DiagItem('ws', t, DiagLevel.warn, 'Connected, no data yet');
    if (ageSec > 6) return DiagItem('ws', t, DiagLevel.bad, 'Quiet for ${ageSec.toStringAsFixed(0)} s');
    if (ageSec > 3) return DiagItem('ws', t, DiagLevel.warn, 'Delayed ${ageSec.toStringAsFixed(0)} s');
    return DiagItem('ws', t, DiagLevel.ok, 'Live, ${ageSec.toStringAsFixed(1)} s ago');
  }

  static DiagItem _market(String? state) {
    const t = 'Market data';
    switch (state) {
      case null:
        return const DiagItem('market_data', t, DiagLevel.unknown, 'Not known yet');
      case 'LIVE':
        return const DiagItem('market_data', t, DiagLevel.ok, 'Fresh (live stream)');
      case 'REST':
        return const DiagItem('market_data', t, DiagLevel.warn, 'Fallback (slower)');
      case 'CONNECTING':
      case 'RECONNECTING':
        return DiagItem('market_data', t, DiagLevel.warn, state == 'CONNECTING' ? 'Connecting' : 'Reconnecting');
      case 'STALE':
        return const DiagItem('market_data', t, DiagLevel.bad, 'Old data');
      case 'DISCONNECTED':
        return const DiagItem('market_data', t, DiagLevel.bad, 'No data');
      default:
        return const DiagItem('market_data', t, DiagLevel.unknown, 'Unknown state');
    }
  }
}
