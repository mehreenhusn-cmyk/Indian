import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'owl_load_sequence.dart';

/// R25: plain black welcome (no picture, chip, scan lines or copper): one white title, one grey line, the real loading block.
/// Wraps the app's real home screen and shows a short black and white
/// "OWL TERMINAL" boot screen on top of it when more than [gate] has passed
/// since it was last shown (default 12 hours).
///
/// Same constructor and same SharedPreferences key as before, so main.dart
/// does not change:
///   home: OwlWelcomeOverlay(prefs: prefs, child: const MainScreen()),
///
/// The loading bar is real (see OwlLoadSequence). The screen closes by itself
/// a moment after the bar is complete and the signature is typed.
/// [_maxDuration] is only a safety net. It is longer than the longest
/// possible loading, so it can no longer cut the screen before the name shows.
/// You can tap to skip after about 1.4 seconds. Always black, in any app theme.
class OwlWelcomeOverlay extends StatefulWidget {
  final SharedPreferences prefs;
  final Widget child;
  final Duration gate;

  const OwlWelcomeOverlay({
    super.key,
    required this.prefs,
    required this.child,
    this.gate = const Duration(hours: 12),
  });

  /// false when main.dart had to fall back to an in-memory store (the time of the last splash is then lost on every restart).
  static bool storeIsPersistent = true;

  /// Change this text when you ship a new app build: the welcome screen then shows once on the first start of that build
  /// (new install or update), and after that once every 12 hours.
  static const String buildId = '2026-10-25-plate5';

  static const _prefsKey = 'owl_welcome_last_shown_ms';
  static const Duration _maxDuration = Duration(seconds: 40);

  @override
  State<OwlWelcomeOverlay> createState() => _OwlWelcomeOverlayState();
}

class _OwlWelcomeOverlayState extends State<OwlWelcomeOverlay> with TickerProviderStateMixin {
  late final AnimationController _entrance;
  late final Animation<double> _fade;

  bool _showSplash = false;
  bool _canDismiss = false;
  Timer? _autoDismiss;
  Timer? _tapEnable;

  @override
  void initState() {
    super.initState();

    _entrance = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 450),
      reverseDuration: const Duration(milliseconds: 300),
    );
    _fade = CurvedAnimation(parent: _entrance, curve: Curves.easeOutCubic);

    _decide();
  }

  // The time of the last welcome is saved in a small FILE in the app's own folder (the settings plugin is not reliable on this phone).
  // File content: "<milliseconds>|<build id>". No file = fresh install = show. Other build id = new version = show. Older than 12 h = show.
  Future<File?> _stampFile() async {
    try {
      final dir = await getApplicationSupportDirectory();
      return File('${dir.path}/owl_welcome_stamp.txt');
    } catch (_) {
      return null;
    }
  }

  Future<void> _decide() async {
    final now = DateTime.now().millisecondsSinceEpoch;
    var lastShown = 0;
    var build = '';
    final f = await _stampFile();
    try {
      if (f != null && await f.exists()) {
        final parts = (await f.readAsString()).trim().split('|');
        lastShown = int.tryParse(parts.first) ?? 0;
        build = parts.length > 1 ? parts[1] : '';
      }
    } catch (_) {}
    if (lastShown == 0) {
      // file missing or unreadable: fall back to the settings value if that works on this phone
      try {
        lastShown = widget.prefs.getInt(OwlWelcomeOverlay._prefsKey) ?? 0;
      } catch (_) {}
    }
    final fresh = lastShown == 0 || build != OwlWelcomeOverlay.buildId || now - lastShown >= widget.gate.inMilliseconds;
    if (!fresh || !mounted) return;
    try {
      await f?.writeAsString('$now|${OwlWelcomeOverlay.buildId}');
    } catch (_) {}
    try {
      widget.prefs.setInt(OwlWelcomeOverlay._prefsKey, now);
    } catch (_) {}
    if (!mounted) return;
    setState(() => _showSplash = true);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _entrance.forward();
    });
    // Guard against an accidental tap while the screen fades in.
    _tapEnable = Timer(const Duration(milliseconds: 1400), () {
      if (mounted) setState(() => _canDismiss = true);
    });
    _autoDismiss = Timer(OwlWelcomeOverlay._maxDuration, _dismiss);
  }

  void _dismiss() {
    if (!mounted || !_showSplash) return;
    HapticFeedback.lightImpact();
    _autoDismiss?.cancel();
    _tapEnable?.cancel();
    _entrance.reverse().then((_) {
      if (mounted) setState(() => _showSplash = false);
    });
  }

  @override
  void dispose() {
    _autoDismiss?.cancel();
    _tapEnable?.cancel();
    _entrance.dispose();
    super.dispose();
  }

  TextStyle _sans(double size, Color color, {FontWeight w = FontWeight.w400, double spacing = 0.2}) =>
      TextStyle(fontFamily: 'Inter', fontSize: size, fontWeight: w, letterSpacing: spacing, color: color);

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        widget.child,
        if (_showSplash)
          Positioned.fill(
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: _canDismiss ? _dismiss : null,
              child: FadeTransition(
                opacity: _fade,
                child: Material(
                  color: Colors.black, // R25: plain black, no picture, no chip, no scan lines
                  child: Stack(
                    children: [
                      SafeArea(
                        child: Center(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 28),
                            child: _content(context),
                          ),
                        ),
                      ),
                      if (_canDismiss)
                        Positioned(
                          left: 0,
                          right: 0,
                          bottom: 28,
                          child: SafeArea(
                            child: Center(
                              child: Text('Tap to skip', style: _sans(12, const Color(0xFF6B7488))),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }

  Widget _content(BuildContext context) {
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 420),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // R25: plain white title (Inter 28 bold, wide tracking) + one quiet grey line, then a thin divider.
          const Text(
            'OWL TERMINAL',
            textAlign: TextAlign.center,
            style: TextStyle(fontFamily: 'Inter', fontSize: 28, fontWeight: FontWeight.w700, letterSpacing: 5, color: Colors.white),
          ),
          const SizedBox(height: 10),
          Text('Autonomous trading system', textAlign: TextAlign.center, style: _sans(14, const Color(0xFF9AA6BC))),
          const SizedBox(height: 20),
          Container(height: 1, color: const Color(0xFF1E2633)),
          const SizedBox(height: 22),
          OwlLoadSequence(
            // Bar complete and both names typed: close a moment later.
            onDone: () => Future.delayed(const Duration(milliseconds: 900), _dismiss),
          ),
        ],
      ),
    );
  }
}
