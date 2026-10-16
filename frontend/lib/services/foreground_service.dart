import 'dart:async';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';

/// UPGRADE: Foreground Service - "taaki Android background mein WS na maare".
///
/// The actual bot (candle polling, signal generation, order placement) runs
/// server-side (backend/recovered_bot) - it keeps running regardless of the
/// phone. What THIS fixes is the Flutter app itself: Android can freeze or
/// kill a backgrounded app's process at any time (Doze, App Standby, low
/// memory), and when it does, WebSocketService's socket + timers die with
/// it - the UI then shows stale P&L/positions until the app is reopened.
///
/// A foreground service (a persistent low-priority notification + elevated
/// process priority) is Android's own sanctioned way to tell the OS "this
/// app is doing something the user cares about, don't freeze/kill it" - it
/// does not run the WebSocket itself, it keeps the whole app PROCESS
/// (including the main isolate that owns the WebSocket) alive for longer in
/// the background. This is the standard/only reliable way to do this
/// without a full native rewrite (WorkManager, JobScheduler, etc.).
///
/// Wired in from main.dart: init() once at startup, start() once
/// permissions are granted, stop() only if the user explicitly wants to
/// disable it (not currently exposed as a Settings toggle - always-on).
class OwlForegroundService {
  static bool _initialized = false;

  /// Must be called once, early, before start(). Safe to call more than
  /// once (guarded).
  static void init() {
    if (_initialized) return;
    _initialized = true;
    FlutterForegroundTask.init(
      androidNotificationOptions: AndroidNotificationOptions(
        channelId: 'owl_terminal_live',
        channelName: 'Owl Terminal Live Monitoring',
        channelDescription:
            'Keeps live prices, positions and alerts syncing while Owl Terminal runs in the background.',
        channelImportance: NotificationChannelImportance.LOW,
        priority: NotificationPriority.LOW,
        // Foreground-service notifications can't be swiped away by design
        // (that's what keeps the process alive) - LOW importance/priority
        // at least keeps it silent instead of alerting like a real push.
        onlyAlertOnce: true,
      ),
      iosNotificationOptions: const IOSNotificationOptions(
        showNotification: false,
        playSound: false,
      ),
      foregroundTaskOptions: ForegroundTaskOptions(
        eventAction: ForegroundTaskEventAction.repeat(15000),
        autoRunOnBoot: false,
        allowWakeLock: true,
        allowWifiLock: true,
      ),
    );
  }

  /// Requests the runtime permissions the service needs (Android 13+
  /// notification permission). Safe to call every time before start() -
  /// a no-op if already granted. Battery-optimization exemption is
  /// intentionally NOT force-requested here (that's an aggressive,
  /// separate ask) - if background kills persist even with the service
  /// running, that's the next thing to add, not this round.
  static Future<void> requestPermissions() async {
    final NotificationPermission notifPerm =
        await FlutterForegroundTask.checkNotificationPermission();
    if (notifPerm != NotificationPermission.granted) {
      await FlutterForegroundTask.requestNotificationPermission();
    }
  }

  /// Starts (or restarts) the foreground service with its persistent
  /// notification. Safe to call if already running (restarts cleanly).
  static Future<void> start() async {
    if (await FlutterForegroundTask.isRunningService) {
      return;
    }
    await FlutterForegroundTask.startService(
      serviceId: 256,
      notificationTitle: 'Owl Terminal',
      notificationText: 'Live monitoring active - prices & positions syncing',
      notificationIcon: null,
      callback: _startCallback,
    );
  }

  static Future<void> stop() async {
    await FlutterForegroundTask.stopService();
  }
}

/// Must be a top-level (or static) function - this is the entry point the
/// OS-managed background isolate calls into. Do not rename/move without
/// also checking any saved reference to it.
@pragma('vm:entry-point')
void _startCallback() {
  FlutterForegroundTask.setTaskHandler(_OwlKeepAliveTaskHandler());
}

/// Deliberately minimal - this handler's own onRepeatEvent doing real work
/// is NOT what keeps the app alive (see class doc on OwlForegroundService
/// above); the foreground-service registration itself is. This just proves
/// the service is alive (for the notification text / future diagnostics)
/// without duplicating WebSocketService's reconnect/ping logic, which stays
/// exactly where it already is, in the main isolate.
class _OwlKeepAliveTaskHandler extends TaskHandler {
  @override
  Future<void> onStart(DateTime timestamp, TaskStarter starter) async {}

  @override
  void onRepeatEvent(DateTime timestamp) {
    FlutterForegroundTask.sendDataToMain({
      'type': 'owl_fgs_heartbeat',
      'ts': timestamp.millisecondsSinceEpoch,
    });
  }

  @override
  Future<void> onDestroy(DateTime timestamp, bool isTimeout) async {}
}
