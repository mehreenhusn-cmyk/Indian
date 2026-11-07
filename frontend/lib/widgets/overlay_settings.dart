import 'dart:convert';
import 'package:flutter/material.dart';
import 'indicator_sheet.dart';

/// Settings for the chart's EMA 30 / EMA 50 lines and the SD Bands (gear next to each chip, same sheet as ZEMA).
/// DISPLAY ONLY: the lengths stay fixed (EMA 30 / 50, SD 200) because they must match the bot's own numbers.
/// The eye states (on30 / on50 / sdOn) only travel through the sheet; the chart keeps them on its chips.
class OverlaySettings {
  static const prefsKey = 'overlay_settings_v1';

  // c30 / c50 = -1 means "the chart's own colour". Dash: 0 solid, 1 dashed, 2 dotted.
  static const Map<String, dynamic> _d = {
    'on30': true, 'on50': true, 'sdOn': true,
    'c30': -1, 'c50': -1, 'w30': 1, 'w50': 1, 'd30': 0, 'd50': 0, 'emaHid': '',
    'sdMean': true, 'sd1': true, 'sd2': true, 'sd3': true, 'sdClouds': true, 'sdLabels': true,
    'sdW': 1, 'sdHid': '',
  };
  static const _eye = ['on30', 'on50', 'sdOn'];
  static const emaKeys = ['on30', 'on50', 'c30', 'c50', 'w30', 'w50', 'd30', 'd50', 'emaHid'];
  static const sdKeys = ['sdOn', 'sdMean', 'sd1', 'sd2', 'sd3', 'sdClouds', 'sdLabels', 'sdW', 'sdHid'];

  final Map<String, dynamic> _m;
  const OverlaySettings._(this._m);

  factory OverlaySettings.defaults() => OverlaySettings._(Map<String, dynamic>.from(_d));

  factory OverlaySettings.fromJson(String? raw) {
    final m = Map<String, dynamic>.from(_d);
    if (raw != null && raw.isNotEmpty) {
      try {
        final j = jsonDecode(raw);
        if (j is Map) {
          for (final k in _d.keys) {
            if (_eye.contains(k)) continue;
            final v = j[k];
            final d = _d[k];
            if (d is bool && v is bool) m[k] = v;
            if (d is int && v is num) m[k] = v.toInt();
            if (d is String && v is String) m[k] = v;
          }
        }
      } catch (_) {}
    }
    m['w30'] = (m['w30'] as int).clamp(1, 4);
    m['w50'] = (m['w50'] as int).clamp(1, 4);
    m['sdW'] = (m['sdW'] as int).clamp(1, 4);
    return OverlaySettings._(m);
  }

  String toJson() => jsonEncode({for (final e in _m.entries) if (!_eye.contains(e.key)) e.key: e.value});

  OverlaySettings set(String k, dynamic v) => OverlaySettings._({..._m, k: v});

  /// Copy with only the given keys back at their defaults (one gear resets only its own indicator).
  OverlaySettings resetGroup(List<String> keys) => OverlaySettings._({..._m, for (final k in keys) k: _d[k]});

  bool b(String k) => _m[k] == true;
  int i(String k) => (_m[k] as num).toInt();
  Set<String> _hid(String k) => (_m[k] as String).split(',').where((x) => x.isNotEmpty).toSet();

  /// The chosen colour (ARGB) or null = use the chart's default colour.
  Color? colorOf(String k) => i(k) == -1 ? null : Color(i(k));

  bool emaVisible(String tf) => !_hid('emaHid').contains(tf);
  bool sdVisible(String tf) => !_hid('sdHid').contains(tf);
}

/// EMA 30 / EMA 50 gear. [def30] / [def50] = the chart's default colours (shown until the user picks one).
Future<OverlaySettings?> showEmaSettingsSheet(BuildContext context, OverlaySettings cur,
    {required int def30, required int def50}) {
  return showIndicatorSheet<OverlaySettings>(
    context,
    title: 'EMA 30 / EMA 50',
    initial: cur,
    defaults: cur.resetGroup(OverlaySettings.emaKeys),
    tabs: [
      IndicatorTab<OverlaySettings>('Inputs', (s, set) => [
            const ShHeader('Lines'),
            ShCheck('Show EMA 30', s.b('on30'), (v) => set(s.set('on30', v))),
            ShCheck('Show EMA 50', s.b('on50'), (v) => set(s.set('on50', v))),
            const ShHeader('Length is fixed at 30 and 50, same as the bot'),
          ]),
      IndicatorTab<OverlaySettings>('Style', (s, set) => [
            const ShHeader('Lines'),
            ShStyleRow(
              label: 'EMA 30',
              on: s.b('on30'),
              onToggle: (v) => set(s.set('on30', v)),
              argb: s.i('c30') == -1 ? def30 : s.i('c30'),
              onColor: (c) => set(s.set('c30', c)),
              width: s.i('w30'),
              onWidth: (w) => set(s.set('w30', w)),
              dash: s.i('d30'),
              onDash: (d) => set(s.set('d30', d)),
            ),
            ShStyleRow(
              label: 'EMA 50',
              on: s.b('on50'),
              onToggle: (v) => set(s.set('on50', v)),
              argb: s.i('c50') == -1 ? def50 : s.i('c50'),
              onColor: (c) => set(s.set('c50', c)),
              width: s.i('w50'),
              onWidth: (w) => set(s.set('w50', w)),
              dash: s.i('d50'),
              onDash: (d) => set(s.set('d50', d)),
            ),
          ]),
      IndicatorTab<OverlaySettings>('Visibility',
          (s, set) => shVisibilityRows(s._hid('emaHid'), (h) => set(s.set('emaHid', h.join(','))))),
    ],
  );
}

/// SD Bands gear: which levels, clouds, labels, line width, timeframes.
Future<OverlaySettings?> showSdSettingsSheet(BuildContext context, OverlaySettings cur) {
  return showIndicatorSheet<OverlaySettings>(
    context,
    title: 'SD Bands',
    initial: cur,
    defaults: cur.resetGroup(OverlaySettings.sdKeys),
    tabs: [
      IndicatorTab<OverlaySettings>('Inputs', (s, set) => [
            const ShHeader('SD Bands'),
            ShCheck('Show SD Bands', s.b('sdOn'), (v) => set(s.set('sdOn', v))),
            const ShHeader('Levels'),
            ShCheck('SD 0 (mean) line', s.b('sdMean'), (v) => set(s.set('sdMean', v))),
            ShCheck('+1 / -1 SD', s.b('sd1'), (v) => set(s.set('sd1', v))),
            ShCheck('+2 / -2 SD', s.b('sd2'), (v) => set(s.set('sd2', v))),
            ShCheck('+3 / -3 SD', s.b('sd3'), (v) => set(s.set('sd3', v))),
            const ShHeader('Fill and labels'),
            ShCheck('Show clouds between the bands', s.b('sdClouds'), (v) => set(s.set('sdClouds', v))),
            ShCheck('Show level labels (left edge)', s.b('sdLabels'), (v) => set(s.set('sdLabels', v))),
            const ShHeader('Length is fixed at 200, same as the bot'),
          ]),
      IndicatorTab<OverlaySettings>('Style', (s, set) => [
            const ShHeader('Lines'),
            ShNumber('Line width (1-4)', 'sdw', s.i('sdW'), 1, 4, (v) => set(s.set('sdW', v.toInt()))),
          ]),
      IndicatorTab<OverlaySettings>('Visibility',
          (s, set) => shVisibilityRows(s._hid('sdHid'), (h) => set(s.set('sdHid', h.join(','))))),
    ],
  );
}
