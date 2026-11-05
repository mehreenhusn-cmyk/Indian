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

  // Part 41 (FILE 50): the FIXED section order of the app, left to right in the bottom bar. This list is the single source of truth:
  // the swipe order below is built from it, so the bar and the swipe can never disagree. Every section opens with its summary / comparison first (see the frontend plan).
  static const List<AppRoute> sections = [
    AppRoute.dashboard,
    AppRoute.positions,
    AppRoute.sniper,
    AppRoute.studyLab,
    AppRoute.more, // Part 13: Settings and tools is now the 5th tab of the bar (the top-bar gear is gone, it was the same page twice)
  ];

  // Round 11: the 5 buttons of the bottom bar, left to right. Market and Brain left the bar (they open from the gear page).
  static const List<AppRoute> bottomBar = sections;

  // Settings has ONE fixed home: the top-bar gear at the far left (Part 14), never a bar button and never next to the power button.
  static const AppRoute settingsRoute = AppRoute.more;

  // The pages behind the gear, in the order the swipe visits them after the 5 sections. Settings and tools is always the LAST one.
  static const List<AppRoute> gearPages = [
    AppRoute.market,
    AppRoute.brain,
    AppRoute.signals,
    AppRoute.dualBot,
    AppRoute.ai,
    AppRoute.diagnostics, // R28c: Diagnostics left the bar; its summary is on the Dashboard, the full page opens from More
  ];

  // Swipe order: the 5 sections first, then the gear pages (built from the two lists above, not typed twice).
  static const List<AppRoute> swipeOrder = [...sections, ...gearPages];

  // Pages that have no button in the bar: they open from the top-bar gear / the Settings and tools page and keep the GEAR lit.
  static const Set<AppRoute> underGear = {AppRoute.market, AppRoute.brain, AppRoute.signals, AppRoute.dualBot, AppRoute.ai, AppRoute.diagnostics};

  /// True for the 5 fixed sections; false for a gear page.
  static bool isSection(AppRoute r) => sections.contains(r);

  /// True only for the Settings and tools page (the gear page that holds the app settings).
  static bool isSettings(AppRoute r) => r == settingsRoute;

  /// Position of a section in the bar (0 = first), or null for a gear page. Never a guess.
  static int? sectionNumber(AppRoute r) {
    final i = sections.indexOf(r);
    return i < 0 ? null : i;
  }

  /// Plain-words problems with the order lists (empty = all fine). Pure check: a route missing from the swipe, a route twice, a gear page that also sits in the bar,
  /// or an underGear set that does not match gearPages. For the Diagnostics text and for a reader of the code; nothing calls it at startup.
  static List<String> orderProblems() {
    final out = <String>[];
    for (final r in AppRoute.values) {
      final n = swipeOrder.where((x) => x == r).length;
      if (n == 0) out.add('${label(r)} is missing from the swipe order.');
      if (n > 1) out.add('${label(r)} is in the swipe order $n times.');
    }
    for (final r in gearPages) {
      if (sections.contains(r)) out.add('${label(r)} is both a section and a gear page.');
      if (!underGear.contains(r)) out.add('${label(r)} is a gear page but not in underGear.');
    }
    for (final r in underGear) {
      if (!gearPages.contains(r)) out.add('${label(r)} is in underGear but not a gear page.');
    }
    if (_screenIndex.length != AppRoute.values.length) out.add('The screen number map does not cover every route.');
    return out;
  }

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
