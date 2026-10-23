# Ping Lab round 4 (2026-10-23) - Ping report

New: one text report for any AI (what was built, where the idea came from, why, how it works,
rules read live from the code, Bot A/B/C results with est. fees, Score, Lead, worker health,
honest verdict, known limits).

- backend/recovered_bot/ping_report.py (new) - builds the text, saves to the phone Download folder
- backend/recovered_bot/ping_api.py - GET /api/ping/report (text), GET /api/ping/report_save
- frontend/lib/screens/ping_tab_screen.dart - "Report" button in the Ping header (needs new APK)
- frontend/lib/widgets/report_download_card.dart - card takes title/description/routes (defaults unchanged)
- frontend/lib/widgets/ping_widgets.dart - "Small sample, not reliable." no longer shown twice
- backend/test_ping_report.py - 19 checks

Works without the new APK: open  http://127.0.0.1:8000/api/ping/report  in the phone browser,
or in Termux:  curl -s localhost:8000/api/ping/report > ~/ping_report.txt
Not tested: Flutter build (no Flutter SDK here), FastAPI routes (fastapi not installed here; syntax checked).
