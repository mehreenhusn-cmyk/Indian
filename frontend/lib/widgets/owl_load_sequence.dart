import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import 'owl_key_clicker.dart';

/// The loading block of the welcome screen. Black and white, terminal style.
///
/// 1. "LOADING" is typed out letter by letter (key sound per letter).
/// 2. A boxed bar fills from 0 to 100 %. The fill follows four real steps:
///    server answered (20 %), data loaded (30 %), live prices connected (30 %),
///    connection speed measured (20 %). It never jumps and never moves faster
///    than 30 % per second.
/// 3. NEW: if one step is slow, the bar waits about 2.5 seconds and then keeps
///    going slowly to 100 %. The app opens anyway and the slow part keeps
///    connecting in the background. Before, the bar could stop at 70 % and the
///    welcome screen closed before your name was typed.
/// 4. At 100 % the word turns to COMPLETED, then the signature is typed. Only
///    after that [onDone] is called.
///
/// All sounds follow the app's sound setting. Nothing here can block the app.
class OwlLoadSequence extends StatefulWidget {
  final String signature;
  final VoidCallback onDone;
  const OwlLoadSequence({super.key, required this.signature, required this.onDone});

  @override
  State<OwlLoadSequence> createState() => _OwlLoadSequenceState();
}

class _OwlLoadSequenceState extends State<OwlLoadSequence> with SingleTickerProviderStateMixin {
  static const String _word = 'LOADING';
  static const double _maxSpeed = 0.30; // share of the bar per second
  static const double _slowSpeed = 0.12; // speed after a step got stuck
  static const int _stuckMs = 2500; // wait this long on a missing step, then go on
  static const int _tickMs = 33;

  static const Color _white = Color(0xFFFFFFFF);
  static const Color _grey = Color(0xFF8A8A8A);
  static const Color _accent = Color(0xFF19E3C2); // teal accent for OK marks and the finished line

  late final OwlKeyClicker _clicker;
  late final AnimationController _blink;
  Timer? _timer;

  int _phase = 0; // 0 typing LOADING, 1 bar filling, 2 completed pause, 3 typing signature, 4 done
  int _wordChars = 0;
  int _sigChars = 0;
  int _msInPhase = 0;
  int _waitMs = 0;
  bool _forced = false;
  double _shown = 0.0;
  int _lastNotch = 0;

  /// Bit 1 = server answered, 2 = first data loaded, 4 = live prices connected, 8 = speed measured.
  static int _mask(AppProvider p) =>
      (p.status.isNotEmpty ? 1 : 0) | (p.initLoaded ? 2 : 0) | (p.wsConnected ? 4 : 0) | (p.wsLatencyMs != null ? 8 : 0);

  static double _target(int m) =>
      ((m & 1) != 0 ? 0.20 : 0.0) + ((m & 2) != 0 ? 0.30 : 0.0) + ((m & 4) != 0 ? 0.30 : 0.0) + ((m & 8) != 0 ? 0.20 : 0.0);

  @override
  void initState() {
    super.initState();
    _blink = AnimationController(vsync: this, duration: const Duration(milliseconds: 520))..repeat(reverse: true);
    _clicker = OwlKeyClicker(
      soundOn: () {
        try {
          return context.read<AppProvider>().soundEnabled;
        } catch (_) {
          return true;
        }
      },
    );
    _clicker.init();
    Future.delayed(const Duration(milliseconds: 650), () {
      if (mounted) _timer = Timer.periodic(const Duration(milliseconds: _tickMs), _onTick);
    });
  }

  void _go(int phase) {
    _phase = phase;
    _msInPhase = 0;
  }

  void _onTick(Timer t) {
    if (!mounted) {
      t.cancel();
      return;
    }
    _msInPhase += _tickMs;
    switch (_phase) {
      case 0: // typing LOADING
        if (_msInPhase >= 95 * (_wordChars + 1) && _wordChars < _word.length) {
          _wordChars++;
          _clicker.tick();
        }
        if (_wordChars >= _word.length && _msInPhase > 95 * _word.length + 260) _go(1);
        break;
      case 1: // the bar follows what is really happening
        final target = _target(_mask(context.read<AppProvider>()));
        if (target > _shown) {
          _waitMs = 0;
          _shown = math.min(target, _shown + _maxSpeed * _tickMs / 1000.0);
        } else {
          _waitMs += _tickMs;
          if (_waitMs > _stuckMs && _shown < 1.0) {
            _forced = true; // a step is slow: keep going, it will connect in the background
            _shown = math.min(1.0, _shown + _slowSpeed * _tickMs / 1000.0);
          }
        }
        final notch = (_shown * 20).floor();
        if (notch > _lastNotch) {
          _lastNotch = notch;
          _clicker.tick(haptic: false);
        }
        if (_shown >= 0.999) {
          _shown = 1.0;
          _clicker.bell();
          _go(2);
        }
        break;
      case 2: // COMPLETED, short pause
        if (_msInPhase > 600) _go(3);
        break;
      case 3: // signature, typed like heavy key presses
        if (_msInPhase >= 85 * (_sigChars + 1) && _sigChars < widget.signature.length) {
          _sigChars++;
          if (widget.signature[_sigChars - 1] != ' ') _clicker.tick();
        }
        if (_sigChars >= widget.signature.length) {
          _clicker.bell();
          _go(4);
          t.cancel();
          widget.onDone();
        }
        break;
    }
    setState(() {});
  }

  @override
  void dispose() {
    _timer?.cancel();
    _blink.dispose();
    _clicker.dispose();
    super.dispose();
  }

  TextStyle _mono(double size, Color color, {FontWeight w = FontWeight.w600, double spacing = 1.0}) =>
      TextStyle(fontFamily: 'monospace', fontSize: size, fontWeight: w, letterSpacing: spacing, color: color, height: 1.35);

  Widget _line(String name, bool on) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 1.5),
      child: Row(
        children: [
          Text(on ? '[ OK ]' : '[ .. ]', style: _mono(11.5, on ? _accent : _grey, w: FontWeight.w800)),
          const SizedBox(width: 10),
          Text(name, style: _mono(11.5, on ? _white : _grey)),
        ],
      ),
    );
  }

  String _statusText(AppProvider p, int m) {
    if ((m & 15) == 15) return 'All systems ready.';
    if (_phase >= 2) return 'Opening now. Live data keeps connecting in the background.';
    if (_forced) return 'Some checks are slow. Opening anyway...';
    if ((m & 1) == 0) return p.isWakingUp ? 'Waking up the server...' : 'Connecting to the server...';
    if ((m & 2) == 0) return 'Loading your data...';
    if ((m & 4) == 0) return 'Waiting for live prices...';
    return 'Checking connection speed...';
  }

  @override
  Widget build(BuildContext context) {
    final m = context.select<AppProvider, int>((p) => _mask(p));
    final p = context.read<AppProvider>();
    final done = _phase >= 2;
    final word = done ? 'COMPLETED' : _word.substring(0, _wordChars);
    final cursorOn = _blink.value > 0.35;
    final sigShown = widget.signature.substring(0, _sigChars);
    final typingSig = _phase == 3 && _sigChars < widget.signature.length;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          height: 24,
          child: AnimatedBuilder(
            animation: _blink,
            builder: (context, _) => Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(word, style: _mono(15, _white, w: FontWeight.w800, spacing: 5)),
                if (!done && (_phase == 0 || cursorOn))
                  Container(width: 9, height: 16, margin: const EdgeInsets.only(left: 3), color: _white),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        SizedBox(
          height: 34,
          width: double.infinity,
          child: RepaintBoundary(
            child: CustomPaint(painter: _BoxBarPainter(_phase >= 1 ? _shown : 0.0)),
          ),
        ),
        const SizedBox(height: 14),
        _line('server', (m & 1) != 0),
        _line('data', (m & 2) != 0),
        _line('live prices', (m & 4) != 0),
        _line('speed check', (m & 8) != 0),
        const SizedBox(height: 10),
        AnimatedBuilder(
          animation: _blink,
          builder: (context, _) => Text(
            '> ${_statusText(p, m)}${cursorOn ? '_' : ' '}',
            style: _mono(11, (m & 15) == 15 ? _accent : _grey),
          ),
        ),
        const SizedBox(height: 22),
        // Signature line, typed like heavy key presses.
        SizedBox(
          height: 22,
          child: AnimatedBuilder(
            animation: _blink,
            builder: (context, _) => Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(_phase >= 3 ? '\u00A9 $sigShown' : '', style: _mono(13, _white, w: FontWeight.w700, spacing: 1.2)),
                if (_phase >= 3 && (typingSig || cursorOn))
                  Container(width: 2, height: 15, margin: const EdgeInsets.only(left: 2), color: _white),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

/// Plain boxed bar: white outline, grey blocks fill from the left,
/// the percentage sits in the middle. Black and white only.
class _BoxBarPainter extends CustomPainter {
  final double progress;
  const _BoxBarPainter(this.progress);

  static const int _segs = 40;

  @override
  void paint(Canvas canvas, Size size) {
    final box = Rect.fromLTWH(1, 1, size.width - 2, size.height - 2);
    canvas.drawRect(box, Paint()..color = Colors.black);
    canvas.drawRect(
      box,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.6
        ..color = Colors.white,
    );

    const pad = 4.0, gap = 0.6; // tiny gaps so the fill reads as one continuous bar
    final inner = Rect.fromLTWH(pad + 1, pad + 1, size.width - 2 * (pad + 1), size.height - 2 * (pad + 1));
    final segW = (inner.width - gap * (_segs - 1)) / _segs;
    final lit = progress * _segs;
    for (var i = 0; i < _segs; i++) {
      final x = inner.left + i * (segW + gap);
      final r = Rect.fromLTWH(x, inner.top, segW, inner.height);
      double a;
      if (i + 1 <= lit) {
        a = 1.0;
      } else if (i < lit) {
        a = lit - i;
      } else {
        a = 0.0;
      }
      canvas.drawRect(
        r,
        Paint()..color = a > 0 ? const Color(0xFF19E3C2).withOpacity(0.35 + 0.65 * a) : Colors.white.withOpacity(0.07),
      );
    }

    final pct = '${(progress * 100).floor()}%';
    final tp = TextPainter(
      text: TextSpan(
        text: pct,
        style: TextStyle(
          fontFamily: 'monospace',
          fontSize: 15,
          fontWeight: FontWeight.w800,
          letterSpacing: 1.5,
          color: Colors.white,
          shadows: [Shadow(color: Colors.black.withOpacity(0.95), blurRadius: 5)],
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, Offset((size.width - tp.width) / 2, (size.height - tp.height) / 2));
  }

  @override
  bool shouldRepaint(covariant _BoxBarPainter old) => old.progress != progress;
}
