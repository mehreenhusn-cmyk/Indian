import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Which market the app is showing: 'crypto' or 'india'. Both are top-level (equal weight) - switching is done
/// from the drawer, it is remembered between app starts, and the Back button never flips the market.
class MarketMode {
  static const _key = 'owl_market_mode';
  static final ValueNotifier<String> mode = ValueNotifier<String>('crypto');

  static void load(SharedPreferences prefs) {
    final v = prefs.getString(_key);
    mode.value = v == 'india' ? 'india' : 'crypto';
  }

  static Future<void> set(String m) async {
    final v = m == 'india' ? 'india' : 'crypto';
    if (mode.value == v) return;
    mode.value = v;
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.setString(_key, v);
    } catch (_) {}
  }
}
