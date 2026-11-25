/// One place to switch app parts on or off.
/// Strategy Doctor and the Labs are OFF (hidden, nothing deleted). Set to true to show them again,
/// and also set "doctor_enabled": true in the backend settings so their background jobs run.
const bool kShowStrategyDoctor = false;

/// PHONE LITE (Round 2, 26 Nov 2026). Read README5 "PHONE LITE" first.
/// true = the app shows ONLY: Home, Positions, Signals, More. Dual Bot, Brain, AI, Sniper, Study Lab, Diagnostics, Ping Lab, Chop Bot and their
/// dashboard rows / More tiles are hidden and their background fetches do not run. Nothing is deleted: set false to see them again
/// (the backend must then run with OWL_LITE=0 too). Do not turn this off unless the owner says so in plain words.
const bool kLite = true;

/// In lite mode the backend runs on THIS phone (Termux), so a fresh install talks to 127.0.0.1.
const String kLiteBackendUrl = 'http://127.0.0.1:8000';
