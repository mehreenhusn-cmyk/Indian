import 'dart:async';
import 'package:flutter/material.dart';

/// Part 1 (FILE 04): ONE shared loading spinner for every screen that waits for the backend.
/// It spins for [slowAfter] (12 s). After that it stops pretending: it says "This is taking long" and shows a Retry button.
/// The screen keeps its own Retry logic: pass its load function as [onRetry]. No colors from the app palette, so it works in Light and Dark.
class LoadSpinner extends StatefulWidget {
  final VoidCallback onRetry;
  final Duration slowAfter;
  const LoadSpinner({super.key, required this.onRetry, this.slowAfter = const Duration(seconds: 12)});

  @override
  State<LoadSpinner> createState() => _LoadSpinnerState();
}

class _LoadSpinnerState extends State<LoadSpinner> {
  Timer? _timer;
  bool _slow = false;

  @override
  void initState() {
    super.initState();
    _timer = Timer(widget.slowAfter, () {
      if (mounted) setState(() => _slow = true);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_slow) {
      return const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()));
    }
    return Padding(
      padding: const EdgeInsets.all(32),
      child: Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text('This is taking long.', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 6),
          Text('The backend is slow or not reachable. You can wait or try again.', textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 14),
          OutlinedButton(onPressed: widget.onRetry, child: const Text('Retry')),
        ]),
      ),
    );
  }
}
