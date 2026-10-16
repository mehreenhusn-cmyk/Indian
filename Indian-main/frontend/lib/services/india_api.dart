import 'dart:convert';

import 'package:http/http.dart' as http;

/// Thin client for the India paper backend (/api/india/*).
class IndiaApi {
  final String base;
  IndiaApi(this.base);

  static const _timeout = Duration(seconds: 8);

  Uri _u(String path) => Uri.parse('$base/api/india$path');

  Future<dynamic> get(String path) async {
    final res = await http.get(_u(path)).timeout(_timeout);
    if (res.statusCode >= 400) throw Exception(_err(res));
    return jsonDecode(res.body);
  }

  Future<dynamic> post(String path, [Map<String, dynamic>? body, Duration? timeout]) async {
    final res = await http
        .post(_u(path), headers: {'Content-Type': 'application/json'}, body: jsonEncode(body ?? {}))
        .timeout(timeout ?? _timeout);
    if (res.statusCode >= 400) throw Exception(_err(res));
    return jsonDecode(res.body);
  }

  Future<String> getText(String path) async {
    final res = await http.get(_u(path)).timeout(_timeout);
    if (res.statusCode >= 400) throw Exception(_err(res));
    return res.body;
  }

  String _err(http.Response r) {
    try {
      final j = jsonDecode(r.body);
      if (j is Map && j['detail'] != null) return '${j['detail']}';
    } catch (_) {}
    return 'HTTP ${r.statusCode}';
  }
}

// ----------------------------------------------------------- formatting ---

double nd(dynamic v) => (v is num) ? v.toDouble() : (double.tryParse('$v') ?? 0.0);

/// Indian digit grouping: 1,23,456.78
String inr(num v, {bool sign = false, int dp = 2}) {
  final neg = v < 0;
  final parts = v.abs().toStringAsFixed(dp).split('.');
  var w = parts[0];
  if (w.length > 3) {
    final last3 = w.substring(w.length - 3);
    var rest = w.substring(0, w.length - 3);
    final groups = <String>[];
    while (rest.length > 2) {
      groups.insert(0, rest.substring(rest.length - 2));
      rest = rest.substring(0, rest.length - 2);
    }
    if (rest.isNotEmpty) groups.insert(0, rest);
    w = '${groups.join(',')},$last3';
  }
  final frac = dp > 0 ? '.${parts[1]}' : '';
  final s = neg ? '-' : (sign && v > 0 ? '+' : '');
  return '$s₹$w$frac';
}

String num2(num v) => v.toStringAsFixed(2);

const _mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// "2026-10-20..." -> "20 Oct 2026"
String dmy(dynamic iso) {
  final s = '${iso ?? ''}';
  if (s.length < 10) return s;
  final m = int.tryParse(s.substring(5, 7)) ?? 1;
  return '${s.substring(8, 10)} ${_mon[(m - 1).clamp(0, 11)]} ${s.substring(0, 4)}';
}

/// "2026-10-20T14:35:00+05:30" -> "14:35"
String hm(dynamic iso) {
  final s = '${iso ?? ''}';
  return s.length >= 16 ? s.substring(11, 16) : s;
}

/// "20 Oct 14:35"
String dayTime(dynamic iso) {
  final s = '${iso ?? ''}';
  if (s.length < 16) return s;
  final m = int.tryParse(s.substring(5, 7)) ?? 1;
  return '${s.substring(8, 10)} ${_mon[(m - 1).clamp(0, 11)]} ${s.substring(11, 16)}';
}
