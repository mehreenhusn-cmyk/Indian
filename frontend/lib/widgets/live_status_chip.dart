import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'owl_status_pill.dart';

/// UI-LIVE: the ONE live-data chip for the whole app.
///   LIVE · 2 s          green  (socket up, data fresh)
///   DELAYED · 18 s      amber  (socket up but quiet, or old feed)
///   OFFLINE             red    (socket down; the screens say 'reconnecting' in their own text)
/// The state comes from AppProvider.liveState (no logic here). A 1 s timer only
/// repaints THIS chip when its text changes, so it never rebuilds a screen.
class LiveStatusChip extends StatefulWidget {
  const LiveStatusChip({super.key});

  @override
  State<LiveStatusChip> createState() => _LiveStatusChipState();
}

class _LiveStatusChipState extends State<LiveStatusChip> {
  Timer? _tick;
  String _text = '';
  String _state = 'offline';

  @override
  void initState() {
    super.initState();
    _read();
    _tick = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) _read(repaint: true);
    });
  }

  void _read({bool repaint = false}) {
    final pr = context.read<AppProvider>();
    final st = pr.liveState;
    final age = pr.liveAgeSec;
    final a = age == null ? '' : fmtSpan(age);
    final txt = st == 'offline'
        ? 'OFFLINE'
        : (st == 'delayed' ? 'DELAYED${a.isEmpty ? '' : ' · $a'}' : 'LIVE${a.isEmpty ? '' : ' · $a'}');
    if (txt == _text && st == _state) return;
    _text = txt;
    _state = st;
    if (repaint) setState(() {});
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final c = _state == 'live' ? p.profit : (_state == 'delayed' ? p.warning : p.loss);
    return OWLStatusPill(text: _text, color: c);
  }
}
