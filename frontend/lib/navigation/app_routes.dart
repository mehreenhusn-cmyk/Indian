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
  more, // screen 6 (now the Settings and tools page, opened by the top-bar gear)
  brain, // screen 7
  sniper, // screen 8 (Round 11: bar tab 3)
  studyLab, // screen 9 (Round 11: bar tab 4)
  diagnostics, // screen 10 (Round 11: bar tab 5)
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
    AppRoute.sniper: 8,
    AppRoute.studyLab: 9,
    AppRoute.diagnostics: 10,
  };

  /// How many screens main.dart keeps (screen numbers 0 .. screenCount - 1, no gaps).
  static int get screenCount => _screenIndex.length;

  // Round 11: the 5 buttons of the bottom bar, left to right. Market and Brain left the bar (they open from the gear page).
  static const List<AppRoute> bottomBar = [
    AppRoute.dashboard,
    AppRoute.positions,
    AppRoute.sniper,
    AppRoute.studyLab,
    AppRoute.diagnostics,
  ];

  // Swipe order: the 5 bar pages first, then the pages that live behind the gear, then the gear page itself.
  static const List<AppRoute> swipeOrder = [
    AppRoute.dashboard,
    AppRoute.positions,
    AppRoute.sniper,
    AppRoute.studyLab,
    AppRoute.diagnostics,
    AppRoute.market,
    AppRoute.brain,
    AppRoute.signals,
    AppRoute.dualBot,
    AppRoute.ai,
    AppRoute.more,
  ];

  // Pages that have no button in the bar: they open from the top-bar gear / the Settings and tools page and keep the GEAR lit.
  static const Set<AppRoute> underGear = {AppRoute.market, AppRoute.brain, AppRoute.signals, AppRoute.dualBot, AppRoute.ai, AppRoute.more};

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

  /// Which bar button is lit for a page: a bar page lights itself, a gear page lights NO bar button (null; the gear lights instead).
  static AppRoute? litBarRoute(AppRoute r) => bottomBar.contains(r) ? r : null;

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
        return 'Settings and tools';
      case AppRoute.brain:
        return 'Brain';
      case AppRoute.sniper:
        return 'Owl Sniper';
      case AppRoute.studyLab:
        return 'Study Lab';
      case AppRoute.diagnostics:
        return 'Diagnostics';
    }
  }
}
