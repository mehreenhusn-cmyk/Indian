// Central route map (Part 27). ONE place that says which screen number is which page.
// Before: numbers like goToTab(3) were written in many files; if a tab moved, they silently opened the wrong page.
// Now: every caller says a NAME (AppRoute.signals) and only this file knows the number.
// Pure Dart: no import, no provider, no network. The numbers are the SAME as main.dart's _screens list.
enum AppRoute {
  dashboard, // screen 0
  market, // screen 1
  positions, // screen 2
  signals, // screen 3 (opened from More)
  dualBot, // screen 4 (opened from More)
  ai, // screen 5 (opened from More)
  more, // screen 6
  brain, // screen 7
}

class AppRoutes {
  AppRoutes._();

  // Screen number of each route = its position in main.dart's _screens list. Do not reorder without main.dart.
  static const Map<AppRoute, int> _screenIndex = {
    AppRoute.dashboard: 0,
    AppRoute.market: 1,
    AppRoute.positions: 2,
    AppRoute.signals: 3,
    AppRoute.dualBot: 4,
    AppRoute.ai: 5,
    AppRoute.more: 6,
    AppRoute.brain: 7,
  };

  // The 5 buttons of the bottom bar, left to right.
  static const List<AppRoute> bottomBar = [
    AppRoute.dashboard,
    AppRoute.market,
    AppRoute.positions,
    AppRoute.brain,
    AppRoute.more,
  ];

  // Swipe order: the bar first, then the pages that live under More, then More.
  static const List<AppRoute> swipeOrder = [
    AppRoute.dashboard,
    AppRoute.market,
    AppRoute.positions,
    AppRoute.brain,
    AppRoute.signals,
    AppRoute.dualBot,
    AppRoute.ai,
    AppRoute.more,
  ];

  // Pages that have no button of their own: they sit under More and keep More lit.
  static const Set<AppRoute> underMore = {AppRoute.signals, AppRoute.dualBot, AppRoute.ai};

  static int screenIndex(AppRoute r) => _screenIndex[r]!;

  // Number -> name. A number that no page has gives null (never a guess).
  static AppRoute? fromScreenIndex(int i) {
    for (final e in _screenIndex.entries) {
      if (e.value == i) return e.key;
    }
    return null;
  }

  /// Screen numbers of the bottom bar buttons (for BottomNavBar).
  static List<int> get barScreens => [for (final r in bottomBar) screenIndex(r)];

  /// Screen numbers in swipe order (for MainScreen).
  static List<int> get swipeScreens => [for (final r in swipeOrder) screenIndex(r)];

  /// Which bar button is lit for a page: a page under More lights More, a bar page lights itself.
  static AppRoute litBarRoute(AppRoute r) => underMore.contains(r) ? AppRoute.more : r;

  /// Plain name for logs and the Diagnostics text.
  static String label(AppRoute r) {
    switch (r) {
      case AppRoute.dashboard:
        return 'Dashboard';
      case AppRoute.market:
        return 'Market';
      case AppRoute.positions:
        return 'Positions';
      case AppRoute.signals:
        return 'Signals';
      case AppRoute.dualBot:
        return 'Dual Bot';
      case AppRoute.ai:
        return 'AI';
      case AppRoute.more:
        return 'More';
      case AppRoute.brain:
        return 'Brain';
    }
  }
}
