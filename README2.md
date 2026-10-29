# README2 — OWL1 Ultra Upgrade Master Prompt
**Purpose:** This is the canonical audit-and-implementation brief for Claude or another coding agent working on `mehreenhusn-cmyk/Indian`, branch `main`.

**Owner expectation:** No compromise on correctness, safety, clarity, test evidence, architecture, data quality, or presentation. “Ultra” means dependable and polished—not adding technology for its own sake, not claiming unproven AI performance, and never silently changing live trading behavior.

**How to use:** First ask the coding agent to audit the current repository and this prompt. It must produce a file-by-file gap report and proposed execution plan before implementation. Then execute in small, reviewable deliveries in dependency order. Preserve this document as the working master brief; update its progress table with commit IDs, commands, results, and evidence.

**Repository:** https://github.com/mehreenhusn-cmyk/Indian  
**Primary stack:** Flutter frontend + Python/FastAPI backend + Binance market/trading integrations.  
**Language for explanations:** Plain English or simple Roman Hinglish. Keep developer reports understandable and concise, with details available below.

---

# PART A — MANDATORY FIRST MESSAGE TO THE CODING AGENT

You are the senior software architect, Python/FastAPI engineer, Flutter engineer, quantitative-research engineer, data-quality engineer, QA lead, and security reviewer for OWL1.

Do not start by rewriting the app. First inspect the actual repository at the current branch and identify what exists, what is broken, what is duplicated, what is unused, what is unsafe, what is already complete, and what is only documented. Do not infer that a feature works because a file or screen exists. Verify code paths, callers, configuration, tests, runtime logs and CI evidence.

Deliver these audit artifacts before modifying application code:

1. `README2_AUDIT.md` — repository map, current architecture, data flow, risks, broken behavior, test status and recommended plan.
2. `README2_FILE_MATRIX.md` — every in-scope file marked KEEP / MODIFY / ADD / DEPRECATE / DELETE-CANDIDATE, reason, dependencies, tests and risk. “DELETE-CANDIDATE” is not permission to delete.
3. `README2_TEST_BASELINE.md` — commands run, pass/fail/skipped results, environment, known blockers and captured evidence. Never label unrun tests as passed.
4. `README2_DECISIONS.md` — architecture decisions, alternatives considered, assumptions needing owner confirmation, and any feature explicitly deferred.
5. A short human-readable report: what is done, what is broken, what is next, and whether any live-trading behavior is at risk.

After audit, implement only low-risk, clearly authorized work. Before touching anything that can affect live orders, exits, stops, leverage, position sizing or trade routing, stop and present the exact proposed change and test plan for separate owner approval. Documentation, read-only audit tools, mock tests and isolated paper/research components may proceed without changing live behavior.

Do not hide failures, reduce tests to make CI green, invent market data, claim profitability, or delete code/data merely because a search suggests it is unused.

# PART B — PRODUCT GOAL AND USER REQUIREMENTS

OWL1 is intended to become a high-quality crypto trading and research app with an exchange-grade Flutter experience, dependable backend, trustworthy data, explainable AI Vision and disciplined testing. The objective is to reduce avoidable losses caused by weak/fake signals and choppy markets, improve evidence-based decision support, make actual realized results visible, and make the entire product easy to understand and operate.

The owner expects:
- A coherent architecture and a single understandable roadmap—not several conflicting lists.
- Backend work organized first, frontend work next, then integration and end-to-end verification. If a genuine dependency requires overlap, document the reason and keep the dependency explicit.
- Premium, professional, responsive, exchange-like UI—not just backend features or placeholder cards.
- AI Vision that studies the behavior of the user's indicators and historical outcomes, explains its reasoning with evidence, and initially assists/filters rather than blindly creating trades.
- Correct separation of live, paper, historical, retrospective/proxy, and research data.
- Data quality, traceability, testing and safe cleanup built into the project.
- Small, reviewable deliveries with exact file paths, tests, acceptance criteria and progress tracking.
- Honest statements about uncertainty, untested items and missing data.
- No compromise on safety just to make a feature appear complete.

## Current strategy context to verify against actual code

The owner has described the current entry as an EMA50 cross with candle close direction. The rule described so far is close crossing EMA50 for BUY/SELL; initial SL uses the signal candle low/high; TP1–TP4 are based on 200-candle standard-deviation bands. The owner believes the live bot may rely on one primary indicator and does not currently use TSI in its entry logic. Treat these as owner-reported behavior to verify, not as a substitute for code inspection.

Indicator concepts previously discussed:
- Special 13 and Special Master Pine scripts (inspect actual source if present; do not recreate missing formulas by guessing).
- EMA 10/30/50/100/200 and EMA50; EMA30/EMA50 cloud where applicable.
- SD bands using 200-period SMA and standard deviation, including ±1/±2/±3 bands.
- Z-score / Z-SMA 50 and a lower pane where price SD curves are reprojected meaningfully, not displayed as unrelated flat Z levels.
- TSI Fast 25/5/14 and Slow 25/13/13, subject to verification against source scripts.
- Trend/Structure, Momentum, Statistical and MTF/Liquidity score concepts (30/25/25/20) and grades A+ ≥90, A ≥80, B ≥70, under 60 no-trade were discussed as candidate rubric. They are not automatically production rules: audit, backtest and document them before enabling.
- A price move upward while a lower-pane Z-score/TSI or momentum signal weakens may indicate divergence or reduced confidence. AI should measure and explain outcomes rather than hardcode a universal rule that always closes a trade.

The desired learning behavior is to discover where signals fail, how outcomes differ by market regime, when no-trade is better, how fees change expectancy, and whether exits/profit booking improve realized outcomes. Open PnL is not the same as realized/withdrawable profit. Report both clearly.

## Non-negotiable live-trading protection

Treat all live-trading paths as protected:
- Do not change live entry/exit logic, order placement, close/partial-close behavior, SL/TP calculations, leverage, position sizing, margin mode, symbol selection, trade frequency, execution routing, retry behavior or protection settings without separate explicit owner approval.
- Do not enable an experimental strategy or AI proposal in live mode.
- Do not silently alter defaults, feature flags, environment variables or settings that could change execution.
- Do not run real-order tests. Use mocks, test doubles, recorded fixtures or paper/sandbox endpoints as appropriate.
- If a safety issue is discovered, document severity and propose a minimal fix; do not conceal it or bundle a behavior-changing fix into an unrelated UI change.
- AI Vision is advisory/shadow/paper-first. It cannot place, amend or close live orders in this project phase.
- A UI preview must never imply that an action will execute differently from what the backend will actually do. Resolve preview/execution mismatches with a documented, approved plan.
- Maintain an explicit kill switch / disabled-by-default state for experimental execution-related features.

# PART C — REQUIRED ARCHITECTURE AND DATA FLOW

Claude must draw the current architecture from source code, then propose a target architecture with explicit boundaries. Do not add microservices or new infrastructure without a demonstrated need.

## Preferred high-level flow

1. **Market data ingestion:** exchange/public source → WebSocket or REST collector → validation/normalization → timestamped raw/normalized records.
2. **Indicator computation:** validated OHLCV/candles → deterministic indicator engine → versioned feature snapshot (EMA, SD bands, Z-score, TSI, volume/volatility, regime, missing-data flags).
3. **Existing strategy path:** current strategy engine remains isolated and unchanged during the passive-learning phase → existing bot routing. Preserve and test the actual live/paper separation.
4. **Shadow/AI Vision path:** market/indicator snapshot + strategy signal + market regime + prior labeled outcomes → deterministic filters/research models → optional LLM explanation layer → evidence-backed recommendation. This path is asynchronous and must not block the live bot's critical path.
5. **Trade and P&L accounting:** exchange fills/orders/fees/funding where available → reconciled trade ledger → realized P&L, unrealized P&L, fees, slippage, funding and paper/live separation.
6. **Research and evaluation:** immutable snapshots + signal decisions + outcome labels → time-aware cohorting → backtest/walk-forward evaluation → comparison report.
7. **API layer:** typed, versioned FastAPI endpoints with validation, pagination, stable error contracts, authentication/authorization where required, redaction and rate limits.
8. **Flutter client:** API/WebSocket state → repository/data layer → domain models/state management → reusable UI components/screens. Avoid putting trading rules in widgets.
9. **Observability:** structured logs, request/correlation IDs, health metrics, collector freshness, data gaps, AI/model version, decision provenance, test evidence and safe diagnostics.

## Required architecture deliverables

- Current and target architecture diagrams (Mermaid is acceptable).
- Data-flow diagram from exchange input through indicator calculation, AI Vision, database/API and Flutter presentation.
- Entity/data dictionary with timestamp/timezone, symbol, timeframe, source, mode (live/paper/historical/proxy), schema version, quality status and provenance.
- API contract list with request/response examples and error behavior.
- Database ownership map: which database/table is authoritative for each data type; read/write owners; retention; migration and backup strategy.
- Dependency map and startup/shutdown lifecycle.
- Threat model for secrets, live endpoints, dangerous commands, malformed data, replay/duplicate events and unauthorized mode changes.
- Performance budgets and measurement methodology. Set numeric targets only after measuring current baseline or explicitly label them as proposed targets.

# PART D — DATA QUALITY, STORAGE AND SAFE CLEANUP

Data quality is a core feature, not a later cleanup. Never delete data because it looks old, odd, duplicated or unused without establishing its role and retention obligations.

## Inventory first
- Inventory every database, table, schema, file-based store, cache, log, generated artifact, model file, dataset and migration.
- Identify owner, creation path, last access if reliably available, callers/readers/writers, retention requirement, size and mode.
- Detect duplicate datasets, inconsistent timestamps, timezone mistakes, invalid OHLCV, impossible high/low relationships, missing candles, duplicate candles, stale data, NaNs/infinities, schema drift and conflicting sources.
- Label records: trusted official/source data, validated derived data, historical proxy, retrospective approximation, paper, live, synthetic fixture, corrupted/quarantined, unknown provenance.
- Never mix paper/live P&L or actual exchange observations with retrospective/proxy data in one unlabelled metric.
- Do not train/evaluate on data that leaks future information into past decisions.
- Use explicit quality flags and quarantine suspect rows; keep enough evidence to reproduce the diagnosis.

## Deletion protocol
Before deleting or overwriting any database, table, file, row set or cache:
1. Prove the item is unused with static references plus runtime evidence where possible.
2. Check migrations, backups, scheduled jobs, dynamic imports, configuration references, user exports and recovery needs.
3. Produce a dry-run report listing exact targets, counts, sizes and reasons.
4. Confirm whether the item is user data, evidence, training data, source code, generated output or disposable cache.
5. Back up or export recoverable data and verify the backup.
6. Prefer archive/quarantine/deprecation first. Use a reversible migration where possible.
7. Require owner approval for destructive removal of user data, trading history, databases or ambiguous artifacts.
8. Add tests proving current functionality no longer depends on removed items.
9. Record what was removed, why, when, by which commit, and how recovery works.

Do not use broad `rm -rf`, wildcard deletion, database recreation or destructive migrations as a cleanup shortcut. Do not commit secrets, API keys, Telegram credentials, account identifiers or private user data.

# PART E — AI VISION / SMART BRAIN RESEARCH SPECIFICATION

## Intended role
AI Vision is an evidence-based research assistant and signal-quality analyst, not an autonomous live trader. It should observe existing strategy signals, learn from labeled outcomes, explain candidate filters, compare alternatives and present uncertainty. It should not pretend to learn reliably from a few wins or a single market regime.

## Phased operation
**Phase 0 — Audit:** inspect existing `ai_ind_features.py`, shadow-lab logging, TSI/Z/SD/reversal-arrow features, Vision screens, strategy doctor, filter lab, reports, and any existing model/provider integrations. Reuse verified components rather than creating parallel systems.

**Phase 1 — Passive shadow logging:** log the existing bot's unmodified decisions and all features needed to reconstruct them. Do not alter order routing or block the bot. Capture signal timestamp, symbol, timeframe, side, signal candle, entry reference, stop/targets as observed, feature values, regime, data quality, strategy/version, fees assumption and later outcome labels. Avoid storing secrets or unnecessary personal information.

**Phase 2 — Data readiness:** require enough clean, time-aligned candles and outcomes; report coverage, missingness, duplicate rate, candle gaps, class imbalance and label quality. If data is insufficient, say “not enough evidence” instead of generating confident grades.

**Phase 3 — Baseline and cohorts:** measure existing strategy without AI, with actual available fees and slippage assumptions. Segment by symbol, timeframe, market regime, session/time, volatility, trend/chop, indicator configuration and setup family. Keep authentic real-time observations separate from retrospective proxies.

**Phase 4 — Candidate filters:** evaluate TSI, Z-score, SD-band shape, EMA structure, reversal arrows, divergence, momentum decay, volume/liquidity and MTF agreement as candidate features. Compare each independently and in combinations. Avoid leakage and overfitting; use chronological train/validation/test splits and walk-forward evaluation. Keep an untouched out-of-sample window.

**Phase 5 — A/B and paper-only:** compare baseline bot vs candidate filters under matched periods and assumptions. Maintain a paper-only comparison board. Do not enable candidate execution in live mode. Require owner approval before any future change to live strategy behavior.

**Phase 6 — Explanation/UI:** each recommendation shows evidence, confidence/calibration, missing data, model/rule version, sample count, applicable regime, expected limitations and a concise reason. Clearly distinguish observed facts from model interpretation.

## Required outcome metrics
Report at minimum:
- Number of eligible signals, taken/skipped, wins/losses/breakeven, win rate and sample size.
- Gross P&L, fees, funding, slippage assumption, net realized P&L, average win/loss, expectancy per trade, profit factor and drawdown.
- MAE/MFE where data permits, stop/target hit rates, time-in-trade and missed-opportunity trade-off.
- Results by regime, symbol, timeframe and setup cohort.
- Baseline vs candidate delta with uncertainty and out-of-sample results.
- Data quality and coverage beside every metric.
- Open/unrealized P&L separately from realized P&L.

Never optimize only for win rate. A filter that raises win rate while lowering net expectancy or increasing drawdown is not automatically better. Do not invent confidence percentages. Calibrate scores on held-out data.

## AI/provider architecture
- Keep the LLM out of the latency-sensitive market-data and order-execution path.
- Use deterministic Python code for indicator math, feature validation, metric calculation, risk checks and eligibility gates.
- Use the LLM for summarizing evidence, explaining research findings and answering questions from approved/traceable app data.
- If Claude API is used, isolate it behind a provider interface, configurable model/timeout/budget, retry/circuit breaker, redacted inputs and explicit logging of provider/model/version. Do not hardcode keys.
- LLM output must be schema-validated and treated as untrusted text; it cannot override deterministic safety rules.
- Cache repeatable analyses, enforce token/cost limits and degrade gracefully when a provider is unavailable.
- RAG/retrieval must cite the exact dataset/report/source used and return “not found” rather than fabricate an answer.
- NVIDIA Nemotron or other models are optional experiments, not mandatory replacements for Claude. Compare cost, latency, quality, hardware, license, privacy and operational burden before adopting them.

## Candidate safety controls to validate
The owner previously discussed a 100 USDT paper account, daily target lock around +30 USDT and daily loss limit around -10 USDT, adjustable. Treat these as configurable paper-test proposals, not as verified current production settings and never silently apply them to live trading. Validate reset timezone, fees, partial fills, duplicate events, restarts and stale account state. UI must show whether a limit is simulated, paper-only or live-enforced.

# PART F — NVIDIA / AI RESEARCH REFERENCES

The exact five URLs shared in an earlier chat are not available in the currently retrievable context. Do not claim these are the exact original five. The following are verified official NVIDIA references relevant to the discussed themes; compare them with the owner's original group links if those are supplied later.

1. **NVIDIA NeMo Agent Toolkit — agent integration, profiling and evaluation**
   https://developer.nvidia.com/blog/how-to-build-custom-ai-agents-with-nvidia-nemo-agent-toolkit-open-source-library/
   Potential use: profile agent workflows, instrument tool calls, evaluate latency/cost and keep integrations modular. Do not add a multi-agent framework unless it solves a measured need.

2. **NVIDIA Nemotron model catalog**
   https://build.nvidia.com/models
   Potential use: research optional model endpoints for structured explanations, tool use or multimodal/document analysis. Check current model availability, endpoint limits, pricing, license, data handling and latency before implementation.

3. **NVIDIA Agentic RAG learning path / NeMo Retriever**
   https://developer.nvidia.com/topics/ai/agentic-ai-learning-path/how-to-build-agentic-ai-rag
   Potential use: retrieve approved research reports, indicator documentation and data dictionary entries with traceable source citations. RAG is not a substitute for clean structured trading data.

4. **NVIDIA Nemotron document processing / multimodal RAG**
   https://developer.nvidia.com/blog/how-to-build-a-document-processing-pipeline-for-rag-with-nemotron/
   Potential use: only if the app needs to parse indicator documentation, PDFs, reports, tables or chart images. It is not required for core OHLCV processing.

5. **NVIDIA cuDF GPU-accelerated dataframes**
   https://developer.nvidia.com/topics/ai/data-science/cuda-x-data-science-libraries/cudf
   Potential use: consider only if profiling shows large research/backtest data processing is a bottleneck and a suitable NVIDIA GPU environment exists. Do not add GPU dependencies to the ordinary phone/backend path by default.

6. **NVIDIA NeMo RL / agentic evaluation research**
   https://developer.nvidia.com/blog/mastering-agentic-techniques-ai-agent-reinforcement-learning
   Potential use: future controlled experiments if there is a well-defined environment, reward, reproducible simulator and enough data. Not a first-step solution for reducing fake trading signals.

7. **NVIDIA Nemotron model card example**
   https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b/modelcard
   Potential use: inspect model capabilities, hardware requirements and license. A very large model may be impractical for this app; do not assume it can run on the user's laptop or Android phone.

Research rule: these links are starting points, not automatic adoption decisions. For each proposed technology, provide a one-page decision: problem solved, alternatives, integration location, measured benefit, cost, privacy/security impact, deployment needs, test plan and rollback. Keep the existing Flutter UI unless an evidence-based reason justifies a targeted change. Avoid replacing Flutter with React Native/WebView or introducing multiple frontend frameworks.

# PART G — PREMIUM FRONTEND / PRESENTATION REQUIREMENTS

A high-end UI is part of the product acceptance criteria, not optional decoration. Audit existing Flutter screens and widgets before redesigning.

## Visual system
- Create a consistent design system: color tokens, semantic status colors, typography scale, spacing, radii, elevations, icon rules, light/dark theme if supported, responsive breakpoints and reusable components.
- Premium exchange-style hierarchy: readable prices, clear P&L, clean candlesticks, disciplined information density, clear primary/secondary actions and restrained visual effects.
- Avoid clutter, oversized gradients, excessive borders, random colors, inconsistent paddings and decorative charts that do not represent real data.
- Show currency, units, symbol, timeframe, timestamp and mode wherever needed.
- Positive/negative P&L and risk status must be unambiguous, accessible and not color-only.
- Provide skeleton/loading, empty, error, offline, stale-data, partial-data, reconnecting and permission-denied states. Never show fake placeholder numbers as live data.
- Support small Android screens, text scaling, safe areas, keyboard visibility, orientation where relevant and accessibility labels.
- Add tasteful motion/micro-interactions only where they clarify state. Avoid animations that delay trading-related information.
- Use Flutter/Impeller capabilities appropriately; measure rendering before considering native Kotlin plugins. Use native code selectively only when a demonstrated requirement cannot be met cleanly in Flutter.

## Screens and components to audit
- Dashboard: overall health, mode, realized/unrealized P&L, fees, data freshness, open positions and clear alerts.
- Positions: symbol, side, quantity, entry/current price, stop/targets, realized/unrealized P&L, fees and safe action previews.
- History: reliable trade history, filters, pagination, clear distinction between actual fills and simulated records.
- Charts: candles, EMA50, SD bands, TSI/Z-score panes and crosshair/labels; exact calculations must match validated indicator sources.
- AI Vision: signal quality evidence, regime, reasons to take/skip/watch, confidence limitations, sample size and baseline-vs-filter results.
- Radar / cohorts: today, yesterday, 2/3/7-day windows as supported by real data; separate live-observed and retrospective proxy cohorts.
- Data Explorer / Knowledge Ledger: source, provenance, data health, experiment/model version and reproducibility.
- Diagnostics: API, database, collector freshness, websocket state, errors, recent history and non-sensitive health details.
- Settings: grouped and named settings, safe descriptions, current mode, paper/live separation, fees and INR/tax-reporting options where relevant.
- Brain Skip card and Strategy Doctor: present only when supported by backend evidence; no fake green statuses.
- Report/export flows: clear time range, timezone, currency, mode and included/excluded data.

## Frontend engineering
- Separate widgets from domain rules; use typed models, repository/API layer, clear state management and centralized error handling.
- WebSocket updates must be incremental and resilient to reconnects; do not rebuild the entire app on every tick.
- Cache only with explicit freshness rules and show stale status.
- Prevent duplicate requests, memory leaks, chart jank, unbounded lists and unnecessary polling.
- Add widget tests for visual states, interaction tests for important flows and integration tests for critical API contracts.
- Capture before/after screenshots where tooling permits and include a screen checklist in the final report.

# PART H — BACKEND ENGINEERING AND SECURITY

- Keep FastAPI endpoints typed, validated, versioned where appropriate, and consistent in response/error shape.
- Keep public market-data collectors separate from authenticated trading/account clients.
- Isolate import-time side effects. Importing modules for tests must not start collectors, connect to exchanges, send Telegram messages or place orders.
- Enforce secret redaction by default and fail closed if safe redaction cannot be guaranteed.
- Keep environment/configuration validation explicit; never log API secrets or authentication headers.
- Use timeouts, bounded retries, backoff, rate-limit handling and circuit breakers for external services.
- Make collectors idempotent; handle duplicate/out-of-order messages, reconnects, gaps and stale snapshots.
- Store timestamps in UTC internally and render in local timezone (India/IST when selected). Make day-boundary logic explicit.
- Add migrations rather than silently recreating tables; support safe startup/shutdown and recoverable storage.
- Separate market-data DB from trading/account data where architecture requires it. Do not mix research proxies with source-of-truth exchange records.
- Protect health endpoints from exposing sensitive details. Provide detailed diagnostics only to authorized contexts.
- Test Telegram/API integrations with mocks. Credentials are read from environment/settings at send time; never bake credentials into source.
- Keep requirements/dependencies minimal and pinned/managed according to existing project conventions. Do not install NVIDIA GPU libraries in the normal app environment without measured justification.

# PART I — CANONICAL SEQUENTIAL EXECUTION PLAN

Use this order as the planning backbone. The existing root README contains legacy section details, file paths and historical IDs; map each legacy item to this canonical sequence rather than deleting it. Verify every path against the actual repository. The rough line estimates below are planning estimates from the existing roadmap, not promises or measurements.

## Phase 0 — Audit and baseline (before implementation)
- Confirm branch, commit, tree layout, runtime entrypoints and CI workflows.
- Inventory every backend module, Flutter screen/widget, database, configuration file, test, migration, background task and generated artifact.
- Run existing safe tests and record baseline failures. Never run real orders.
- Map all legacy labels (A–F, U1–U5, NEXT-1–10, B3/G1/G2, H1, S0–S19, 6a–6j) to one canonical Part ID.
- Produce the five audit artifacts in Part A.
- Verify all NVIDIA links and the actual earlier user-provided links if available; distinguish verified source from inference.
- Exit criteria: complete file matrix, dependency graph, risk list, test baseline and proposed plan approved before risky implementation.

## Phase 1 — Backend safety and observability foundations
**Part 1: Read-only database safety (roughly 380 lines).** Inspect safe database openers, WAL/SHM handling, symlink/path safety. Add focused tests. Do not modify data during inventory.
**Part 2: Fail-closed redaction (roughly 270 lines).** Add/verify central redaction and tests for API keys, tokens, headers, Telegram credentials, URLs and nested objects.
**Part 3: Database inventory/evidence report (roughly 350 lines).** Build a read-only inventory CLI with evidence labels and a report. Run it once against the actual repo/data environment and save a redacted report.
**Part 4: Protected strategy behavior tests (roughly 450 lines).** Characterize current rules and paper/live routing. Test existing behavior; do not change it.
**Part 5: Mock-only exchange client/import isolation/CI guard (roughly 425 lines).** Ensure imports do not perform network/trading side effects; mock all clients; add an informational CI job and safe tests.
**Exit gate:** safety tests pass or remaining failures are explicitly documented; no real order executed; owner sees a protected-path report.

## Phase 2 — Backend market data and accounting
**Part 6: Public market collectors and separate market store (roughly 1,820 lines; blocked on inventory).** Collect public Binance data, snapshots, official cohorts and 3m/5m candles; define gap handling, idempotency and storage cap. Do not collect private account data through public collectors.
**Part 7: Live/Paper P&L reconciliation (roughly 990 lines).** Separate realized/unrealized, fees, funding, fills and paper/live records. Compare internal records with source records where accessible; flag unreconciled differences rather than hiding them.
**Part 8: Diagnostics health API (roughly 1,260 lines).** Expose collector freshness, database status, API health, errors and history with safe redaction.
**Part 17: Settings taxonomy, fees and tax reporting (roughly 1,060 lines).** Audit configuration categories and provide transparent fees/INR/tax reports where data supports them. India-specific tax outputs must be clearly labeled as estimates/reports, not legal or tax advice.
**Backend data readiness gate:** collector tests, gap/duplicate tests, storage cap, timezone tests, P&L reconciliation fixtures and data-quality report all pass.

## Phase 3 — Backend AI Vision and research evidence
**Part 13: Data summaries, Data Explorer API and evidence-based AI Vision (roughly 1,530 lines).** Provide validated feature snapshots, coverage and summaries; explanations must cite underlying data.
**Part 14: Knowledge Ledger/provenance (roughly 1,230 lines).** Track source, feature/model version, run parameters, experiment results and report lineage.
**Part 15: Scalp Lab framework + first two research categories (roughly 2,560 lines).** Historical/paper research only; wait for 3–4 weeks of usable candle data before drawing conclusions.
**Part 16: Stop-wick → continuation → re-entry study (roughly 960 lines).** Study as a hypothesis; do not turn into an automatic strategy.
**Part 19: Brain-assisted paper A/B (roughly 350 lines).** Wait for P&L and provenance readiness; compare baseline and candidate filters on matched data.
**Part 21: Brain-to-trading proposals B3/G1/G2 (roughly 270 lines).** Research/proposal only until evidence and separate owner authorization. No live behavior change.
**Exit gate:** no look-ahead leakage, clear cohort provenance, reproducible runs, enough data or explicit “insufficient evidence,” paper-only operation.

## Phase 4 — Frontend design system and screens
**Part 9: Premium Flutter design system/navigation/reusable states (roughly 1,200 lines).** Build tokens, components, routing and consistent loading/empty/error/offline/stale states.
**Part 10: Positions and safe close preview (roughly 670 lines).** Improve clarity and ensure preview exactly matches backend behavior. Any change to actual live close path requires separate approval.
**Part 11: Chart audit (roughly 520 lines).** Verify EMA50, SD and Special Master TSI/Z-score against original source. Do not approximate missing formulas.
**Part 20: Brain Skip card (roughly 130 lines).** Use existing backend key if verified; show evidence and status honestly.
**Part 8 frontend counterpart:** diagnostics health strip/detail/history using the backend contract.
**Part 13 frontend counterpart:** Data Explorer and Vision evidence presentation.
**Part 17 frontend counterpart:** grouped settings, fees and report UI.
**Frontend gate:** all required screens have realistic states; no fake live data; widget tests and screenshots/evidence captured; accessibility and performance checks documented.

## Phase 5 — Radar, integration and acceptance
**Part 12: Radar cohorts (roughly 1,610 lines; depends on collector data).** Support today/yesterday/2/3/7-day views as available; distinguish authentic observations from retrospective proxies.
**Part 18: Final integration/performance/accessibility/acceptance/README close-out (roughly 500 lines).** Validate contracts end-to-end, mobile screens, reconnects, database migration, logs, permissions, performance and accessibility.
**Part 22: Dual Bot H1 auto-start + TP-LAST proposal.** Separate scope/estimate and risk review. TP-LAST affects exits; do not implement or enable without separate explicit approval.
**Part 23: E4/E5/E6 and Brain v2 backlog.** Not planned until separately scoped and approved.
**Part 24: Backend cleanup review.** Produce safe cleanup candidates, evidence and rollback plan. No unapproved destructive deletion.
**Final gate:** complete acceptance checklist, test evidence, known limitations, rollback notes, build/deployment instructions and plain-language handover.

### Dependency rules
- Market-data research (Parts 12, 15, 16, 19, 21) cannot claim reliable results until the required clean data and labels exist.
- Frontend screens can be prototyped against documented mock contracts, but must not be marked integrated until real API contract tests pass.
- Part 3 inventory must precede any database cleanup or destructive migration.
- Part 4/5 tests protect current trading behavior before research/architecture changes.
- Part 7 accounting and Part 14 provenance are prerequisites for credible Brain A/B comparisons.
- Part 18 is the final integration gate, not a substitute for tests during earlier parts.

# PART J — TESTING STANDARD (MANDATORY FOR EVERY DELIVERY)

For each task, specify:
1. Goal and observed problem.
2. Exact files added/modified/deprecated.
3. Risk level and whether live behavior could be affected.
4. Unit tests and expected assertions.
5. Integration/contract tests.
6. Regression tests for adjacent functionality.
7. Security/data-quality tests where relevant.
8. Manual Android/Flutter check if UI is affected.
9. Exact command executed and exit code.
10. Actual result: PASS / FAIL / BLOCKED / NOT RUN.
11. Evidence path or CI URL/commit.
12. Known limitations and rollback instructions.

Test categories:
- Python unit tests; API tests; schema/contract tests; database migration tests; collector fixture tests; duplicate/out-of-order/gap/stale-data tests; timezone/day-boundary tests; redaction/security tests; mock exchange client tests; import-side-effect tests.
- Flutter unit/widget tests; repository/state tests; API error/empty/offline/reconnect tests; chart rendering and data-label checks; accessibility/text scaling checks; responsive layout checks; important user-flow integration tests.
- End-to-end tests with paper/mock accounts only. No real order submission.
- Performance profiling for API latency, data processing, WebSocket update rates, Flutter frame stability, memory growth and large lists.
- CI must not misrepresent skipped/optional tests as passes. A baseline failure must be reported even if unrelated.

Never say “all tests pass” unless the recorded commands actually ran and passed. Distinguish code review, static analysis, unit tests, device tests and production verification.

# PART K — PERFORMANCE, RELIABILITY AND ACCESSIBILITY

Measure before optimizing. Establish baselines for:
- API latency and error rates.
- Collector lag, reconnect time, missed/duplicate candles and storage growth.
- Feature/indicator computation time and AI explanation latency.
- WebSocket update-to-render latency and UI frame jank.
- Startup time, memory use and long-list/chart behavior.
- Provider spend, timeouts, cache hit rate and graceful fallback.
- Screen-reader labels, contrast, text scaling, touch targets and focus/navigation.

Do not introduce GPU/cuDF, a second frontend framework, multiple agents, vector databases, message brokers or additional services merely because they sound advanced. Add them only when profiling and a written decision show measurable value and operational feasibility.

# PART L — SECURITY, PRIVACY AND OPERATIONS

- Never commit secrets or print them in reports. Redact before logs, AI prompts, error messages and exported artifacts.
- Use least privilege; separate public market data from private account operations.
- Ensure the UI cannot switch live mode or relax safety controls through an unvalidated client-only setting.
- Validate all API inputs and LLM outputs. Do not execute code or commands derived from model output.
- Use bounded network timeouts and retries; avoid retry storms.
- Maintain data backups and verify restore procedures for important stores.
- Provide clear health status and useful diagnostics without exposing secrets.
- Document environment variables and safe setup. Avoid requesting or printing the user's credentials in chat.
- Check licenses and data-provider terms before adopting external models or datasets.
- If a dependency has a known vulnerability or is unmaintained, document severity, reachability and a tested upgrade plan.

# PART M — INTEGRITY RULES FOR IMPLEMENTATION

1. Inspect before editing; map actual code before proposing a replacement.
2. Do not rewrite working modules simply for style.
3. Do not create duplicate sources of truth.
4. Do not fabricate data, test output, screenshots, benchmarks, source URLs or completed status.
5. Do not delete code, data or historical roadmap detail without evidence and authorization.
6. Keep changes small and traceable; one logical change per commit.
7. Keep existing repository root structure; do not add a nested `Indian-main/` folder.
8. Do not overwrite unrelated owner changes or reset the branch destructively.
9. Keep the canonical roadmap and old historical IDs cross-referenced until migration is verified.
10. When a requirement is ambiguous, record the ambiguity and safest default; ask the owner only when the decision affects product behavior, data deletion, costs, privacy or live trading.
11. Every UI value must have a traceable source and mode; no fake live metrics.
12. A TODO or placeholder is not a completed feature.
13. “Ultra” means quality and evidence, not maximum complexity.
14. If a required external tool/service is unavailable, document the limitation and provide a practical fallback.
15. Keep all experimental trading changes paper-only until explicitly approved.

# PART N — DELIVERY AND PROGRESS REPORT FORMAT

After each delivery, update the progress table below and provide a concise report in this format:

- **Kya kiya / Completed:** exact behavior, files and commit.
- **Kya test hua / Tests:** exact commands and real results.
- **Kya baaki hai / Remaining:** blockers, unrun tests and missing evidence.
- **Next:** the next dependency-ready task.
- **Safety:** explicitly state whether live trading paths/configuration were untouched.
- **Data:** state whether any data was added, migrated, archived or deleted.
- **UI:** if applicable, list screens/states checked and evidence.
- **Rollback:** how to revert safely.

Never report progress by counting lines alone. Count accepted requirements and verified tests.

## Initial progress table (must be refreshed after audit)

| Area | Status before audit | Required evidence |
|---|---|---|
| Current architecture | Unknown until re-inspected | Architecture/data-flow diagrams and actual entrypoints |
| Existing backend tests | Unknown until run | Command log and pass/fail/blockers |
| Existing Flutter tests/build | Unknown until run | Command log, build result and environment |
| Data/database quality | Inventory pending verification | Read-only inventory, provenance and gap report |
| AI Vision readiness | Existing pieces reported; behavior unverified | Feature map, clean-label coverage and shadow baseline |
| NVIDIA integration | Research references only; no adoption assumed | Decision record for each proposed component |
| Premium presentation | Requirements documented; screen quality unverified | Screen-by-screen audit, tests and screenshots |
| Live-trading safety | Protected; current paths must be characterized | Routing tests and explicit no-real-order evidence |
| Cleanup candidates | No deletions authorized | Dry-run report, dependency proof and rollback plan |

# PART O — ACCEPTANCE CHECKLIST

Do not mark the project complete until the applicable items are evidenced:

## Architecture
- [ ] Current and target architecture diagrams exist and match actual code.
- [ ] Backend/frontend/data ownership boundaries are documented.
- [ ] API and database contracts have tests.
- [ ] No unexplained duplicate source of truth.
- [ ] Failure/reconnect/startup/shutdown behavior is documented.

## Safety and security
- [ ] Live-trading behavior was characterized and protected with tests.
- [ ] No real orders were sent by test runs.
- [ ] Experimental AI paths are isolated and disabled for live execution.
- [ ] Secrets are redacted and never committed.
- [ ] Destructive data/code cleanup follows the deletion protocol.

## Data and research
- [ ] Records include source, timestamp, mode and quality/provenance labels.
- [ ] Gaps, duplicates, stale records and invalid candles are detected.
- [ ] Live, paper, historical and proxy metrics are separate.
- [ ] P&L separates realized/unrealized, fees, funding and slippage assumptions.
- [ ] AI comparisons are time-aware, leakage-resistant and reproducible.
- [ ] Insufficient data produces an explicit uncertainty state.

## AI Vision
- [ ] Passive/shadow behavior is verified.
- [ ] Baseline and candidate comparisons use matched data and costs.
- [ ] Results include net expectancy/drawdown, not only win rate.
- [ ] Every explanation has evidence/provenance and model/rule version.
- [ ] Provider failure does not affect bot critical path.
- [ ] No AI-generated recommendation can directly execute live orders.

## Flutter presentation
- [ ] Consistent design system and navigation.
- [ ] Dashboard, positions, history, charts, Vision, diagnostics and settings audited.
- [ ] Loading, empty, error, offline, stale and partial-data states implemented.
- [ ] UI displays correct mode, units, timestamps and data provenance.
- [ ] Accessibility and responsive layout checked.
- [ ] Real-device/screenshot evidence recorded where available.
- [ ] UI previews agree with backend behavior.

## Delivery quality
- [ ] Each change has exact files, tests, result and rollback.
- [ ] CI status verified for the actual commit.
- [ ] Known failures and limitations are disclosed.
- [ ] README and roadmap statuses reflect evidence, not intention.
- [ ] Final handover states what is done, what remains and the next safe step.

# PART P — FINAL INSTRUCTION TO CLAUDE

Start with **AUDIT ONLY**. Inspect the repository, current README/master notes, tests, workflows, databases, runtime entrypoints, existing AI Vision modules and Flutter screens. Verify the official NVIDIA references above and distinguish them from the exact original links, which may not be present in the current context.

Then produce the audit artifacts and a reconciled file-by-file plan. Do not begin a broad rewrite. Preserve historical work, keep the root structure correct, and do not modify live-trading behavior. After the audit, implement the smallest safe first delivery, report actual test evidence, and wait for owner approval before any change that can affect live orders, exits, risk, destructive data cleanup or new recurring costs.

**The owner’s priority is a dependable, evidence-backed, premium OWL1 app—not a flashy demo.**
