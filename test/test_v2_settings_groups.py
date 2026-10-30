"""Part 63 test (static, NOT RUN by owner rule; Dart is not compiled here): the Settings screen is regrouped into 13 groups and NO field, switch or button was lost.
Run:  python3 test/test_v2_settings_groups.py"""
import os
import re
import unittest

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "lib", "screens", "settings_screen.dart")
GROUPS = ["Timeframe", "Size and leverage", "Take profit", "Stop and trail", "Daily limits", "Trade Rules", "Binance keys", "Live trading",
          "AI assistant", "Telegram", "Sound Alerts", "Appearance", "Backend Connection"]
FIELDS = ["invest_amount", "leverage", "scalp_close_roi_pct", "daily_target_usdt", "daily_loss_limit_usdt", "max_open_trades", "binance_api_key",
          "binance_api_secret", "position_size_value", "live_leverage", "telegram_bot_token", "telegram_chat_id"]
HOOKS = ["_timeframeSelector(p, t)", "_tpModeSelector(p, t)", "_trailSelector(p, t)", "_onLiveTradingToggled(v)", "_testBinanceConnection", "const AiKeysCard()",
         "_saveBackendUrl", "_BackupTile()", "const ReportDownloadCard()", "_save(silent: true)", "_voiceCard(context)", "_appearanceCard(context)",
         "_dailyGate = v", "_blockSellGainer = v", "_blockBuyLoser = v", "_aiEnabled = v", "_positionSizeMode = v"]


def src():
    with open(SRC, encoding="utf-8") as f:
        return f.read()


class Groups(unittest.TestCase):
    def test_thirteen_groups_with_unique_titles(self):
        s = src()
        titles = re.findall(r"SettingsGroup\(\n\s+icon:[^\n]+\n\s+title: '([^']+)'", s)     # inline groups + the 2 card helpers
        self.assertEqual(sorted(titles), sorted(GROUPS))
        self.assertEqual(len(set(titles)), 13)          # the title is the identity for "one group open at a time"
        self.assertNotIn("title: 'Trade Risk'", s)

    def test_no_field_lost_or_doubled(self):
        s = src()
        for k in FIELDS:
            calls = re.findall(r"_field\((?:(?!_field\().){0,220}?'%s'" % k, s, re.S)
            self.assertEqual(len(calls), 1, k)

    def test_every_control_still_there(self):
        s = src()
        for h in HOOKS:
            self.assertIn(h, s, h)
        self.assertEqual(s.count("_radio(p, t,"), 2)    # the two Position Size radios

    def test_order(self):
        s = src()
        at = lambda x: s.index(x)
        order = ["SettingsHeading('Trading')", "title: 'Timeframe'", "title: 'Size and leverage'", "title: 'Take profit'", "title: 'Stop and trail'",
                 "title: 'Daily limits'", "title: 'Trade Rules'", "SettingsHeading('Account')", "title: 'Binance keys'", "title: 'Live trading'",
                 "SettingsHeading('Alerts & AI')", "title: 'AI assistant'", "title: 'Telegram'", "_voiceCard(context),", "SettingsHeading('App')",
                 "_appearanceCard(context),", "title: 'Backend Connection'", "_BackupTile(),"]
        self.assertEqual([at(x) for x in order], sorted(at(x) for x in order))

    def test_live_switch_not_in_keys_group(self):
        s = src()
        a, b, c = s.index("title: 'Binance keys'"), s.index("title: 'Live trading'"), s.index("title: 'AI assistant'")
        self.assertNotIn("_onLiveTradingToggled(v)", s[a:b])
        self.assertIn("_onLiveTradingToggled(v)", s[b:c])
        self.assertIn("binance_api_secret", s[a:b])


if __name__ == "__main__":
    unittest.main()
