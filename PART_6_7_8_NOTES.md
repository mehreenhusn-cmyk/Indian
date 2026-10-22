# Parts 6 + 7 + 8 in ONE zip (build 2026-10-22-part8). Only changed files. Put them over your Part 5 repo.
Part 6: AI Own checks spread over the hour (+ "next slot opens at"), Lab card shows the AI's own reason first, websocket compression off,
        1-second JSON build timed (load report shows dumps_ms).
Part 7: India prices PUSHED over /api/india/ws_ticks (india_api.py + india_ticks.dart), REST only as fallback.
        Splash: skipped when settings storage fell back to memory (no more repeat), once per 12 h otherwise; thin bar gaps, teal fill,
        "Trading System" with capital T, teal OK marks.
Part 8: Settings > Download report (Download / Share / Copy) = whole-app report: what the app is, dashboard, signals, alerts, AI Vision / AI Own /
        capital / Lab, backend health + errors, settings without keys, known problems (ai_report.py, api_server.py, report_download_card.dart,
        settings_screen.dart). Fyers: Telegram reminder once a day when the browser login is due in 2 days or less (india_telegram.py);
        the days-left line already exists in the India broker card.
NOT built (needs your answer / a test first): Fyers auto-catch of the login code, Tradebulls morning login.
Tests: test_part6/7/8 pass. test_india_telegram fails on your original repo too. Flutter not compiled.
Do on the phone: Termux battery = Unrestricted, termux-wake-lock, save Fyers PIN once, termux-setup-storage once (for the Download folder).
