import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';

import 'providers/app_provider.dart';
import 'screens/dashboard_screen.dart';
import 'screens/market_screen.dart';
import 'screens/positions_screen.dart';
import 'screens/signals_screen.dart';
import 'screens/vision_tab_screen.dart';
import 'screens/alerts_screen.dart';
import 'screens/india_paper_screen.dart';
import 'screens/settings_screen.dart';
import 'widgets/bottom_nav_bar.dart';
import 'widgets/owl_ambient_background.dart';
import 'widgets/owl_drawer.dart';
import 'widgets/live_ticker_bar.dart';
import 'widgets/exit_confirm.dart';
import 'widgets/owl_connection_banner.dart';
import 'widgets/owl_welcome_overlay.dart';
import 'services/market_mode.dart';
import 'services/websocket_service.dart';
import 'services/foreground_service.dart';
import 'theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Safety net: if any widget fails to build, show the real error text on screen instead of a blank
  // screen, so the cause can be read (and sent) straight from the phone.
  ErrorWidget.builder = (FlutterErrorDetails d) => Material(
        color: const Color(0xFF1A0000),
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(12, 40, 12, 12),
          child: Text(
            'App error (send this text):\n${d.exceptionAsString()}\n\n${d.stack.toString().split('\n').take(8).join('\n')}',
            style: const TextStyle(color: Color(0xFFFF8A80), fontSize: 11),
          ),
        ),
      );

  // Required once, before runApp, for the foreground-service isolate to be
  // able to send data back to this main isolate (see foreground_service.dart).
  try {
    FlutterForegroundTask.initCommunicationPort();
  } catch (_) {}

  final prefs = await _openPrefs();
  if (prefs == null) {
    runApp(const _BootError('SharedPreferences plugin failed twice (see Termux/Android log).'));
    return;
  }

  // If the last start never finished (crash / blank screen), open in Crypto this time instead of
  // reopening the market that may be the one failing. The flag is cleared once the first screen is up.
  const bootKey = 'owl_boot_pending';
  final lastBootFailed = prefs.getBool(bootKey) ?? false;
  MarketMode.load(prefs); // reopen in the market you used last
  if (lastBootFailed) MarketMode.mode.value = 'crypto';
  await prefs.setBool(bootKey, true);
  Timer(const Duration(seconds: 6), () => prefs.setBool(bootKey, false));

  runApp(OwlApp(prefs: prefs));
}

/// Opens the settings store. If the Android plugin is broken in this build (NoSuchMethodError /
/// MissingPluginException at start-up), fall back to an in-memory store so the app still opens:
/// everything works, but settings such as the theme are not remembered after a restart.
Future<SharedPreferences?> _openPrefs() async {
  try {
    return await SharedPreferences.getInstance();
  } catch (e) {
    debugPrint('SharedPreferences plugin failed, using in-memory settings: $e');
  }
  try {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    return await SharedPreferences.getInstance();
  } catch (_) {
    return null;
  }
}

/// Shown only if the very first start-up step throws (nothing else can draw yet).
class _BootError extends StatelessWidget {
  final String text;
  const _BootError(this.text);

  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        home: Scaffold(
          backgroundColor: const Color(0xFF1A0000),
          body: SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(12),
              child: Text('Start-up error (send this text):\n$text', style: const TextStyle(color: Color(0xFFFF8A80), fontSize: 11)),
            ),
          ),
        ),
      );
}

class OwlApp extends StatelessWidget {
  final SharedPreferences prefs;

  const OwlApp({super.key, required this.prefs});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider(
      create: (context) => AppProvider(prefs)..init(),
      child: Selector<AppProvider, ThemeMode>(
        selector: (_, p) => p.themeMode,
        builder: (context, themeMode, child) {
          return MaterialApp(
            title: 'OWL',
            theme: AppTheme.light,
            darkTheme: AppTheme.dark,
            themeMode: themeMode,
            // Instant theme switch: the default 200ms animation lerps the
            // background while text colors flip at once -> ghost/faded text.
            themeAnimationDuration: Duration.zero,
            home: OwlWelcomeOverlay(prefs: prefs, child: const MarketRoot()),
            debugShowCheckedModeBanner: false,
          );
        },
      ),
    );
  }
}

/// Crypto and India Paper are two equal top-level markets. Both stay alive underneath (the crypto socket and the
/// India paper bot keep working while the other market is on screen); Back never switches market.
class MarketRoot extends StatefulWidget {
  const MarketRoot({super.key});

  @override
  State<MarketRoot> createState() => _MarketRootState();
}

class _MarketRootState extends State<MarketRoot> {
  bool _indiaSeen = MarketMode.mode.value == 'india';

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<String>(
      valueListenable: MarketMode.mode,
      builder: (context, m, _) {
        final india = m == 'india';
        if (india) _indiaSeen = true; // built on first visit, then kept alive
        // One Back rule for the whole app (see exit_confirm.dart): other tab -> first tab -> "Exit app?".
        // canPop is false only here at the root; pushed pages (charts, sheets) still close normally.
        return PopScope(
          canPop: false,
          onPopInvokedWithResult: (didPop, _) {
            if (didPop) return;
            BackGuard.handleBack(context, m);
          },
          child: IndexedStack(
            index: india ? 1 : 0,
            children: [
              const MainScreen(),
              _indiaSeen ? const IndiaPaperScreen() : const SizedBox.shrink(),
            ],
          ),
        );
      },
    );
  }
}

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> with WidgetsBindingObserver {
  int _currentIndex = 0;
  late WebSocketService _wsService;

  // Safety-net REST poll - the WebSocket pushes updates ~every 1s when it's
  // actually alive, but Android can silently kill/pause a socket in the
  // background (screen off, app backgrounded, OS doze) with no onDone/
  // onError firing, so the reconnect logic never kicks in either. Without
  // this, a position could sit stale in the UI indefinitely until the app
  // was force-closed and reopened (which re-runs init() from scratch) -
  // this timer means the UI self-heals within ~15s even if the socket is
  // silently dead, no restart needed.
  Timer? _pollTimer;

  // Keep-alive ping - separate from the poll above, just hits /health
  // periodically so a free-tier backend (Render cold-start, see
  // app_provider.dart) sees regular traffic while the app is open and is
  // less likely to spin down between real requests.
  Timer? _keepAliveTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    BackGuard.cryptoGoHome = _backToFirstTab;
    _wsService = WebSocketService();
    _wsService.onMessage = (data) {
      context.read<AppProvider>().updateFromWebSocket(data);
    };
    _wsService.onConnectionChange = (connected) {
      if (mounted) context.read<AppProvider>().setWsConnected(connected);
    };
    _wsService.onLatency = (ms) {
      if (mounted) context.read<AppProvider>().setWsLatency(ms);
    };
    // Connection came back after an outage: backend catch-up check of open
    // trades + REST refresh (the FULL_STATE_SNAPSHOT itself already arrived
    // over the socket as its first message).
    _wsService.onReconnected = (outage) {
      if (mounted) context.read<AppProvider>().onWsReconnected(outage);
    };
    // Connect using the same Backend URL the REST calls use (set in
    // Settings, persisted via SharedPreferences) instead of a hardcoded
    // localhost — this is what lets the app work against a PC/VPS backend,
    // not just a phone-local Termux one.
    final provider = context.read<AppProvider>();
    // Saving a new Backend URL in Settings reconnects the socket right away.
    provider.onBackendUrlChanged = () => _wsService.connect(provider.wsUrl);
    _wsService.connect(provider.wsUrl);
    _startBackgroundTimers();
    _startForegroundService();
  }

  // UPGRADE: Foreground Service - keeps the app process (and this socket)
  // alive when Android backgrounds/freezes the app, instead of the OS
  // silently killing it. See services/foreground_service.dart for why this
  // is the fix for "WS na maare" rather than anything on WebSocketService
  // itself. Fire-and-forget: a denied notification permission or a
  // platform that doesn't support it just means no keep-alive boost, not a
  // crash - the app works exactly as before either way.
  Future<void> _startForegroundService() async {
    try {
      OwlForegroundService.init();
      await OwlForegroundService.requestPermissions();
      await OwlForegroundService.start();
    } catch (_) {
      // Never let a foreground-service failure take down app startup.
    }
  }

  void _startBackgroundTimers() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(seconds: 15), (_) {
      // WebSocket is the primary feed (~250ms pushes). REST is only the
      // safety net now: fire it just when the socket is down or silent.
      final provider = context.read<AppProvider>();
      if (provider.wsStale) provider.fetchStatus();
    });
    _keepAliveTimer?.cancel();
    _keepAliveTimer = Timer.periodic(const Duration(minutes: 4), (_) {
      context.read<AppProvider>().ping();
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Sound alerts can be limited to "only while the app is open".
    context.read<AppProvider>().setAppForeground(state == AppLifecycleState.resumed);
    // Phone was locked/app backgrounded then brought back - the socket may
    // have died silently while away (see _pollTimer comment above), so
    // reconnect it and grab a fresh status immediately instead of waiting
    // for the next 15s poll tick.
    if (state == AppLifecycleState.resumed) {
      final provider = context.read<AppProvider>();
      _wsService.forceReconnect();
      provider.fetchStatus();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    if (BackGuard.cryptoGoHome == _backToFirstTab) BackGuard.cryptoGoHome = null;
    _pollTimer?.cancel();
    _keepAliveTimer?.cancel();
    _wsService.disconnect();
    super.dispose();
  }

  // ---- Tab memory -------------------------------------------------------
  // Each tab keeps the place where you left it, and tapping the tab you are
  // already on scrolls it back to the top. Screens are NOT kept alive in the
  // background (that would slow the app); we only remember the scroll
  // positions of the long lists and put them back when you return.
  final List<GlobalKey> _tabKeys = List.generate(7, (_) => GlobalKey());
  final Map<int, List<double>> _scrollMemo = {};

  /// The big vertical lists of one tab, in tree order.
  List<ScrollableState> _tabScrollables(int index) {
    final out = <ScrollableState>[];
    final ctx = _tabKeys[index].currentContext;
    if (ctx == null) return out;
    void visit(Element e) {
      if (e is StatefulElement && e.state is ScrollableState) {
        final s = e.state as ScrollableState;
        final dir = s.widget.axisDirection;
        if (dir == AxisDirection.down || dir == AxisDirection.up) {
          try {
            final h = e.size?.height ?? 0;
            if (h > 160) out.add(s);
          } catch (_) {}
        }
      }
      e.visitChildren(visit);
    }

    (ctx as Element).visitChildren(visit);
    return out;
  }

  /// Back button: from any tab except the first, go to the first tab (Dash). Returns false when already there.
  bool _backToFirstTab() {
    if (!mounted || _currentIndex == 0) return false;
    AppHaptics.light();
    _saveScroll(_currentIndex);
    setState(() => _currentIndex = 0);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && _currentIndex == 0) _restoreScroll(0, <int, double>{});
    });
    return true;
  }

  void _saveScroll(int index) {
    final list = <double>[];
    for (final s in _tabScrollables(index)) {
      try {
        list.add(s.position.pixels);
      } catch (_) {
        list.add(0);
      }
    }
    _scrollMemo[index] = list;
  }

  /// Puts the saved positions back. Lists may still be loading, so it tries a
  /// few times. It never fights you: if you already moved a list, it stops.
  void _restoreScroll(int index, Map<int, double> placed, [int attempt = 0]) {
    final saved = _scrollMemo[index];
    if (saved == null || saved.every((v) => v < 1)) return;
    final lists = _tabScrollables(index);
    var pending = false;
    for (var i = 0; i < lists.length && i < saved.length; i++) {
      final want = saved[i];
      if (want < 1) continue;
      try {
        final pos = lists[i].position;
        if (!pos.hasPixels) {
          pending = true;
          continue;
        }
        final last = placed[i];
        final movedByUser = pos.pixels > 1 && (pos.pixels - want).abs() > 1 && (last == null || (pos.pixels - last).abs() > 2);
        if (movedByUser) continue;
        final target = want.clamp(pos.minScrollExtent, pos.maxScrollExtent).toDouble();
        if ((pos.pixels - target).abs() > 1) pos.jumpTo(target);
        placed[i] = target;
        if (want > pos.maxScrollExtent + 1) pending = true; // list is still growing
      } catch (_) {
        pending = true;
      }
    }
    if (pending && attempt < 6) {
      Future.delayed(Duration(milliseconds: 120 + 120 * attempt), () {
        if (mounted && _currentIndex == index) _restoreScroll(index, placed, attempt + 1);
      });
    }
  }

  void _scrollTabToTop(int index) {
    for (final s in _tabScrollables(index)) {
      try {
        final pos = s.position;
        if (pos.hasPixels && pos.pixels > 1) {
          pos.animateTo(pos.minScrollExtent, duration: const Duration(milliseconds: 320), curve: Curves.easeOutCubic);
        }
      } catch (_) {}
    }
    _scrollMemo[index] = <double>[];
  }

  final List<Widget> _screens = [
    const DashboardScreen(),
    const MarketScreen(),
    const PositionsScreen(),
    const SignalsScreen(),
    const VisionTabScreen(),
    const AlertsScreen(),
    const SettingsScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    final wsConnected = context.select<AppProvider, bool>((p) => p.wsConnected);
    final wsLongDown = context.select<AppProvider, bool>((p) => p.wsLongDown);
    final syncNotice = context.select<AppProvider, String?>((p) => p.syncNotice);
    final syncNoticeIsGood = context.select<AppProvider, bool>((p) => p.syncNoticeIsGood);
    // Dashboard's "Open Positions" card asks (via AppProvider.goToTab) to
    // jump straight to the Positions tab (index 1) - this is the only
    // channel that can reach _currentIndex from a Dashboard sub-widget, see
    // AppProvider.goToTab's doc comment. Consumed once via
    // consumeTabRequest() so it never re-fires on an unrelated rebuild.
    final tabRequest = context.select<AppProvider, int>((p) => p.navigateToTabRequest);
    if (tabRequest >= 0) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        final requested = context.read<AppProvider>().consumeTabRequest();
        if (requested != null && requested != _currentIndex) {
          _saveScroll(_currentIndex);
          setState(() => _currentIndex = requested);
        }
      });
    }
    return Scaffold(
      backgroundColor: context.palette.bg,
      // Left-side swipe drawer (Exchange Selector + Quick AI Assistant
      // access) - lives here on the OUTER Scaffold so it's reachable by an
      // edge swipe from every tab, even though each tab screen also has its
      // own inner Scaffold/AppBar (that inner one has no `drawer` of its
      // own, so it never competes for the swipe gesture).
      drawer: const OwlDrawer(),
      // PART 1 HARDENING FIX: the top status-bar inset is now applied ONCE,
      // here, around the whole body Column - not per-child. Previously
      // LiveTickerBar (the "5m | PAPER" pills row) had no SafeArea of its
      // own, so whenever neither banner below was showing (the normal,
      // common case - no dropped connection, no sync notice) it was the
      // very first thing in the Column and sat flush at y=0, overlapped by
      // the Android status bar's clock/battery icons. Wrapping the two
      // banners in their OWN SafeArea each (as before) while also wrapping
      // LiveTickerBar in its own would have double-padded the top inset on
      // the (rarer) frames where a banner is visible - a single outer
      // SafeArea(bottom: false) avoids that entirely: exactly one top
      // inset, applied to whichever child happens to be first.
      body: Stack(
        children: [
          const Positioned.fill(child: OwlAmbientBackground()),
          SafeArea(
        bottom: false,
        child: Column(
          children: [
            // Top-level connection banner - only shown when the live
            // WebSocket is down, so screens relying on it (positions/prices)
            // don't silently look "stuck" without explanation. The 15s
            // safety-net poll (see _pollTimer above) still keeps data fresh
            // even while this shows, just not sub-second.
            // Shared banner widget (owl_connection_banner.dart): collapses to
            // zero height while live, so behaviour is unchanged - it still
            // only appears when the WebSocket is down.
            OWLConnectionBanner(
              status: (wsConnected || !wsLongDown)
                  ? ConnectionStatus.live
                  : ConnectionStatus.connecting,
            ),
            if (wsConnected && syncNotice != null)
              Container(
                width: double.infinity,
                color: (syncNoticeIsGood
                        ? context.palette.positive
                        : context.palette.warning)
                    .withOpacity(0.12),
                padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 12),
                child: Text(
                  syncNotice,
                  textAlign: TextAlign.center,
                  style: AppTypography.metadata.copyWith(
                    color: syncNoticeIsGood
                        ? context.palette.positive
                        : context.palette.warning,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            // PHASE 4 - STICKY LIVE TICKER BAR: persistent across every tab.
            // None of the six screens use a real Flutter `AppBar` widget -
            // each just draws its own header Text inside its own body - so
            // there's no single AppBar to dock strictly "under" for all of
            // them without editing every screen. Placed here, right after
            // the (conditional) connection/sync banners and before the tab
            // content, it sits directly above each screen's own header and
            // stays visible across every tab switch. The outer SafeArea
            // above already guarantees this never collides with the status
            // bar, whether or not a banner is showing above it.
            const LiveTickerBar(),
            // RepaintBoundary keeps 1 Hz price updates on a tab from
            // repainting the ticker bar / banners / nav bar around it.
            Expanded(
              child: RepaintBoundary(
                child: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 120),
                  switchInCurve: AppMotion.standard,
                  switchOutCurve: AppMotion.standard,
                  // Fade + tiny scale (0.98 -> 1): the "fade through" feel,
                  // done natively so it costs one opacity + one transform
                  // layer per tab switch - no package, no blur.
                  // SPEED: fade only (the scale layer made the phone re-raster the whole
                  // screen on every frame while two tabs were alive at once).
                  transitionBuilder: (child, animation) => FadeTransition(
                    opacity: animation,
                    child: child,
                  ),
                  layoutBuilder: (current, previous) => Stack(
                    fit: StackFit.expand,
                    children: [...previous, if (current != null) current],
                  ),
                  // Inner tab Scaffolds go transparent so the ambient glow
                  // shows through; pushed routes keep the normal opaque theme.
                  child: Theme(
                    key: ValueKey<int>(_currentIndex),
                    data: Theme.of(context).copyWith(
                      scaffoldBackgroundColor: Colors.transparent,
                    ),
                    child: KeyedSubtree(key: _tabKeys[_currentIndex], child: _screens[_currentIndex]),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
        ],
      ),
      bottomNavigationBar: BottomNavBar(
        currentIndex: _currentIndex,
        onTap: (index) {
          AppHaptics.light();
          if (index == _currentIndex) {
            _scrollTabToTop(index); // tap the open tab again: back to the top
            return;
          }
          _saveScroll(_currentIndex);
          setState(() {
            _currentIndex = index;
          });
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted && _currentIndex == index) _restoreScroll(index, <int, double>{});
          });
        },
      ),
    );
  }
}
