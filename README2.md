# README2 — OWL1 COMPLETE REQUIREMENTS & IMPLEMENTATION PROMPT

**Project:** OWL1  
**Repository:** https://github.com/mehreenhusn-cmyk/Indian  
**Branch:** main  
**Stack today:** Flutter Android app + Python/FastAPI backend + Binance market scanner/data  
**Document purpose:** This is the detailed prompt for Claude to understand the owner's actual requirements, inspect the existing project, compare this document with README.md, report what is already done versus missing, and then propose a safe, ordered implementation plan.

> IMPORTANT: Read this entire file and the existing README.md before changing code. Do not start by rewriting the app. The first task is an audit and a plain-language report.

---

## 1. OWNER'S MAIN GOAL — WHAT OWL1 SHOULD BECOME

The owner wants OWL1 to grow into a high-end, dependable trading terminal with an evidence-based AI Vision/Brain layer. This is not merely a request to change colours, add a chatbot, or create another BUY/SELL indicator.

The app should help answer, using real recorded evidence:

- What is happening in the market and in this position right now?
- Is the existing signal likely to be useful or weak, and why?
- When does a setup begin forming, when does it become confirmed, and is there a safe way to identify a valid setup earlier without using future information?
- Which timeframe and trend context are useful for a particular setup?
- Which setups work in trending, sideways/choppy, compression, expansion, retest, exhaustion or reversal conditions?
- How many trades are worth taking? When is WAIT or NO NEW TRADE better than taking every signal?
- What happened to profit after a position showed a good open P&L? How much was actually realized after fees and other costs?
- What did similar historical setups do, how many examples exist, and how reliable is that evidence?
- What has the Brain learned from previous mistakes, and what is still unknown?
- What should the user see on the screen to understand the answer quickly without digging through developer logs?

**The owner does not want to hand-author a long list of fixed indicator rules.** The system should capture accurate features and real outcomes, then discover candidate relationships, measure them, test them out-of-sample and explain them honestly. Examples like “price rising while Z-score falls” are research hypotheses, not rules to hard-code.

“Ultra / no compromise” means correctness, trustworthy data, safe behaviour, low latency, a clear architecture, maintainable code, a polished UI and real acceptance evidence. It does not mean adding every available framework or promising profits.

## 2. HOW README.md AND README2.md MUST WORK TOGETHER

There must not be two competing roadmaps.

- **README.md remains the existing project master record.** It contains historical work, current status, prior decisions, old task IDs, code references, dependencies, and the existing sequential roadmap. Preserve those details.
- **README2.md is this full requirement and implementation brief.** It explains what the owner wants and how Claude must audit, verify and implement it.
- If a supporting matrix is needed, create one file called `README2_RECONCILIATION.md`. Do not create several competing status documents without a real need.

Before coding, compare the complete current README.md and README2.md, plus relevant recovered prompts that are actually available. Classify each item as:
- SAME — accurately covered in both.
- README1_ONLY — in README.md but missing or too vague here.
- README2_ONLY — added requirement here.
- CONFLICT — the notes disagree or source code contradicts a note.
- HISTORICAL_DONE — completed earlier; retain the record and do not restart without evidence.
- NEEDS_EVIDENCE — requires current source, test, runtime or device verification.

Every important requirement, previous decision, completed item, open bug, test, dependency and old roadmap ID must be accounted for. If README.md contains a useful requirement missing here, add it to this file or reference it clearly. Never silently drop detail because it is inconvenient. Do not call a feature “done” merely because an old note says it was once completed; check current code and tests. Keep historical completion separate from current verification.

The existing README uses a canonical 24-Part sequence and older aliases including A–F, U1–U5, NEXT-1–10, B3/G1/G2, H1, S0–S19 and 6a–6j. Preserve and cross-reference those names; do not create a new conflicting sequence.

## 3. CONFIDENTIALITY, SECURITY AND PROJECT OWNERSHIP

This is the owner's private product and trading-strategy work. The repository is currently private; keep the project and its details private.

- Do not make the repository or prompt public, create a public mirror, or share the strategy, architecture, trade history, reports or screenshots outside the owner's workspace.
- Never put API keys, exchange credentials, passwords, tokens, account identifiers, private URLs, or real personal/account secrets in README files, source code, prompts, logs, screenshots or test fixtures.
- Keep Claude/NVIDIA/API credentials on the backend using environment variables or an appropriate secret store. Never ship secrets to Flutter or Android assets.
- Redact credentials from exceptions, logs, reports, generated prompts and diagnostic endpoints.
- Do not paste private exchange data into third-party AI services unless the owner has approved the data flow and it is necessary. Prefer minimal, redacted, derived features. Explain any data sent to an external provider.
- Do not alter GitHub visibility, permissions, secrets, integrations or external sharing settings.
- Treat live trading, destructive database operations, new recurring spend and data export outside the private project as approval-required actions.
- Do not claim privacy is guaranteed by a README; enforce it in repository settings, application code, permissions and provider configuration.

## 4. CURRENT PRODUCT AND REPORTED PROBLEMS TO VERIFY

The following are owner-reported history and starting points, not proof that every issue still exists. Check the current source, tests, logs and runtime before labelling anything an active bug.

### Trading and results
- The owner reports too many weak/fake signals in choppy markets.
- The existing bot has been described as relying mainly on an EMA50 close-cross/direction signal, with the signal candle low/high used for the initial stop and TP1–TP4 based on 200-candle standard-deviation bands. Verify the current implementation and every live order path.
- The owner has observed high open/unrealized P&L at times but wants to improve the amount actually realized and retained after fees.
- The owner wants to know when a setup starts, whether entry timing is late, which trend/timeframe context matters and which scalping setups can deliver a useful net result without excessive low-quality trades.
- The user wants historical outcome-based learning rather than manually fixed “price up + Z down = exit” rules.

### App and backend issues reported across earlier work
- Prior work has included Vision, Strategy Doctor, Filter Lab, Brain/Brain Skip, diagnostics, report, ping worker, PumpDump and SWR tuple-key fixes. Locate and reuse these systems where valid; avoid building duplicate replacements.
- Earlier discussion raised black/blank or empty positions/history screens, close/TP preview consistency, a Binance-like fast interface, backend startup and ping/worker issues, and a deprecated FastAPI startup-event warning. Check whether these are still present and reproduce where possible.
- The user has encountered ZIP updates that created an unwanted nested `Indian-main/` directory. Keep the correct repository root and never introduce `Indian-main/Indian-main/`.
- Heavy research/collector workloads may slow or freeze the phone/backend. Measure resource use and bound background work.
- Previous notes said CI may not actually run the tests that comments imply it runs. Inspect the current workflows and report the real commands/results.

For every issue report: current status, reproduction steps, actual source path/symbol, root-cause evidence, test coverage, proposed minimal fix and regression test. If not reproduced, say so instead of inventing a fix.

## 5. LIVE-TRADING SAFETY — NON-NEGOTIABLE

The current bot is the baseline and must remain available for comparison. Do not replace it just to add AI.

The master notes state that the main bot can send LIVE Binance orders when live trading is enabled. Historically identified paths include:
- `execution_router.py` → `binance_trader.py` / `protection_manager.py`
- `ai_live_client.py` → `ai_live_executor.py`

These names are a starting map only; verify the current call graph and exact files.

**Do not change without separate explicit owner approval:**
- live entry or exit conditions;
- order routing or execution;
- stop loss, take profit, break-even or protective-order behaviour;
- quantity/position sizing, leverage or risk defaults;
- close/reduce/re-entry behaviour;
- the meaning/default of `live_trading_enabled`;
- any Brain/Vision proposal that gains authority to block, allow or manage a live trade.

No test may create, amend, cancel or close a real exchange order. Use mocks/fakes and isolated paper/sandbox testing. Research collectors, replay and Scalp Lab must not import or call live execution paths. AI failure, timeout, invalid output or unavailable API must never stall or change the existing bot.

A future live pilot is not approved by this document. It requires a separate owner decision, strong paper/shadow evidence, explicit risk limits, monitoring, rollback and tests.

## 6. INDICATOR SCOPE AND EXACTNESS

The owner has described two indicator families as the intended V2 research scope:

1. **EMA50 + statistical-deviation (SD) bands** — including the existing 200-candle basis and bands where present.
2. **Special Master momentum/statistical pane** — TSI and Z-score/Z-SMA behaviour.

Previously discussed components include EMA10/30/50/100/200, EMA30/50 cloud, 200-candle SMA/SD bands at ±1/±2/±3, Z-SMA50, TSI Fast 25/5/14, TSI Slow 25/13/13, reversal arrows and timeframe/structure context. Verify exact formulas from source. These parameter notes do not authorize changing current rules.

The existing README has explicitly restricted extra indicator families in V2: do not add ADX, ATR, RSI, MACD, VWAP, Hurst or a third indicator to V2 features/scores/replay unless the owner separately changes scope. Any allowed metadata already present must remain metadata-only unless approved.

The exact original Pine scripts for Special 13 and Special Master have previously been reported as unavailable in the repository. If still missing, mark exact parity as NOT VERIFIED and request the source files. Do not invent formulas, silently approximate them, or claim exact parity from screenshots.

Required checks:
- candle-close versus intrabar signal timing;
- repainting or use of incomplete candles;
- duplicate or delayed signals;
- correct symbol/timeframe/timezone alignment;
- EMA/SD formula and band alignment;
- TSI/Z-score raw values, slope and state;
- signal candle plus preceding context;
- repeatability from saved market data.

## 7. STRATEGY IMPROVEMENT: TIMING, TREND, EARLY SETUP AND SCALPING

This is a central owner requirement. The goal is not merely to filter existing signals. The owner wants to understand **when a setup begins forming, whether an entry can be identified before the move is mostly over, which trend/timeframe context helps, and which short-duration setups retain positive net results after costs**.

Study, do not assume:

1. **Baseline replay:** reproduce the current strategy using timestamped candles and trade/signal logs. Show the earliest time each input was genuinely available.
2. **Setup lifecycle:** separate precursor, setup forming, trigger, candle close, bot decision and actual execution timestamps.
3. **Early-entry research:** identify candidate precursor patterns before the existing signal; replay using only data available at that time. Measure false starts, adverse excursion, missed moves, net expectancy and stability. Never use future candles to pretend an entry was knowable earlier.
4. **Trend/timeframe context:** test higher-timeframe context against lower-timeframe trigger using only the approved indicator scope. Report exact timeframe and timestamp alignment.
5. **Timing Sync:** compare same-candle indicator alignment with one- or two-candle delays. Check whether earlier alignment really helps or just creates false starts.
6. **Scalping/time in trade:** study supported candle timeframes and time-of-day/session cohorts. Measure hold duration, time to MFE/MAE, net expectancy, fees, slippage, drawdown, trade count and stability.
7. **Trend vs chop:** compare trending, sideways/choppy, compression, expansion, retest, exhaustion and reversal conditions. These are labels/hypotheses until defined reproducibly and validated; do not hard-code “chop = no trade.”
8. **Indicator interaction:** study EMA/SD position and shape alongside TSI/Z-score, including agreement/disagreement, momentum weakening while price rises, momentum strengthening, extremes, retests and continuation/reversal. Do not hard-code any one pattern as a universal action.
9. **Profit leakage:** record open P&L, peak/MFE, MAE, realized exit, giveback, hold duration, exit reason, fees, funding and slippage. Compare possible exit/protection variants in offline replay or paper mode only.
10. **Re-entry / stop-wick:** study stop-wick → continuation → re-entry as a research category; do not auto-re-enter live positions.
11. **Setup ranking:** compare net expectancy, drawdown, profit factor, sample size, out-of-sample stability, trade frequency and uncertainty. Do not optimize only for win rate or gross/open P&L.
12. **Evidence-based result:** return TAKE-AS-RESEARCH-CANDIDATE, WATCH or SKIP-AS-RESEARCH-CANDIDATE with reason, sample size, counterexamples and uncertainty. These are research labels, not live order commands.

A previous project note reportedly found same-candle Timing Sync at about +1.33 USDT/trade over 61 trades, and “Z first, main 1–2 candles later” at about −4.98 USDT over 27 trades. This is a historical recorded result only. Re-run from the original rows and verify dates, definitions, fees and leakage before relying on it. Do not present it as current verified performance.

## 8. AI VISION AND BRAIN — REQUIRED SEPARATION

The user wants AI to discover useful behaviour from real data, not be forced into a long list of invented rules.

Keep these roles distinct:

- **Existing bot:** deterministic baseline; initially unchanged.
- **AI Vision:** interprets the current timestamped market/indicator snapshot and explains what it sees.
- **Brain:** stores and evaluates historical judged outcomes, similar setups, past mistakes and lessons.
- **LLM reasoning:** generates a structured explanation from supplied evidence; this is not the same as model training or proven statistical learning.
- **Replay/statistical evaluation:** measures whether a candidate relationship predicts outcomes.
- **Production strategy:** live rules, protected until separately approved.

Target data flow:

Existing bot / market data  
→ timestamped signal and state-change event  
→ feature/event collector  
→ validated, versioned dataset and outcome labels  
→ Vision current-state analysis + Brain historical evidence  
→ optional Claude explanation  
→ shadow/paper A/B evaluation  
→ actual outcome reconciliation  
→ versioned research result  
→ human-reviewed proposal.

AI should investigate signal quality, continuation/reversal, false signals, expected move, adverse/favourable excursion, regime-specific performance, indicator agreement/disagreement, profit giveback, hold/exit behaviour and trade-frequency trade-offs.

For every signal/event, store only fields that can be supported, such as timestamp, symbol, timeframe, direction, OHLC and preceding candles, approved indicator values/slopes, EMA relationships, SD/band state, data-quality flags, bot decision, Vision output/version, historical evidence count, entry/SL/TP as actually recorded, MFE, MAE, time to MFE/MAE, actual exit, realized P&L, fees, funding/slippage estimates and final outcome.

Separate:
- features genuinely available at decision time;
- future outcome labels used only after the event for evaluation/training.

Never leak future values into a live decision feature. Never invent sample counts, indicator values or confidence percentages. “Not enough data” is a valid result. Do not call Claude on every price tick. Use event-driven analysis, timeouts, bounded concurrency and caching; the trading/data path must not wait for the LLM.

Initial Vision should be passive/shadow. Compare:
- A = existing bot baseline;
- B = existing bot plus a simulated Vision filter/recommendation.

Compare trade count, win rate, net P&L, fees, drawdown, profit factor, expectancy, MFE/MAE, avoided losers, missed winners and performance by regime/indicator relationship. Use matched periods and costs, out-of-sample validation and honest uncertainty. A 2–3 day passive observation period was discussed as an initial check, not proof of a reliable edge. Some research may need several weeks of clean data. A previously noted 100-judged-trade Brain readiness target is a checkpoint, not a guarantee of profitability or sufficient proof by itself.

A paper account around 100 USDT, daily target lock around +30 USDT and daily loss limit around -10 USDT were discussed as adjustable paper-test proposals. Verify current settings; do not silently apply these to live trading.

## 9. MARKET DATA, MOVERS, DUAL BOT AND SCALP LAB

The user wants the system to retain historical context rather than only show today's movers. Verify the existing rolling universe logic and whether it uses authentic snapshots.

A previously recorded requirement was today's top 5 movers plus coins that appeared in the top 5 on each of the previous seven completed days, deduplicated. Historical memory matters because a coin may pump, digest/sideways, retest a higher timeframe, continue for another day or two, then lose volume and slide. Treat this as a lifecycle research hypothesis, not a guaranteed pattern.

Keep these clearly distinguished:
- current live snapshot;
- authentic historical snapshot captured at that time;
- retrospective reconstruction from candle history;
- synthetic/test fixture.

Never label a retrospective reconstruction as an authentic historical snapshot. Historical top-five gainers/losers for 1/2/3/7 days must use the correct historical window and source.

Price-action and volume layers previously discussed included signal-candle strength, rejection wicks, candle size relative to prior candles, EMA50 retest held/broken, relative volume and follow-through. The recorded intention was report/measurement-only, not active trade filters, unless separately approved. Do not add a volume floor or trade exclusion just because volume is measured.

Research collection must be bounded by measured CPU, memory, network and storage. Earlier notes discussed roughly 21 symbols/two timeframes and caps around 30 or 51 coin-timeframe items depending on inclusion rules; these are planning notes, not permanent truth. Measure the current load before setting caps. Collect public market data using public endpoints where possible, respect rate limits, handle gaps and restarts idempotently, and avoid authenticated trade permissions for research collectors.

The prior design calls for a separate `v2_market.db`, public GET-only collectors, explicit gap logs and a hard cap near 300 MB. Verify current code before relying on this. On capacity, pause and report the reason; never silently remove protected trade history or gap evidence.

Scalp Lab should separate each research category's definitions, setup records, trade results, fees, sample size, failure cases and conclusions. Shared raw candles may be reused, but category P&L must not be double-counted. Initial Scalp Lab research may require 3–4 weeks of clean candle data; report coverage and gaps rather than pretending the sample is sufficient.

## 10. DATA INVENTORY, QUALITY, RETENTION AND CLEANUP

The user wants a clean, understandable data architecture and removal of genuinely unnecessary clutter, but does not want valuable history lost.

Inventory all current databases/tables, JSON/CSV/Parquet data, candle caches, logs, model outputs, report exports, temporary files, migrations, generated artefacts and dynamic storage paths. For each item, identify:
- authoritative/source-of-truth or derived;
- owner/module and readers/writers;
- paper/live/research/synthetic mode;
- age, size, coverage, quality and retention;
- backup/rebuild path;
- proven references from runtime/tests/jobs/settings.

Validate OHLCV order and relationships, missing/duplicate candles, gaps, timestamps/timezones, symbol/timeframe consistency, stale snapshots, outcome labels and mixed-mode records.

The owner previously stated that trade data must not be deleted while the Brain is being evaluated and before it is ready for real-money consideration. Therefore:
- Default to read-only inventory, dry-run report, quarantine/archive and deduplication proposals.
- Do not delete live/paper trade history, Brain journeys, outcomes, mistakes, lessons or historical cohorts without separate explicit approval.
- Do not decide something is unused based only on lack of static references.
- If storage pressure is real, report growth and safe alternatives first.
- The market-data retention cap is not permission to delete trade data.
- SQLite WAL/SHM behaviour matters: verify that read-only inventory does not mutate databases or create unwanted sidecar files.
- If an artefact is reproducible, prove the source and rebuild before proposing removal.

India-specific requirements: verify INR conversion, timezone/day-boundary handling, fees, funding, realized net P&L and tax/report exports if present or explicitly in scope. Label estimates and limitations; do not present the app as a tax/legal authority. Binance crypto data is not the same as Indian securities-market data.

## 11. BACKEND AND DATA-FLOW ARCHITECTURE

Map actual FastAPI routers, services, schemas/models, database owners, collectors, workers, schedulers, startup/shutdown, WebSocket/polling and execution entrypoints.

Expected principles:
- Keep market-data/trading processing separate from slower AI reasoning.
- Keep public market data separate from authenticated account/trading access.
- Use typed request/response schemas, validation, consistent errors and pagination/versioning where useful.
- Record source timestamp, received timestamp, symbol, timeframe, schema/version, mode, provenance and quality flags.
- Make collectors idempotent, rate-limit aware, restart-safe and gap-aware.
- Handle reconnect/backoff, stale state, duplicate events, cancellation, timeouts and partial failures.
- Avoid heavy synchronous work in the request/event loop.
- Provide safe health/diagnostics endpoints and bounded logs without credentials.
- Verify Telegram formatting/links and environment-based credentials where present.
- Verify the correct backend requirements file, commands, CI and deployment setup from the repository rather than guessing.

Document a concrete data-flow diagram using actual source paths. Every displayed UI value should have a traceable source: exchange/API → backend owner → storage/cache → API contract → Flutter state → screen. Do not put business rules inside widgets.

## 12. FRONTEND — HIGH-END EXCHANGE TERMINAL, NOT A GENERIC DASHBOARD

Keep Flutter unless measured evidence proves a specific bottleneck that cannot be fixed reasonably. Do not replace Flutter for fashion. Native Android/Kotlin is acceptable only for a demonstrated capability/performance need. Do not mix Flutter, React Native, WebView and other UI frameworks without a clear reason.

The desired result is a premium, fast, unique OWL1 terminal. “Premium” means clear hierarchy, correct data, low latency, useful interactions, reliability and accessibility—not gradients alone.

Audit and improve, using current screen structure:
- **Wallboard/Home/Dashboard:** glanceable market state, backend/scanner health, data freshness, PAPER/LIVE/SHADOW mode, realized and unrealized P&L, positions and important alerts.
- **Navigation:** coherent primary tabs and nested pages for Dashboard, Market/Radar, Positions/History, Brain/Vision, Scalp Lab/experiments, Dual Bot/Wallet, reports, settings and diagnostics as applicable. A previous proposal was Dashboard, Market, Positions, Brain, More; verify fit with current screens before changing navigation.
- **Positions/history:** no black/blank screens; correct loading/empty/offline/stale/error states; filters and refresh; correct mode and P&L labelling.
- **Position cards:** compact and readable; entry/current price, quantity, stop/targets, fees/funding, realized net vs floating P&L, data freshness and mode. A close preview must match the authoritative backend action.
- **Charts:** candles, EMA50, SD bands, entries/exits and SL/TP overlays aligned to correct symbol/timeframe/timestamps; TSI and Z-score panes where available; crosshair, zoom/pan and clear candle-close/provisional state. Do not fake an overlay or formula.
- **AI Vision/Brain:** current observation, historical evidence, sample size, similar setups, uncertainty, past mistakes and recommended research action. Distinguish current Vision from historical Brain evidence. “Not enough data” must be visible.
- **Radar/movers:** correct time window, authentic vs retrospective label, source and timestamp.
- **Strategy Doctor / Filter Lab / Brain Skip:** useful evidence and actionable explanation, not decorative badges.
- **Diagnostics feed:** prior concern was that feed/status moved down or disappeared after scrolling. Inspect current scroll structure; keep summary/status in the intended visible position, allow history to scroll independently, avoid gesture conflicts and unexpected auto-jumps.
- **Settings:** grouped logically, units and defaults clear, PAPER/LIVE labels unmistakable, fees/report configuration transparent and dangerous actions guarded.
- **Reports/history:** timeframe, timezone, currency, mode, fees and inclusion rules explicit.
- **Performance:** granular state updates, no full-screen rebuild for one value, efficient WebSocket propagation, chart/list virtualization, caching, bounded buffers, light animations and no expensive work on the UI thread.
- **Presentation system:** consistent OWL1 identity, semantic colours, typography, spacing, cards, radii, icon rules, responsive layouts, safe areas, text scaling, accessible touch targets and screen-reader labels.
- **Every data-driven screen:** loading/skeleton, empty, offline, stale, partial, error, retry and reconnect states.
- Never insert fake numbers or green health statuses to make the app appear complete. Never use excessive animations, giant empty cards, unreadably dense cards, repeated content or decoration that harms performance.

## 13. CLAUDE API AND NVIDIA RESEARCH

Claude API is the first reasoning-provider candidate discussed by the owner. Keep it behind a provider interface and on the backend. Do not replace it just because Nemotron exists.

Five NVIDIA Skills/catalog URLs recovered from the earlier user-shared prompt:
1. https://build.nvidia.com/skills?pageSize=96&filters=domain%3Adomain_ai_and_machine_learning&page=1
2. https://build.nvidia.com/skills?pageSize=96&filters=domain%3Adomain_ai_and_machine_learning&page=2
3. https://build.nvidia.com/skills?pageSize=96&filters=domain%3Adomain_ai_and_machine_learning%2Cdomain_infrastructure%2Cdomain_developer_tools%2Cdomain_graphics_and_media%2Cdomain_physical_ai%2Cdomain_accelerated_computing%2Clibrary%3Alibrary_tao_toolkit%2Clibrary%3Alibrary_nemo_megatron_bridge%2Clibrary%3Alibrary_bionemo_open_models%2Clibrary%3Alibrary_nemo%2Clibrary%3Alibrary_bionemo_nims%2Clibrary%3Alibrary_monai%2Clibrary%3Alibrary_deepstream_sdk%2Clibrary%3Alibrary_earth2studio%2Clibrary%3Alibrary_megatron_core%2Clibrary%3Alibrary_nemotron_for_digital_health%2Clibrary%3Alibrary_jetson%2Clibrary%3Alibrary_dynamo%2Clibrary%3Alibrary_nemo_framework%2Clibrary%3Alibrary_nemotron%2Clibrary%3Alibrary_rag%2Clibrary%3Alibrary_nemo_rl%2Clibrary%3Alibrary_nemo_retriever%2Clibrary%3Alibrary_physicsnemo%2Clibrary%3Alibrary_riva%2Clibrary%3Alibrary_cosmos%2Clibrary%3Alibrary_cuopt%2Clibrary%3Alibrary_nemo_agent_toolkit%2Clibrary%3Alibrary_dali%2Clibrary%3Alibrary_doca%2Clibrary%3Alibrary_holoscan%2Clibrary%3Alibrary_nvshmem%2Clibrary%3Alibrary_cuda_tile%2Clibrary%3Alibrary_trustworthy_ai%2Clibrary%3Alibrary_cudf%2Clibrary%3Alibrary_nvflare&page=3
4. https://build.nvidia.com/skills?pageSize=96&filters=domain%3Adomain_ai_and_machine_learning%2Cdomain_infrastructure%2Cdomain_developer_tools%2Cdomain_graphics_and_media%2Cdomain_physical_ai%2Cdomain_accelerated_computing%2Clibrary%3Alibrary_nemo%2Clibrary%3Alibrary_nemotron%2Clibrary%3Alibrary_rag%2Clibrary%3Alibrary_nemo_retriever%2Clibrary%3Alibrary_nemo_agent_toolkit%2Clibrary%3Alibrary_trustworthy_ai%2Clibrary%3Alibrary_cudf%2Clibrary%3Alibrary_nvflare&page=4
5. https://build.nvidia.com/skills?pageSize=96&filters=domain%3Adomain_ai_and_machine_learning%2Cdomain_infrastructure%2Cdomain_developer_tools%2Cdomain_graphics_and_media%2Cdomain_physical_ai%2Cdomain_accelerated_computing%2Clibrary%3Alibrary_nemo%2Clibrary%3Alibrary_nemotron%2Clibrary%3Alibrary_rag%2Clibrary%3Alibrary_nemo_retriever%2Clibrary%3Alibrary_nemo_agent_toolkit%2Clibrary%3Alibrary_trustworthy_ai%2Clibrary%3Alibrary_cudf%2Clibrary%3Alibrary_nvflare&page=5

Also evaluate:
- Nemotron: https://developer.nvidia.com/topics/ai/nemotron
- Quantitative Signal Discovery Agent: https://build.nvidia.com/nvidia/quantitative-signal-discovery-agent
- NeMo Agent Toolkit: https://developer.nvidia.com/nemo-agent-toolkit
- NVIDIA blueprint/RAG ecosystem: https://build.nvidia.com/blueprints

For each candidate, research the current official documentation and state the exact OWL1 use case, measurable benefit, required hardware/GPU/hosted service, license, privacy, latency, recurring cost, operational burden, test and rollback. Prioritize quantitative signal discovery/evaluation, retrieval of historical similar setups and tool orchestration only if useful. Do not add unrelated NVIDIA technologies or a GPU dependency just for fashion. The user previously mentioned a roughly $10 Claude plan/API budget; verify actual billing model and current costs instead of assuming subscription includes API credits.

## 14. TESTING AND ACCEPTANCE

Audit existing tests before writing new ones. Identify the actual commands and run only feasible, relevant tests during the initial audit. Report skipped tests and why.

Required coverage as applicable:
- deterministic strategy/indicator characterization and regression tests;
- no-live-order tests using mocks/fakes;
- API schemas, validation, errors and mode separation;
- data quality, timestamp alignment, gaps, deduplication and retention;
- AI output schema, provider timeout/failure, redaction and missing-data handling;
- replay leakage prevention and train/evaluation separation;
- P&L/fees/funding reconciliation and MFE/MAE;
- frontend state, loading/error/empty/offline cases and preview/backend parity;
- performance/resource measurements for collector and UI;
- CI commands and Android/Flutter build when the environment supports them.

Do not claim tests passed unless they were actually run. Distinguish code review, unit tests, integration tests, CI, Android build and real-device validation. Never fabricate screenshots, benchmarks, test output or historical sample counts.

Acceptance requires observable results, not merely a file being created. Each delivery must state:
- exact changed files;
- why each change was needed;
- tests/commands actually run and results;
- current limitations;
- rollback approach;
- what remains;
- the single next dependency-ready step;
- confirmation that live-trading paths/settings remained untouched, or explicit approval and details if a change was authorized.

## 15. CLEAN IMPLEMENTATION ORDER

Do not start all features at once. After audit and owner approval, use the current canonical README.md 24-Part roadmap as the source of ordering and dependencies. The high-level execution should be easy to understand:

### Phase A — Audit and safety foundation
- Read both READMEs and relevant recovered prompts.
- Map architecture, all live execution paths, database owners, API routes, Flutter screens and CI.
- Record baseline test status and reported bugs.
- Complete requirements reconciliation, file matrix, data inventory and risk plan.
- Implement safety/redaction/inventory foundation only after approval.

### Phase B — Backend and data reliability
- Complete approved safety, redaction and inventory foundations.
- Characterize protected trading rules with no-live-order tests.
- Build isolated public market-data collection/storage and candle validation as approved.
- Add reliable event/feature collection, provenance, health/diagnostics and P&L reconciliation.
- Establish Vision/Brain schemas, outcome labels, provider isolation and shadow/replay evaluation.
- Keep research data and trade data separate; preserve historical records.

### Phase C — Research and strategy evidence
- Validate indicator formulas and timestamp alignment.
- Run baseline replay, timing/early-entry, trend/timeframe, chop, scalp, MFE/MAE and profit-giveback studies.
- Evaluate historical movers, Scalp Lab categories and re-entry hypotheses.
- Report sample coverage and uncertainty; do not enable live strategy changes.

### Phase D — Flutter presentation
- After API contracts and source-of-truth data are stable, implement the premium design system and screen states.
- Improve dashboard/wallboard, charts, positions/history, Vision/Brain, Radar, Strategy Doctor, diagnostics, reports and settings.
- Optimize live updates and test on Android where possible.
- Do not fake missing backend functionality with frontend-only placeholder numbers.

### Phase E — Integration and acceptance
- Verify end-to-end flow from market source/database through API to Flutter.
- Run backend tests, Flutter tests/analyze/build, contract checks and CI as environment permits.
- Compare paper/shadow outcomes against the baseline.
- Update README.md with evidence and the exact next task.
- Only then consider another approved delivery.

Actual subtask order must follow the dependencies in README.md. If a dependency means a small frontend/backend slice must alternate, explain why, but preserve the broad grouping so the owner can follow progress.

## 16. AUDIT-ONLY FIRST RESPONSE REQUIRED FROM CLAUDE

Before changing code, return a concise owner-friendly report containing:

1. **What the owner wants:** in plain English/Roman Hinglish.
2. **What the app currently has:** based on files actually found.
3. **Architecture/data flow:** actual current backend → API/storage → Flutter flow.
4. **Requirements reconciliation:** what README.md has that README2 missed, what is duplicated, and what conflicts.
5. **Reported problems:** currently reproduced, not reproduced, historical or unverified.
6. **Strategy research:** timing, early setup, trend/timeframe, scalping, chop and realized-profit plan.
7. **AI Vision/Brain:** what exists, what is missing and what evidence is available.
8. **UI/presentation:** screen-by-screen current status and design/performance gaps.
9. **Data inventory:** protected stores, questionable data and safe cleanup proposal. Do not delete anything.
10. **NVIDIA/Claude:** relevant verified findings, likely costs/prerequisites and what should be deferred.
11. **Exact file matrix:** current paths, proposed paths, dependencies, acceptance criteria and tests.
12. **Test evidence:** commands actually run, exact results and anything not run.
13. **Risks/decisions needed:** especially anything affecting live trading, data loss, privacy or recurring cost.
14. **One next step:** the single safest dependency-ready task and why it comes first.

Do not begin a broad implementation in the first response. Wait for owner approval of the proposed first delivery.

## 17. CONTINUOUS WORKFLOW — DO NOT MAKE THE OWNER RE-EXPLAIN

For every future update/ZIP/commit:
1. Read README.md and the relevant README2 sections.
2. Identify the latest evidence-backed DONE milestone.
3. Find the first unfinished, dependency-ready task.
4. Inspect the relevant files and existing tests.
5. State the intended small delivery and risk before editing.
6. Implement only the approved scope.
7. Run the relevant tests; do not run expensive unrelated tests without reason.
8. Update README.md status, test evidence and next action.
9. Keep cumulative ZIP/repository root correct if packaging is requested; no nested `Indian-main/`.
10. Summarize in plain language: **Kya kiya → Kya test hua → Kya baaki hai → Next kya hai.**
11. Stop and wait for the next owner instruction.

Do not ask again for decisions already recorded in README.md. If a genuinely new conflict exists, ask only the necessary focused question.

## 18. FINAL PRODUCT SUCCESS CRITERIA

OWL1 is progressing toward success when:
- The existing trading baseline remains intact and reproducible.
- The two approved indicator families are accurately represented or parity limitations are explicit.
- Signal and market events are timestamped and reproducible.
- Historical evidence distinguishes authentic snapshots from retrospective proxies.
- Fake-signal behaviour, setup timing, scalp outcomes and profit leakage can be measured honestly.
- Net results account for costs and drawdown, not only open P&L or win rate.
- AI Vision explains current state; Brain evidence remains traceable to historical outcomes.
- LLM output cannot invent numbers or override safety.
- Flutter is premium, fast, readable, accessible and correct on a real Android device.
- Backend research cannot freeze or destabilize the bot.
- Data cleanup preserves protected trade history and is reversible/approved.
- Each feature has tests and evidence; each unknown is labelled unknown.
- The owner can understand progress without repeating the same requirements.
- No live-trading authority has been silently granted.

**Final instruction:** Audit first. Reconcile README.md with this file. Keep private project details private. Preserve working code and historical records. Do not change live trading. Propose one clear next delivery, wait for approval, then implement and prove it.


---

# PART R — FULL MERGE CHECKLIST FROM THE THREE OWNER PROMPTS

This section is deliberately part of README2 itself. It is not a new roadmap and does not replace the earlier sections. Claude must use this checklist to verify that the three detailed source prompts have been carried into one complete OWL1 specification. The recovered sources include the Claude Opus master prompt, the AI Vision + NVIDIA frontend/backend prompt, and the long Version 2 master prompt with raw-data/research memory, visualisation, explainability and continuous-execution requirements. Similar/duplicated statements may be merged, but their meaning and constraints must not be lost.

## R1. Owner workflow and project continuity

- Treat OWL1 as an existing app, not a greenfield demo.
- First inspect the actual repository, full README.md, this README2.md, source tree, test tree, dependency manifests, CI and build setup. Do not infer current implementation from old notes alone.
- Initial response is audit-only: no code edits, data edits, migrations, dependency changes, UI changes or trading changes.
- Give a coherent architecture, product/UI plan, data model, API contract plan, phased dependency graph, file-level changes, test/acceptance criteria, risks, estimates and rollback plan.
- Find the exact remembered Claude plan of approximately 43 parts / 6,000–7,000 lines if actually available. If it is not present, say so; never reconstruct it as if it were the original.
- Do not force an arbitrary number of parts or lines. Estimates are ranges derived from inspected code. The whole product plan is unified even though implementation is staged.
- Wait for owner approval before implementation. After approval, continue through the agreed plan without repeatedly asking the owner to restate requirements.
- README.md remains the one living status/roadmap record. README2.md remains the complete specification/prompt. Keep these roles clear; do not create competing master roadmaps.
- For each delivery, update README.md with real status, exact changed files, test evidence, limitations, rollback and the single next task.
- If ZIP delivery is requested, include cumulative changes not yet confirmed applied, preserve correct `Indian-main/` root and README location, and never nest `Indian-main/Indian-main/`.
- Report Passed / Failed / Not Run / Blocked accurately. File existence, a written test, a nice screenshot or an LLM answer is not proof of a working feature.

## R2. Required source-prompt reconciliation

Before implementation, create a traceability table inside the audit report (or a supporting matrix only if needed). Every requirement from the three recovered prompts and README.md must map to:
- Stable requirement ID and original source prompt/section.
- Current implementation status: Implemented, Partial, Missing, Broken, Unknown, Historical Done or Needs Evidence.
- Actual source paths and symbols, not guessed file names.
- Canonical roadmap part and dependency.
- Data/API/UI ownership.
- Acceptance criteria and tests.
- Risk level and whether owner approval is required.

Do not silently delete a requirement because it is repeated. Merge duplicates but retain traceability to every source. Where two source prompts disagree, report the conflict and preserve the safer behavior until the owner decides. Where an item is already done, verify it and retain the historical record rather than rebuilding it automatically.

## R3. Existing app areas to audit (do not assume all are present)

Inspect and verify each area if found in the repo:
- Dashboard/Home/Wallboard and market summary.
- Binance scanner, market candidates and historical movers.
- Positions, open orders, trade history, close preview and TP adjustment.
- Existing EMA50/SD-band signal bot and protective orders.
- Special 13 and Special Master indicator parity.
- AI Vision and the current provider/API integration.
- Brain, Brain Skip, historical journeys and outcome evaluation.
- Scalp Lab categories, experiments and separate ledgers.
- Timing Sync, setup lifecycle, early-entry and trend/timeframe research.
- Tag Lab and historical tag versioning.
- Strategy Doctor and Filter Lab.
- Ping Lab / backend health / WebSocket diagnostics / diagnostic event feed.
- Dual Bot / Dual Wallet / account and execution identity.
- Reports/downloads, fees/funding/net P&L and India-specific INR/timezone/reporting.
- Settings, notifications/Telegram, data retention, backup/export and privacy.
- Backend workers, scheduled jobs, API routes, storage, migrations and startup/shutdown.
- Flutter navigation, shared components, chart package, Android lifecycle and CI.
If a module is absent, mark it missing or unknown. Do not build a fake placeholder and label it complete.

## R4. Detailed market-data and storage requirements

- Map the real source of every market value and every UI value: exchange/public endpoint or account endpoint → collector/client → validation/normalisation → storage/cache → API/WebSocket → Flutter state → displayed field.
- Identify the source of truth for candles, snapshots, signals, positions, fills, fees, funding, realized P&L, floating P&L and reports.
- Keep public market-data collectors separate from authenticated trading/account services.
- Use event timestamps and receive timestamps, symbol, timeframe, source, schema/formula version, candle status, data quality and mode/provenance.
- Validate OHLCV ordering, duplicate/out-of-order candles, missing intervals, timezone alignment, symbol/timeframe mismatch, stale feeds and partial snapshots.
- Make ingestion restart-safe and idempotent. Add bounded queues, rate-limit handling, backoff, reconnect/resync and explicit gap records where relevant.
- A connected WebSocket is not proof of fresh data. Show connection, subscription, event arrival and candle freshness separately.
- Keep last-known-good data with a stale marker instead of replacing unavailable values with zero.
- Separate authentic snapshots, retrospective reconstructions and synthetic fixtures everywhere in storage, UI and reports.
- The previous design discussed a separate `v2_market.db` for research/public market data and a storage cap around 300 MB. Verify current files and load before adopting this. A cap means pause/report/approved retention policy, not silent deletion.
- Measure collector CPU, memory, request/subscription rate, disk growth, recovery time and impact on the existing backend before widening the universe. Earlier limits such as 21 symbols/two timeframes or 30/51 coin-timeframe items are historical planning numbers to validate, not immutable settings.
- Inspect SQLite WAL/SHM and read-only inventory behaviour. Do not accidentally mutate/create sidecars while claiming a strictly read-only audit.
- Inventory caches, generated reports, logs, temporary files, stale duplicates and unreachable data. Prove references and rebuildability before proposing deletion. Use dry-run, backup/archive/quarantine and explicit owner approval for destructive cleanup.
- Preserve all trade history, Brain journeys, outcomes, lessons and historical cohort evidence while Brain is being evaluated. Never delete it merely because it is old or absent from a static code reference.

## R5. Historical movers, pump lifecycle and Wallbot/scalp research

- Verify whether the current product has a Wallbot/Wallboard or similarly named market board; preserve actual naming and routes from source.
- For historical top-five movers, use each completed day's authentic snapshot. Do not reuse today's top five to fill the previous seven days.
- If authentic history does not exist, label it unavailable and begin prospective collection only after the approved plan; do not invent historical rankings.
- Track coin episodes/lifecycle when data supports it: pump/initial expansion → continuation → digestion/sideways → retest → possible continuation → weakening volume/slide. These are research hypotheses, not guaranteed lifecycle rules.
- Avoid counting 20 snapshots from the same coin episode as 20 independent examples. Define episode IDs and overlap rules.
- Keep current live candidates, authentic historical snapshots and retrospective candle-derived cohorts visibly distinct.
- Scalp Lab categories need separate definitions, setup counts, trade records, P&L, fees, sample size, hold time, failure cases, confidence and next experiment. Shared raw candles are allowed; duplicate P&L counting is not.
- Price-action context previously discussed includes signal candle strength, rejection wick, candle size relative to recent candles, EMA50 retest held/broken, relative volume and follow-through. Measure/report these only where data supports them. Do not turn them into production filters without separate approval.
- Allow a clean data-collection period of around 3–4 weeks if necessary. Report gaps and coverage; do not claim an edge before adequate evidence.

## R6. Detailed Brain/Scalp experiment outputs

Every experiment should define before running:
- Hypothesis and intended decision use.
- Dataset/query, symbols, timeframe, period and cohort selection.
- Feature availability timestamp and candle-close/provisional rules.
- Outcome horizon and setup/episode identity.
- Baseline comparison and candidate variants.
- Fees, funding, slippage, spread and fill assumptions.
- Exclusion rules, overlap handling and missing-data policy.
- Train/research period versus holdout/out-of-sample period.
- Metrics: sample count, net expectancy, net P&L, drawdown, profit factor, win rate, trade frequency, MFE/MAE, time to MFE/MAE, giveback and uncertainty where calculable.
- Counterexamples, failure cases, sensitivity and whether the result survives another period/symbol group.
- Reproducible query/config/version, result artifact and next experiment.
- Result label such as Insufficient Data, Exploratory, Watch, Promising Candidate, Rejected or Needs More Validation. These are research labels, not live instructions.

The owner wants to know when to take a setup, when to wait, when no new trade is better, how long to hold, and what evidence supports an exit/profit-protection idea. The system must test these questions rather than claim it can predict profit. Record skipped opportunities so both avoided losers and missed winners can be measured.

## R7. Premium Flutter experience — detailed expectations

Build a coherent terminal, not disconnected decorative screens:
- Audit current screen hierarchy and preserve useful navigation before redesign.
- Limit primary bottom tabs; put detailed features inside clear nested sections rather than placing every screen on the bottom bar.
- A previous navigation candidate was Dashboard, Market, Positions, Brain, More; treat it as a candidate to validate, not an instruction to break existing navigation.
- Brain should expose useful areas such as Overview, Scalp Lab, indicator behaviour, experiments, coin lifecycle and Knowledge/Results where appropriate.
- Dual Bot/Wallet should clearly separate identities, balances, positions, orders, risk and P&L.
- Settings, alerts/signals, reports/downloads and diagnostics must remain discoverable.
- Back navigation, nested tabs, swipeable sections, modal sheets, chart fullscreen and selected-tab state must be predictable. Avoid duplicate bottom bars.
- Shared components may include AppScaffold, AppHeader, ModeBadge, ConnectionStatus, DataFreshness, P&L/KPI cards, position cards, section headers, filters, loading skeletons, empty/error/offline/stale states, confirmation sheets, diagnostic rows, chart containers and paginated lists. Reuse only where behavior is truly shared; avoid one giant shared-widget file.
- Use consistent design tokens for typography, spacing, semantic colours, surfaces, borders/radii, icons, chart labels and number formatting. Prefer a calm, high-trust exchange style; avoid excessive glow, gradients, rainbow statuses, card nesting and heavy animation.
- Use tabular/readable numbers, consistent USDT/INR precision, signed P&L and time-zone/timeframe labels.
- Do not communicate status by colour alone. Respect text scaling, screen readers, contrast and touch-target size.
- Test narrow Android screens, long symbols and values, keyboard/safe areas, rotation if supported, large text, empty and large datasets, slow network, stale WebSocket, reconnect, scrolling, modal/back navigation and debug overflow.
- Loading/skeleton, populated, empty, stale, offline, reconnecting, partial and error states must be designed for each data-driven screen.
- Do not show placeholder figures as live. Do not claim screenshots/device validation if not actually performed.

## R8. Position cards, order previews, reports and India-specific handling

- Show realized net P&L separately from floating/open P&L. Show gross/net and fees/funding separately where supported.
- Display entry/current price, quantity/size, margin/leverage, open time, mode, stop/targets and target progress only when the source provides them.
- Ensure close/reduce previews use the same authoritative backend selection and calculation as the actual action.
- Handle double taps, partial fills, stale prices, rejected requests, timeout, duplicate requests and refresh from authoritative state.
- “Close All Profit/Loss” must preview exact affected positions/amounts and require confirmation. Do not implement/change it without approval if it affects live execution.
- Reports must specify date range, timezone, currency, account/mode, fees/funding inclusion, gross/net formula and data completeness.
- Verify INR conversion source/time and timezone/day-boundary calculations. If tax reporting exists, label estimates and rule version; do not hard-code an assumed Indian tax rate or claim professional tax advice.
- Do not double-count exchange fees or funding already included by the source.
- Separate live, paper, shadow, replay and hypothetical records and totals. Never mix paper results with live-account liabilities.

## R9. Settings and user control

Audit settings before changing defaults. Group supported settings into:
- Account/environment and clearly visible Live/Paper/Shadow/Replay mode.
- API connections with masked credentials and permissions explanation.
- Market-data symbols/timeframes, freshness, retention and rate-limit implications.
- Dashboard display density, card order, theme and chart defaults.
- Approved trading/risk settings, with clear statement of whether a setting affects live orders.
- Brain/research settings, separate from live strategy settings.
- Scalp Lab category, timeframe, paper/shadow and fee/slippage assumptions.
- AI Vision provider/model/usage/latency/cost where supported.
- Notifications/Telegram where supported.
- Diagnostics/privacy/log retention/export.
- Data/storage backup, retention and cache cleanup.
- Reports/tax configuration where supported.
- About/version/compatibility.
Every setting should state value, description, default, validation, persistence source, restart need, scope and whether safe to change with an open trade. Dangerous/live-affecting changes require confirmation and audit evidence. Never reveal secrets in UI.

## R10. Backend/WebSocket reliability and API contracts

- Inspect the existing FastAPI structure before refactoring. Map routes, schemas, services, repositories, background workers, scheduler lifecycle, startup/shutdown, WebSockets, polling and Flutter consumers.
- Define typed request/response contracts and consistent error structures. Validate inputs, units, timestamps and mode.
- Prevent slow AI or research work from blocking the event loop, scanner or execution path.
- Use timeouts, bounded concurrency, cancellation, backoff and idempotency.
- Reconnect/resync after WebSocket gaps; avoid duplicate listeners/subscriptions after navigation.
- Provide diagnostics with event age, last successful REST call, last WebSocket event, last candle, last scan, active subscriptions, reconnects, queue depth and errors where the source supports it.
- Redact secrets/private account data from logs and exported diagnostics.
- Keep current data path until a new one passes comparison tests; use a reversible migration/feature flag where appropriate.
- Verify correct requirements manifest, commands, Android/Flutter build compatibility and CI workflows from the repo rather than guessing.
- Avoid blind dependency upgrades, forced framework migration or new database/GraphQL layers without evidence.

## R11. Claude/NVIDIA selection and cost controls

- Claude API is the initial reasoning-provider candidate; verify the actual API billing model, model, rate limits and budget. A consumer subscription must not be assumed to include API credits.
- Keep provider access behind a backend interface, keys server-side, requests event-driven, concurrency bounded and outputs schema-validated.
- NVIDIA resources are candidates to study, not a mandatory stack. Evaluate the five original Skills catalogue links plus Nemotron, Quantitative Signal Discovery Agent, NeMo Agent Toolkit and RAG/blueprints links listed earlier in this file.
- For each candidate record: official capability, specific OWL1 use case, expected measurable benefit, hardware/hosted service, license, privacy/data handling, latency, cost, integration burden, benchmark, rollback and adopt/defer/reject decision.
- Prioritize only components that demonstrably help quantitative signal discovery/evaluation, retrieval of similar historical setups, tool orchestration or trustworthy evaluation.
- Do not add unrelated healthcare, robotics, Omniverse or physical-AI components; do not add GPU dependency just for fashion.
- Do not send private exchange/account data to an external provider without an approved minimal-data flow.
- Cache only when the market/time context makes cached output safe. Never call an LLM for every tick or put its latency on the critical execution path.

## R12. Test matrix and proof required for each delivery

For each requirement, state the test ID, test level, expected result, actual result and evidence. Use relevant coverage for:
- Existing live-rule characterization and regression tests.
- Mocked exchange client and proof no real order was submitted.
- API contract, validation, authentication/permissions and error paths.
- Candle order/gap/duplicate/timestamp/timezone checks.
- Storage retention, migration and restart/idempotency.
- Live/paper/shadow/replay separation.
- P&L/fees/funding reconciliation and rounding.
- AI schema validation, timeout, invalid response, quota failure, redaction and missing-data cases.
- Replay look-ahead leakage, cohort overlap and out-of-sample split.
- Flutter loading/empty/offline/stale/error/retry states, navigation and preview parity.
- WebSocket reconnect/resync and stale-data handling.
- Collector CPU/memory/disk/rate-limit impact.
- Flutter analyze/test/build, backend test commands and CI where environment supports them.
- Real-device performance/accessibility/screenshots only if actually run.

Never say “tested” when only reviewed. Never say “passed” when not run. Clearly separate source inspection, unit tests, integration tests, CI, Android build and physical-device validation.

## R13. Delivery completion report — required simple format

Every approved delivery must end with this exact concise report:
1. **Kya kiya:** changed features/files and reason.
2. **Kya test hua:** commands, real results and tests not run.
3. **Kya baaki hai:** blockers, missing evidence and known limitations.
4. **Live safety:** whether any protected trading path/setting changed; default must be no.
5. **Next step:** one dependency-ready task, why it comes next and its acceptance criteria.

## R14. Privacy and external sharing clarification

The project and strategy details are private owner material. Keep repository visibility and sharing unchanged. Do not publish or externally share the prompts, source, trading records, screenshots or reports. A prompt cannot by itself guarantee confidentiality: enforce privacy in repo permissions, secret handling, provider configuration, data minimization and logs. Ask before any external data transfer, public sharing, destructive data deletion or recurring paid service.

## R15. Final completeness check before calling README2 consolidated

Claude must confirm each source prompt has been inspected and mapped:
- `OWL1_Claude_Opus_Master_Prompt.txt`
- `OWL1_AI_Vision_NVIDIA_Frontend_Backend_Master_Prompt.txt`
- the long `OWL1_MASTER_PROMPT_v70plus` / Version 2 continuous execution and raw-data/research brief actually supplied by the owner.

Also inspect the actual README.md and current code. If the source files have overlapping wording, consolidate it but retain all unique requirements and constraints. If a prompt is only partially available, state exactly what was available. Do not claim all three have been fully reconciled until the requirement matrix proves it.

The owner wants one detailed document to give Claude so Claude can make the final repository-grounded plan. Do not make the owner read or manually merge the source prompts. Use this README2 as the consolidated brief; keep README.md as the live project status and historical record.
