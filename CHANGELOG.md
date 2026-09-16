# 📋 Changelog

All notable architectural decisions and evolutionary milestones of **Project Coach** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

---

## [2.1.0] - 2026-09-15
### Added
- **Dedicated Telegram Message Formatter (Mobile UX Redesign):** Built a mobile-native presentation layer optimized for narrow smartphone screens and smartwatches.
- **Compact Daily Nutrition Cards:** Clean bullet points for essential daily totals (Eaten, Protein intake, Daily status), eliminating cluttered vertical text blocks.
- **Contextual Real-Time Decision Loop:** The agent evaluates live voice queries by correlating workout scheduling (TRAINING DAY — PULL), multi-day meal memory, and real-time macronutrient balancing.

### Changed
- **Elimination of Raw Markdown (GFM):** Replaced broken pipe tables (|) with clean, vertical cards that render natively in Telegram.
- **Interface Decluttering:** Removed raw ### heading marks, horizontal rules (---), and leaked local filesystem URIs (ile:///).

---

## [2.0.0] - 2026-09-15
### Added
- **Bidirectional Mobile Interface via Telegram Bot API:** Implemented /telegram-webhook endpoint for real-time text and voice exchanges from smartwatches and mobile phones.
- **Local GPU Speech-to-Text (Faster-Whisper):** Integrated large-v3 model running in CUDA float16 mode, decoding voice notes locally without cloud audio API costs.
- **Idempotence & Auto-Purge (TelegramDeduplicator — ADR-014):** Handled a Wear OS Telegram client race condition that sent duplicate voice packets within milliseconds. Outlier duplicates are dropped via global ile_unique_id, and redundant chat bubbles are asynchronously removed using deleteMessage.
- **Multi-Key Failover Router (GeminiKeyPool — ADR-013):** Dynamic rotation of 3 independent Google AI Studio keys with zero-millisecond failover upon encountering HTTP 429 quota exhaustion.
- **Session Serialization (chat_lock):** Per-chat locking mechanism preventing concurrency race conditions across agent session files and guarding RPM thresholds.
- **Host Environment Resilience (Power SRE — ADR-015):** Windows power policy tuned for Modern Standby S0 (AC sleep disabled, Lenovo Conservation Mode battery threshold ~80%, ARSO automatic restart sign-on).

---

## [1.3.0] - 2026-09-12
### Added
- **Dynamic BMR Server Compensation (ADR-012):** Fixed an upstream sync discrepancy where Samsung Health exported only active calories to Google Health Connect, omitting basal metabolic rate (BMR).
- **Automated Mifflin-St Jeor Algorithm:** Backend dynamically computes BMR based on rolling bodyweight in SQLite when telemetry reads below 1,500 kcal, achieving 100% parity with native watch metrics.

---

## [1.2.0] - 2026-09-08
### Added
- **Store-and-Forward Offline Queue (MacroDroid):** Local queuing mechanism in Android to buffer voice notes and telemetry packets during network dropouts.
- **Delimited Cache Buffer:** Encodes buffered packets with | separators and flushes queue automatically once HTTPS tunnel reconnects.

---

## [1.0.0] - 2026-09-01
### Added
- **Windows Background Daemon:** Automated pythonw background execution via VBS startup script (start_serwera.vbs) without terminal windows.
- **Relational SQLite Database & ETL Pipeline (etl_parser.py):** Structured storage schema separating daily metrics (metryki_dzienne) from workout sessions (	reningi).
- **Input Validation (Sanity Check):** Outlier detection blocking abnormal data spikes (e.g., weigh-in typos) to preserve rolling average integrity.

---

## [0.5.0] - 2026-08-20
### Added
- **Event-Driven Push Architecture:** Replaced manual polling with passive HTTPS webhooks delivering real-time telemetry from mobile sensors.
- **Encrypted HTTPS Tunnel (Ngrok):** Secure public gateway to local Flask service without requiring static public IP or router port forwarding.
- **Raw Data Lake:** Persistent disk storage of all incoming JSON payloads before ETL processing.

---

## [0.1-alpha] - 2026-08-01
### Added
- **Proof of Concept (PoC):** Python scripts querying Google Fit and Strava REST APIs manually.
- **Flat CSV Storage:** Basic volume and cardio summaries tracked in local spreadsheets.
- **Friction Discovery:** Identified excessive friction in manual tracking, prompting the transition to an automated pipeline.
