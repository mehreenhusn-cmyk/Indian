# Part 4A + 4B (build 2026-10-22-part4b). Only the changed files. Put them over Indian_part3_final.
4A backend: NEW ai_evidence.py (extra tags, Bot vs Bot+AI vs AI Own after fees, patterns confirmed on older 60% AND newer 40%, paper gate),
  ai_vision.py saves "tags2" per signal and the prompt treats indicator agreement as a hint, api_server.py GET /api/vision/evidence.
4B app: NEW widgets/vision_evidence_view.dart, vision_tab_screen.dart (More > Evidence), app_provider.dart (fetchVisionEvidence).
Tags exist only for signals judged after this build, so it fills up over time ("needs more" until 12+ tagged trades).
Paper only. Nothing here changes a trade. Flutter is not compiled - build the app and open Vision > More > Evidence.
Python tests pass except the same 4 that fail on your original repo.
