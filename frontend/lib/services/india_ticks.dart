import 'dart:async';

import 'package:flutter/foundation.dart';

import 'india_api.dart';

/// Live index prices for the India screens. Polls the tiny /ticks answer about once a second (the backend fills it from the
/// Fyers WebSocket, so there is no broker call and no big payload). Screens listen to [data] and call start() / stop().
///
///   data.value = {'live': bool, 'mode': 'WEBSOCKET' | 'REST' | 'DEMO', 'spots': {'NIFTY': {'lp': 22850.15, 'at': epochSec, 'age_ms': 120}}}
class IndiaTicks {
  IndiaTicks._();
  static final IndiaTicks instance = IndiaTicks._();

  final ValueNotifier<Map<String, dynamic>> data = ValueNotifier<Map<String, dynamic>>(<String, dynamic>{});
  Timer? _timer;
  IndiaApi? _api;
  int _users = 0;
  bool _busy = false;

  void start(IndiaApi api) {
    _api = api;
    _users++;
    _timer ??= Timer.periodic(const Duration(milliseconds: 800), (_) => _poll());
    _poll();
  }

  void stop() {
    if (_users > 0) _users--;
    if (_users == 0) {
      _timer?.cancel();
      _timer = null;
    }
  }

  Future<void> _poll() async {
    final api = _api;
    if (api == null || _busy) return;
    _busy = true;
    try {
      final d = await api.get('/ticks', const Duration(seconds: 3));
      if (d is Map) data.value = Map<String, dynamic>.from(d);
    } catch (_) {
      // keep the last prices; the chart's own reload shows the error text
    } finally {
      _busy = false;
    }
  }
}
