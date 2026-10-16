import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/india_api.dart';
import '../theme/app_theme.dart';
import '../widgets/india_ui.dart';
import '../widgets/owl_card.dart';

/// "Exchange connection" card (top of India Settings). Tap an exchange (Tradebulls / Fyers), enter the key,
/// tap Connect - the balance and data of THAT exchange then show here. Passwords / 2FA / the daily Fyers
/// auth code are sent once and are never saved on the server. For Fyers the PIN IS saved (server only) so the
/// backend renews the daily login by itself - the browser login is then needed only about every 15 days.
class IndiaBrokerCard extends StatefulWidget {
  final IndiaApi api;
  final VoidCallback onChanged;
  const IndiaBrokerCard({super.key, required this.api, required this.onChanged});

  @override
  State<IndiaBrokerCard> createState() => _IndiaBrokerCardState();
}

class _IndiaBrokerCardState extends State<IndiaBrokerCard> {
  String _broker = 'fyers';
  final _fApp = TextEditingController();
  final _fSecret = TextEditingController();
  final _fRedirect = TextEditingController();
  final _fCode = TextEditingController();
  final _fPin = TextEditingController();
  Map<String, dynamic> _whatIf = {};
  String _loginUrl = '';
  final _base = TextEditingController();
  final _user = TextEditingController();
  final _key = TextEditingController();
  final _pass = TextEditingController();
  final _tfa = TextEditingController();
  String _loginType = 'PASSWORD';
  bool _busy = false;
  bool _loaded = false;
  String _error = '';
  Map<String, dynamic> _info = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in [_base, _user, _key, _pass, _tfa, _fApp, _fSecret, _fRedirect, _fCode, _fPin]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final j = await widget.api.get('/broker');
      if (!mounted) return;
      setState(() {
        _info = Map<String, dynamic>.from(j as Map);
        _loaded = true;
      });
      _loadWhatIf();
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  /// Same paper trades replayed against the REAL Fyers balance (taken / skipped, profit with balance).
  Future<void> _loadWhatIf() async {
    try {
      final r = Map<String, dynamic>.from(await widget.api.get('/report?period=30d') as Map);
      if (mounted && r['what_if'] is Map) setState(() => _whatIf = Map<String, dynamic>.from(r['what_if'] as Map));
    } catch (_) {}
  }

  Map<String, dynamic> get _saved {
    final s = _info['saved'];
    if (s is Map && s[_broker] is Map) return Map<String, dynamic>.from(s[_broker] as Map);
    return {};
  }

  Future<void> _connect() async {
    FocusScope.of(context).unfocus();
    final creds = _broker == 'fyers'
        ? <String, dynamic>{
            if (_fApp.text.trim().isNotEmpty) 'app_id': _fApp.text.trim(),
            if (_fSecret.text.trim().isNotEmpty) 'secret_id': _fSecret.text.trim(),
            if (_fRedirect.text.trim().isNotEmpty) 'redirect_url': _fRedirect.text.trim(),
            if (_fCode.text.trim().isNotEmpty) 'auth_code': _fCode.text.trim(),
            if (_fPin.text.trim().isNotEmpty) 'pin': _fPin.text.trim(),
          }
        : <String, dynamic>{
      'login_type': _loginType,
      if (_base.text.trim().isNotEmpty) 'base_url': _base.text.trim(),
      if (_user.text.trim().isNotEmpty) 'user_id': _user.text.trim(),
      if (_key.text.trim().isNotEmpty) 'api_key': _key.text.trim(),
      if (_pass.text.isNotEmpty) 'password': _pass.text,
      if (_tfa.text.trim().isNotEmpty) 'second_auth': _tfa.text.trim(),
          };
    setState(() {
      _busy = true;
      _error = '';
    });
    try {
      final j = await widget.api.post('/broker/connect', {'broker': _broker, 'creds': creds}, const Duration(seconds: 40));
      _pass.clear();
      _tfa.clear();
      _fCode.clear();
      _fSecret.clear();
      _fPin.clear();
      if (!mounted) return;
      setState(() => _info = Map<String, dynamic>.from(j as Map));
      widget.onChanged();
      _loadWhatIf();
    } catch (e) {
      if (mounted) setState(() => _error = '$e'.replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _loginLink() async {
    setState(() {
      _busy = true;
      _error = '';
    });
    try {
      final j = await widget.api.post('/broker/login_url', {
        'broker': 'fyers',
        if (_fApp.text.trim().isNotEmpty) 'app_id': _fApp.text.trim(),
        if (_fRedirect.text.trim().isNotEmpty) 'redirect_url': _fRedirect.text.trim(),
      });
      final url = '${(j as Map)['url']}';
      await Clipboard.setData(ClipboardData(text: url));
      if (mounted) setState(() => _loginUrl = url);
    } catch (e) {
      if (mounted) setState(() => _error = '$e'.replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _refreshBalance() async {
    setState(() => _busy = true);
    try {
      final j = await widget.api.post('/broker/balance', {'broker': _broker}, const Duration(seconds: 20));
      if (mounted) setState(() => _info = Map<String, dynamic>.from(j as Map));
      _loadWhatIf();
    } catch (e) {
      if (mounted) setState(() => _error = '$e'.replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _disconnect() async {
    setState(() => _busy = true);
    try {
      final j = await widget.api.post('/broker/disconnect');
      if (!mounted) return;
      setState(() {
        _info = Map<String, dynamic>.from(j as Map);
        _error = '';
      });
      widget.onChanged();
    } catch (e) {
      if (mounted) setState(() => _error = '$e'.replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _field(TextEditingController c, String label, {String hint = '', bool secret = false}) {
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: TextField(
        controller: c,
        obscureText: secret,
        autocorrect: false,
        enableSuggestions: false,
        decoration: InputDecoration(labelText: label, hintText: hint, isDense: true, border: const OutlineInputBorder()),
      ),
    );
  }

  /// Live-feed health: socket state, how many candles are built, premium source.
  List<Widget> _feedLines(AppText t, AppPalette p, Map<String, dynamic> f) {
    final candles = f['candles'] is Map ? Map<String, dynamic>.from(f['candles'] as Map) : <String, dynamic>{};
    final need = nd(f['warmup_need']).toInt();
    final hist = f['history_note'] != null;
    final have = candles.values.isEmpty ? 0 : candles.values.map((e) => nd(e).toInt()).reduce((a, b) => a < b ? a : b);
    final ticks = nd(f['ticks']).toInt();
    final ok = '${f['feed']}' == 'connected' && ticks > 0;
    final err = '${f['feed_error'] ?? ''}';
    return [
      const SizedBox(height: 6),
      Text(ok ? 'Price feed: receiving prices ($ticks ticks)' : 'Price feed: ${f['feed']}${ticks == 0 ? ' - no prices yet (market closed?)' : ''}',
          style: t.secondary.copyWith(color: ok ? p.profit : p.warning)),
      Text('Option premium: ${f['premium_source']} - ${f['contracts'] ?? ''}', style: t.metadata),
      if (hist) Text('${f['history_note']}', style: t.metadata) else Text('Strategy candles: $have / $need ${have >= need ? '(ready)' : '(building from live ticks - keep the backend running)'}', style: t.metadata),
      if (f['ws_feed'] is Map) ...[
        Text('Prices by ${f['ws_feed']['mode'] == 'WEBSOCKET' ? 'WebSocket (no request limit)' : 'REST (limited to 50 calls a minute)'}', style: t.secondary.copyWith(color: f['ws_feed']['mode'] == 'WEBSOCKET' ? p.profit : p.warning)),
        if ('${f['ws_feed']['note'] ?? ''}'.isNotEmpty) Text('${f['ws_feed']['note']}', style: t.metadata),
        if (f['ws_feed']['api'] is Map) Text('Fyers calls: ${nd(f['ws_feed']['api']['calls_per_min']).toInt()} / ${nd(f['ws_feed']['api']['max_per_min']).toInt()} per minute', style: t.metadata),
      ],
      if (err.isNotEmpty) SelectableText(friendlyError(err), style: t.metadata.copyWith(color: p.loss)),
    ];
  }

  /// One line per exchange that has been connected: its own balance, so you see each exchange separately.
  List<Widget> _balances(AppText t, AppPalette p) {
    final acc = _info['accounts'];
    if (acc is! Map || acc.isEmpty) return [];
    final rows = <Widget>[const SizedBox(height: 8)];
    for (final e in acc.entries) {
      final a = Map<String, dynamic>.from(e.value as Map);
      final name = '${e.key}' == 'fyers' ? 'Fyers' : 'Tradebulls';
      final cash = a['net_available'] != null ? inr(nd(a['net_available'])) : '-';
      final err = '${a['balance_error'] ?? ''}';
      rows.add(Text('$name  ${a['name'] ?? ''}   cash $cash', style: t.primary));
      if (a['total'] != null) rows.add(Text('Total ${inr(nd(a['total']))}   Used ${a['used'] == null ? '-' : inr(nd(a['used']))}', style: t.secondary));
      if (err.isNotEmpty) rows.add(Text(friendlyError(err), style: t.metadata.copyWith(color: p.warning)));
    }
    rows.add(TextButton.icon(
      onPressed: _busy || !(_info['connected'] == true || _info['login_ok'] == true) ? null : _refreshBalance,
      icon: const Icon(Icons.refresh, size: 16),
      label: const Text('Refresh balance'),
    ));
    return rows;
  }

  /// Fyers login health: automatic renewal on/off and how long until the browser login is needed again.
  List<Widget> _authLines(AppText t, AppPalette p) {
    final a = _info['auth'] is Map ? Map<String, dynamic>.from(_info['auth'] as Map) : <String, dynamic>{};
    if (a.isEmpty || _broker != 'fyers') return [];
    final auto = a['auto_renew'] == true;
    final left = a['refresh_days_left'] == null ? null : nd(a['refresh_days_left']).toInt();
    final soon = a['needs_login_soon'] == true;
    final note = '${a['note'] ?? ''}';
    final text = !auto
        ? 'Daily login is still manual: save your Fyers PIN once (PIN field) and the app renews the login by itself.'
        : (left != null && left <= 2
            ? 'Auto-login ON - browser login needed again in ${left < 0 ? 0 : left} day(s). Get the login link and paste a new auth code.'
            : 'Auto-login ON - no daily login.${left != null ? ' Browser login needed again in about $left days.' : ''}');
    return [
      const SizedBox(height: 8),
      Text(text, style: t.secondary.copyWith(color: soon ? p.warning : p.profit, fontWeight: FontWeight.w600)),
      if (note.isNotEmpty) Text(note, style: t.metadata),
    ];
  }

  /// "If your real balance had been there": the paper trades replayed against the real cash.
  List<Widget> _whatIfLines(AppText t, AppPalette p) {
    final w = _whatIf;
    if (w.isEmpty || nd(w['trades']).toInt() == 0) return [];
    final known = w['balance_known'] == true;
    final pw = nd(w['pnl_with_balance']);
    return [
      const SizedBox(height: 10),
      Text('WHAT IF YOUR REAL BALANCE WAS USED (last 30 days)', style: t.metadata.copyWith(fontWeight: FontWeight.w700, letterSpacing: 1.0)),
      const SizedBox(height: 4),
      Text('Paper P&L ${inr(nd(w['paper_pnl']))} on paper capital ${inr(nd(w['paper_capital']))}', style: t.secondary),
      Text(known
              ? 'With your Fyers cash ${inr(nd(w['balance']))}: ${nd(w['taken']).toInt()} of ${nd(w['trades']).toInt()} trades fit, P&L ${inr(pw)}'
              : 'Fyers cash not read yet - connect and tap Refresh balance',
          style: t.primary.copyWith(color: known ? (pw >= 0 ? p.profit : p.loss) : p.textSecondary)),
      if (known && nd(w['skipped']).toInt() > 0)
        Text('${nd(w['skipped']).toInt()} trades would have been skipped (missed ${inr(nd(w['pnl_missed']))}). Cash needed to take every signal: ${inr(nd(w['needed_for_all']))}', style: t.metadata),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final t = context.type;
    final p = context.palette;
    final loginOk = _info['login_ok'] == true;
    final live = _info['connected'] == true;
    final acct = _info['account'] is Map ? Map<String, dynamic>.from(_info['account'] as Map) : <String, dynamic>{};
    final saved = _saved;
    final status = live
        ? IPill('LIVE DATA', p.profit)
        : loginOk
            ? IPill('LOGIN OK - DEMO DATA', p.warning)
            : IPill('NOT CONNECTED', p.textSecondary);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.m),
      child: OWLCard(
        padding: const EdgeInsets.all(AppSpacing.m),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('EXCHANGE', style: t.metadata.copyWith(fontWeight: FontWeight.w700, letterSpacing: 1.1))),
            status,
          ]),
          const SizedBox(height: 8),
          Wrap(spacing: 8, children: [
            for (final b in const ['tradebulls', 'fyers'])
              IChip(b == 'fyers' ? 'Fyers' : 'Tradebulls', selected: _broker == b, onTap: () => setState(() {
                _broker = b;
                _error = '';
              })),
          ]),
          ..._balances(t, p),
          if (_broker == 'fyers') ..._whatIfLines(t, p),
          ..._authLines(t, p),
          if (!_loaded && _error.isEmpty) const Padding(padding: EdgeInsets.only(top: 12), child: LinearProgressIndicator()),
          if (loginOk || live) ...[
            const SizedBox(height: 8),
            Text('Logged in as ${acct['name'] ?? ''}', style: t.primary),
          ],
          if (live && _info['feed'] is Map) ..._feedLines(t, p, Map<String, dynamic>.from(_info['feed'] as Map)),
          if (loginOk && !live)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                'Login works but live prices could not be started, so the app keeps using demo data. Paper trades only - no real orders are ever placed.',
                style: t.metadata,
              ),
            ),
          if (_broker == 'tradebulls') ...[
            _field(_base, 'API base URL', hint: saved['base_url'] != null ? 'saved: ${saved['base_url']}' : 'https://...'),
            _field(_user, 'User ID', hint: saved['user_id'] != null ? 'saved: ${saved['user_id']}' : 'e.g. AB1234'),
            _field(_key, 'API key', hint: saved['api_key'] != null ? 'saved: ${saved['api_key']}' : ''),
            const SizedBox(height: 10),
            IChoice<String>(
              values: const ['PASSWORD', 'MPIN'],
              current: _loginType,
              label: (v) => v == 'PASSWORD' ? 'Password' : 'MPIN',
              onPick: (v) => setState(() => _loginType = v),
            ),
            _field(_pass, _loginType == 'MPIN' ? 'MPIN' : 'Password', secret: true),
            _field(_tfa, '2FA password (second_auth)', secret: true),
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('Password and 2FA are used for this login only and are not saved. Leave base URL, user ID and API key empty to reuse the saved ones.', style: t.metadata),
            ),
          ] else ...[
            _field(_fApp, 'App ID', hint: saved['app_id'] != null ? 'saved: ${saved['app_id']}' : 'e.g. ABCD1234-100'),
            _field(_fSecret, 'Secret ID', hint: saved['secret_id'] != null ? 'saved: ${saved['secret_id']}' : '', secret: true),
            _field(_fRedirect, 'Redirect URL', hint: saved['redirect_url'] != null ? 'saved: ${saved['redirect_url']}' : 'https://www.google.com'),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              onPressed: _busy ? null : _loginLink,
              icon: const Icon(Icons.link, size: 16),
              label: const Text('1. Get Fyers login link (copies it)'),
            ),
            if (_loginUrl.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: SelectableText('Link copied - paste it in your browser, log in to Fyers:\n$_loginUrl', style: t.metadata),
              ),
            _field(_fPin, 'Fyers PIN (for automatic daily login)', hint: saved['pin'] != null ? 'saved' : '4 digits', secret: true),
            _field(_fCode, '2. Auth code (or paste the whole address you land on)'),
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('The browser login (steps 1 and 2) is needed only the first time and then about every 15 days. With your PIN saved, the app renews the daily login by itself. App ID, Secret, Redirect URL and PIN are saved on your server only; the auth code is not. Paper trades only - no real orders.', style: t.metadata),
            ),
          ],
          if (_error.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: SelectableText(_error, style: t.metadata.copyWith(color: p.loss)),
            ),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: FilledButton(
                onPressed: _busy ? null : _connect,
                child: _busy
                    ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(loginOk || live ? 'Reconnect' : 'Connect'),
              ),
            ),
            if (loginOk || live) ...[
              const SizedBox(width: 10),
              OutlinedButton(onPressed: _busy ? null : _disconnect, child: const Text('Disconnect')),
            ],
          ]),
        ]),
      ),
    );
  }
}
