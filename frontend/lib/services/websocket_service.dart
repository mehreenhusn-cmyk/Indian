import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:web_socket_channel/status.dart' as status;

/// Live connection to the backend's /ws endpoint.
///
/// What this guarantees (and why):
///  * The backend sends a FULL_STATE_SNAPSHOT (`type: init`) as the very first
///    message of every connection, then a small `update` every second. The
///    app replaces its whole state from that snapshot, so after any drop the
///    open positions / live PnL are correct immediately - nothing is
///    "remembered" from before the drop.
///  * Reconnects are fast and self-healing: 1s, 1s, 2s, 3s, 5s, 8s (then 8s
///    forever), reset on the first message received. Only ONE socket is
///    ever alive (a generation counter ignores callbacks from old sockets),
///    so a late onDone from a dead socket can never spawn duplicate
///    reconnect loops.
///  * Silent death is detected: the server pushes every second, so if
///    nothing arrives for [_silenceLimit] (or a ping gets no pong for
///    [_pongLimit]) the socket is dropped and re-opened - Android often
///    kills sockets in the background without ever calling onDone.
///  * A handshake that hangs (never connects, never errors) is retried too.
///  * [onReconnected] fires once when data flows again after an outage, with
///    the outage length - AppProvider uses it to ask the backend to
///    catch-up-check open trades and to refresh everything over REST.
class WebSocketService {
  WebSocketChannel? _channel;
  StreamSubscription? _sub;

  Function(Map<String, dynamic>)? onMessage;

  /// Fired whenever the connected state changes. "Connected" means a
  /// message has actually been received, not just that a socket was opened.
  Function(bool)? onConnectionChange;

  /// Round-trip ms for every pong received.
  Function(int)? onLatency;

  /// Fired when messages start flowing again after having been down.
  Function(Duration outage)? onReconnected;

  static const _pingEvery = Duration(seconds: 5);
  static const _watchdogEvery = Duration(seconds: 3);
  // A busy server can go quiet for a few seconds. Dropping the socket then only makes it worse (new
  // handshakes queue behind the stuck work), so be patient: the 6s REST safety-net still covers the gap.
  static const _silenceLimit = Duration(seconds: 20);
  static const _pongLimit = Duration(seconds: 25);
  static const _handshakeLimit = Duration(seconds: 15);
  static const _backoffSeconds = [1, 2, 3, 5, 8, 10];

  bool _isConnected = false;
  bool _wantConnected = false;
  int _generation = 0;
  int _attempt = 0;
  String _wsUrl = 'ws://localhost:8000/ws';

  Timer? _reconnectTimer;
  Timer? _pingTimer;
  Timer? _watchdogTimer;
  DateTime? _pingSentAt;
  DateTime? _lastMessageAt;
  DateTime? _openedAt;
  DateTime? _disconnectedAt;

  bool get isConnected => _isConnected;

  void _setConnected(bool value) {
    if (_isConnected == value) return;
    _isConnected = value;
    if (!value) {
      _disconnectedAt ??= DateTime.now();
      _pingSentAt = null;
    }
    onConnectionChange?.call(value);
  }

  /// Connect (or re-connect) to [url]. Safe to call repeatedly: any existing
  /// socket is torn down first.
  void connect([String? url]) {
    if (url != null && url.isNotEmpty) {
      _wsUrl = url;
    }
    _wantConnected = true;
    _attempt = 0;
    _open();
    _startTimers();
  }

  /// Drop whatever socket exists and open a fresh one right now - used when
  /// the app returns to the foreground.
  void forceReconnect() {
    if (!_wantConnected) return;
    // Switching Termux <-> app fires this every time. A socket that delivered data a moment ago is
    // healthy: keep it (killing it was the "connection closed / opened" burst in the backend log).
    final fresh = _lastMessageAt;
    if (_isConnected && fresh != null && DateTime.now().difference(fresh) < const Duration(seconds: 3)) {
      sendPing();
      return;
    }
    // Coming back from the background: if data stopped a while ago the
    // outage really began then - record that, so onReconnected reports the
    // true gap (and the backend catch-up runs) once the new socket delivers.
    final last = _lastMessageAt;
    if (_isConnected && last != null && DateTime.now().difference(last) > const Duration(seconds: 4)) {
      _disconnectedAt = last;
      _setConnected(false);
    }
    _attempt = 0;
    _open();
    _startTimers();
  }

  void _open() {
    _reconnectTimer?.cancel();
    _teardownSocket();
    final gen = ++_generation;
    _openedAt = DateTime.now();
    try {
      final channel = WebSocketChannel.connect(Uri.parse(_wsUrl));
      _channel = channel;
      _sub = channel.stream.listen(
        (message) => _onData(gen, message),
        onDone: () => _onDrop(gen, 'closed'),
        onError: (Object error) => _onDrop(gen, 'error: $error'),
        cancelOnError: true,
      );
    } catch (e) {
      _onDrop(gen, 'connect failed: $e');
    }
  }

  void _teardownSocket() {
    _sub?.cancel();
    _sub = null;
    final ch = _channel;
    _channel = null;
    if (ch != null) {
      try {
        ch.sink.close(status.goingAway);
      } catch (_) {}
    }
  }

  void _onData(int gen, dynamic message) {
    if (gen != _generation) return; // stale socket
    _lastMessageAt = DateTime.now();
    _attempt = 0;
    dynamic data;
    try {
      data = jsonDecode(message as String);
    } catch (e) {
      print('WebSocket parse error: $e');
      return;
    }
    if (data is! Map<String, dynamic>) return;

    final wasDown = !_isConnected;
    _setConnected(true);
    if (wasDown && _disconnectedAt != null) {
      final outage = DateTime.now().difference(_disconnectedAt!);
      _disconnectedAt = null;
      onReconnected?.call(outage);
    }

    if (data['type'] == 'pong') {
      final sent = _pingSentAt;
      if (sent != null) {
        onLatency?.call(DateTime.now().difference(sent).inMilliseconds);
        _pingSentAt = null;
      }
      return;
    }
    onMessage?.call(data);
  }

  void _onDrop(int gen, String why) {
    if (gen != _generation) return; // an old socket dying - ignore
    print('WebSocket dropped ($why)');
    _teardownSocket();
    _setConnected(false);
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    if (!_wantConnected) return;
    _reconnectTimer?.cancel();
    final i = _attempt < _backoffSeconds.length ? _attempt : _backoffSeconds.length - 1;
    _attempt++;
    _reconnectTimer = Timer(Duration(seconds: _backoffSeconds[i]), () {
      if (_wantConnected) _open();
    });
  }

  void _startTimers() {
    _pingTimer?.cancel();
    _pingTimer = Timer.periodic(_pingEvery, (_) => sendPing());
    _watchdogTimer?.cancel();
    _watchdogTimer = Timer.periodic(_watchdogEvery, (_) => _watchdog());
  }

  void _watchdog() {
    if (!_wantConnected) return;
    final now = DateTime.now();
    if (_isConnected) {
      final last = _lastMessageAt;
      final pingAt = _pingSentAt;
      final silent = last != null && now.difference(last) > _silenceLimit;
      final noPong = pingAt != null && now.difference(pingAt) > _pongLimit;
      if (silent || noPong) {
        _onDrop(_generation, silent ? 'silent for ${_silenceLimit.inSeconds}s' : 'no pong');
      }
    } else if (_reconnectTimer == null || !_reconnectTimer!.isActive) {
      // Not connected and nothing scheduled: either a handshake that never
      // finished, or a lost timer - open again.
      final opened = _openedAt;
      if (opened == null || now.difference(opened) > _handshakeLimit) {
        _open();
      }
    }
  }

  void disconnect() {
    _wantConnected = false;
    _reconnectTimer?.cancel();
    _pingTimer?.cancel();
    _watchdogTimer?.cancel();
    _generation++; // invalidate callbacks from the socket being closed
    _teardownSocket();
    _setConnected(false);
  }

  void sendPing() {
    if (_channel != null && _isConnected) {
      _pingSentAt ??= DateTime.now();
      try {
        _channel!.sink.add(jsonEncode({'type': 'ping'}));
      } catch (_) {}
    }
  }

  /// Ask the server for a fresh FULL_STATE_SNAPSHOT (it answers with a
  /// `type: init` message).
  void requestSnapshot() {
    if (_channel != null && _isConnected) {
      try {
        _channel!.sink.add(jsonEncode({'type': 'resync'}));
      } catch (_) {}
    }
  }
}
