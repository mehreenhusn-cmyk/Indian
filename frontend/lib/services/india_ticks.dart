import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'package:web_socket_channel/web_socket_channel.dart';

import 'india_api.dart';

/// Live index (+ optional option) prices for the India screens.
/// Part 7: prices are PUSHED over a WebSocket (/api/india/ws_ticks). Polling /ticks is only the fallback while the socket is down.
/// Polls /ticks about once a second when needed. Screens listen to [data] and call start()/stop().
///
/// data.value keys: live, mode, spots, opts, speed, now
class IndiaTicks {
  IndiaTicks._();
  static final IndiaTicks instance = IndiaTicks._();

  final ValueNotifier<Map<String, dynamic>> data = ValueNotifier<Map<String, dynamic>>(<String, dynamic>{});
  Timer? _timer;
  IndiaApi? _api;
  int _users = 0;
  bool _busy = false;
  List<String> _optSyms = const [];
  WebSocketChannel? _ws;
  StreamSubscription? _wsSub;
  Timer? _wsRetry;
  DateTime _lastPush = DateTime.fromMillisecondsSinceEpoch(0);
  int _wsFails = 0;

  bool get _pushing => DateTime.now().difference(_lastPush).inMilliseconds < 3000;

  void _sendOpts() {
    try {
      _ws?.sink.add(jsonEncode({'opt': _optSyms}));
    } catch (_) {}
  }

  void _openWs() {
    final api = _api;
    if (api == null || _ws != null || _users == 0) return;
    try {
      final url = api.base.replaceFirst(RegExp(r'^http'), 'ws') + '/api/india/ws_ticks';
      final ch = WebSocketChannel.connect(Uri.parse(url));
      _ws = ch;
      _sendOpts();
      _wsSub = ch.stream.listen((m) {
        try {
          final d = jsonDecode(m as String);
          if (d is Map) {
            _lastPush = DateTime.now();
            _wsFails = 0;
            data.value = Map<String, dynamic>.from(d);
          }
        } catch (_) {}
      }, onError: (_) => _wsDown(), onDone: _wsDown, cancelOnError: true);
    } catch (_) {
      _wsDown();
    }
  }

  void _wsDown() {
    _wsSub?.cancel();
    _wsSub = null;
    _ws = null;
    if (_users == 0) return;
    _wsFails++;
    final secs = _wsFails < 3 ? 1 : (_wsFails < 6 ? 3 : 8);
    _wsRetry?.cancel();
    _wsRetry = Timer(Duration(seconds: secs), _openWs);
  }

  void _closeWs() {
    _wsRetry?.cancel();
    _wsSub?.cancel();
    _wsSub = null;
    try {
      _ws?.sink.close();
    } catch (_) {}
    _ws = null;
  }

  /// Option symbols the visible chain / open paper positions need (capped 40).
  void setOptSymbols(List<String> syms) {
    final next = syms.where((s) => s.isNotEmpty).take(40).toList();
    if (listEquals(next, _optSyms)) return;
    _optSyms = next;
    _sendOpts();
    _poll(); // refresh soon with new list
  }

  void start(IndiaApi api) {
    _api = api;
    _users++;
    _openWs();
    _timer ??= Timer.periodic(const Duration(milliseconds: 800), (_) => _poll());
    _poll();
  }

  void stop() {
    if (_users > 0) _users--;
    if (_users == 0) {
      _timer?.cancel();
      _timer = null;
      _closeWs();
    }
  }

  Future<void> _poll() async {
    final api = _api;
    if (api == null || _busy || _pushing) return; // socket is delivering prices: no need to ask
    _busy = true;
    try {
      var path = '/ticks';
      if (_optSyms.isNotEmpty) {
        path = '/ticks?opt=${Uri.encodeQueryComponent(_optSyms.join(','))}';
      }
      final d = await api.get(path, const Duration(seconds: 3));
      if (d is Map) data.value = Map<String, dynamic>.from(d);
    } catch (_) {
      // keep last prices
    } finally {
      _busy = false;
    }
  }
}

/// One muted line: "feed: WEBSOCKET, price age 180 ms, chain 2.0 s".
/// Tap shows the full speed map in a simple dialog via [onTap].
class IndiaSpeedLine extends StatelessWidget {
  final VoidCallback? onTap;
  const IndiaSpeedLine({super.key, this.onTap});

  @override
  Widget build(BuildContext context) {
    // imported by screens that already have material + theme
    return ValueListenableBuilder<Map<String, dynamic>>(
      valueListenable: IndiaTicks.instance.data,
      builder: (context, d, _) {
        final speed = (d['speed'] is Map) ? Map<String, dynamic>.from(d['speed'] as Map) : <String, dynamic>{};
        final mode = (d['mode'] ?? speed['mode'] ?? '--').toString();
        final spots = (d['spots'] is Map) ? d['spots'] as Map : {};
        int? age;
        for (final v in spots.values) {
          if (v is Map && v['age_ms'] is num) {
            final a = (v['age_ms'] as num).toInt();
            if (age == null || a < age) age = a;
          }
        }
        final chainAvg = speed['chain_avg_s'];
        final parts = <String>[
          'feed: $mode',
          if (age != null) 'price age $age ms',
          if (chainAvg != null) 'chain ${chainAvg}s',
        ];
        final text = parts.join(', ');
        return GestureDetector(
          onTap: onTap ??
              () {
                // full numbers as a simple snack / dialog is left to the screen
              },
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 2),
            child: Text(
              text.isEmpty ? 'feed: --' : text,
              style: const TextStyle(fontSize: 11, color: Color(0xFF888888)),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        );
      },
    );
  }
}
