import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'india_api.dart';

/// Live index (+ optional option) prices for the India screens.
/// Polls /ticks about once a second. Screens listen to [data] and call start()/stop().
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

  /// Option symbols the visible chain / open paper positions need (capped 40).
  void setOptSymbols(List<String> syms) {
    final next = syms.where((s) => s.isNotEmpty).take(40).toList();
    if (listEquals(next, _optSyms)) return;
    _optSyms = next;
    _poll(); // refresh soon with new list
  }

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
