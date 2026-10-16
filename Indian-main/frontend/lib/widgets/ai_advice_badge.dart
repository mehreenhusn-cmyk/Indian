import 'dart:async';
import 'package:flutter/material.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'package:provider/provider.dart';

/// Display-only AI advice above a position card, e.g. "AI: skip - sideways, TSI aur Z alag".
/// The bot NEVER blocks or closes anything because of this. One shared fetch (every 30 s) for ALL
/// cards, answered from stored Shadow Lab rows on the backend (no live candle fetching).
class _AdviceFeed {
  static final ValueNotifier<Map<String, dynamic>> badges = ValueNotifier<Map<String, dynamic>>({});
  static int _users = 0;
  static Timer? _timer;
  static bool _busy = false;

  static void join(AppProvider pr) {
    _users++;
    if (_timer == null) {
      _pull(pr);
      _timer = Timer.periodic(const Duration(seconds: 30), (_) => _pull(pr));
    }
  }

  static void leave() {
    _users--;
    if (_users <= 0) {
      _users = 0;
      _timer?.cancel();
      _timer = null;
    }
  }

  static Future<void> _pull(AppProvider pr) async {
    if (_busy) return;
    _busy = true;
    try {
      final r = await pr.fetchAiAdvice();
      final b = r?['badges'];
      if (b is Map) badges.value = Map<String, dynamic>.from(b);
    } finally {
      _busy = false;
    }
  }
}

class AiAdviceBadge extends StatefulWidget {
  final dynamic tradeId;
  const AiAdviceBadge({super.key, required this.tradeId});

  @override
  State<AiAdviceBadge> createState() => _AiAdviceBadgeState();
}

class _AiAdviceBadgeState extends State<AiAdviceBadge> {
  @override
  void initState() {
    super.initState();
    _AdviceFeed.join(context.read<AppProvider>());
  }

  @override
  void dispose() {
    _AdviceFeed.leave();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (widget.tradeId == null) return const SizedBox.shrink();
    final p = context.palette;
    return ValueListenableBuilder<Map<String, dynamic>>(
      valueListenable: _AdviceFeed.badges,
      builder: (context, all, _) {
        final b = all[widget.tradeId.toString()];
        if (b is! Map) return const SizedBox.shrink();
        final lvl = (b['level'] ?? '').toString();
        final c = lvl == 'ok' ? p.profit : (lvl == 'skip' ? p.loss : (lvl == 'warn' ? p.warning : p.textMuted));
        return Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Align(
            alignment: Alignment.centerLeft,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: c.withOpacity(0.14),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: c.withOpacity(0.5), width: 0.7),
              ),
              child: Text((b['text'] ?? '').toString(),
                  style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: c)),
            ),
          ),
        );
      },
    );
  }
}
