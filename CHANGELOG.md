# 📋 Changelog

All notable architectural decisions and evolutionary milestones of **Project Coach** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

---

## [2.5.0] - 2026-11-23
### Added
- **Cloudflare Tunnels Ingress & Perimeter Hardening:** Deployed containerized `cloudflared` tunnel connector (`coach-tunnel`) establishing outbound QUIC tunnels to Cloudflare edge with zero open inbound ports and complete elimination of public IP exposure.
- **Telegram Webhook Secret Token Authentication:** Enforced cryptographic header validation (`X-Telegram-Bot-Api-Secret-Token`) for incoming Telegram updates, rejecting unauthorized external POST traffic (HTTP 403).
- **Multi-Service Compose Orchestration:** Extended stack with `coach-redis` (`redis:7-alpine`) for asynchronous queue offloading alongside `project-coach-cpu` and `coach-tunnel`.
- **Enterprise Inverted Whitelist:** Converted `.dockerignore` to the strict Zero-Trust Default Deny whitelist standard, slashing build context transfer to 301 bytes and completely shielding the Debian container from host secrets, test suites, and Windows binaries.
- **Production Documentation Shielding:** Suppressed public Swagger UI (`/docs`), ReDoc (`/redoc`), and `openapi.json` schemas on production environments.
- **Retina 2x C4 Architecture Diagrams:** Updated English and Polish high-resolution architecture schematics (`architecture.png`, `architecture.pl.png`) reflecting Cloudflare Tunnels, Redis task queue, and Docker multi-service isolation.

### Changed
- **Host Port Loopback Binding:** Bound FastAPI internal host ports strictly to the loopback interface, eliminating bypass exposure on the local network.

### Removed
- **Legacy Host Stack Teardown:** Terminated legacy host processes (`ngrok.exe` and background `pythonw.exe`), leaving the containerized stack as the sole master of the SQLite WAL database.
- **Legacy Server Retirement:** Archived original Flask implementation to `docs/_archiwum/` and replaced `server/server.py` with a lightweight bridge preserving 100% test suite compatibility (35/35 passing).

---

## [2.4.0] - 2026-09-16
### Added
- **Docker Dual-Profile Containerization:** Implemented multi-stage Docker build (`python:3.13-slim-bookworm`) and Docker Compose profiles:
  - `cpu`: Lightweight container (~350 MB) for standard webhooks and cloud Gemini LLM inference.
  - `gpu`: Hardware-accelerated container (~1.9 GB) leveraging NVIDIA Container Toolkit passthrough for local Faster-Whisper (`large-v3`, CUDA float16) speech transcription.
- **SQLite WAL Volume Mount Security:** Host Bind Mount (`../kalistenika:/kalistenika`) ensuring atomic shared memory transactions (`.db-wal`, `.db-shm`) and Data Lake consistency (`workouts.json.tmp` -> `os.replace`) under the Single-Writer pattern.
- **Dynamic Environment Parameterization:** Parameterized `KALISTENIKA_DIR` and `WHISPER_DEVICE` with 100% backward compatibility for host Windows execution.

---

## [2.3.0] - 2026-09-16
### Added
- **Asynchronous FastAPI & Uvicorn Engine:** Upgraded production backend from synchronous Flask to high-throughput asynchronous FastAPI + Pydantic v2 running on port 8000. Features strict request payload validation, interactive Swagger UI (`/docs`), and SRE process management with instant rollback capability (<5s).
- **Telegram Mobile Sanitizer & GitHub Alert Mapping:** Enhanced message formatting pipeline to automatically translate GitHub Flavored Markdown alerts (`> [!NOTE]`, `> [!TIP]`, `> [!WARNING]`) into mobile indicators and strip blockquote markers for clean Telegram rendering.
- **Comprehensive Unit Test Suite:** Expanded test suite to 23 automated unit and integration tests (`test_server_fastapi.py` and `test_server.py`) passing in <0.2s with full mock isolation.

### Fixed
- **Process Spawning Typing Compatibility:** Fixed generic typing support (`Popen[bytes]`) on Python 3.13 by replacing function monkeypatch with inheriting `PatchedPopen` class for headless background execution.

---

## [2.2.0] - 2026-09-16
### Added
- **SRE Self-Healing Watchdog:** Background monitoring thread auto-recovering the tunnel every 60s upon network drops, and auditing Telegram webhook health (`getWebhookInfo`) every 5 minutes to flush stalled queues.
- **Real-Time UX Typing Feedback (`sendChatAction: typing`):** Implemented `TelegramTypingAction` providing immediate, continuous visual feedback ("Project Coach is typing...") during speech-to-text transcription and agent reasoning.
- **Two-Track Architecture Diagrams (Retina 2x PNG):** Rendered pixel-perfect architecture diagrams in Polish and English (`architecture.png`, `architecture.pl.png`) replacing flaky GitHub Mermaid rendering.

### Fixed
- **Hermetic Lifecycle & Process Isolation:** Scoped process termination hooks exclusively to `__main__` and made Whisper GPU loading lazy (`init_whisper()`), allowing unit test suites to run in 0.04s without impacting production background processes or allocating GPU VRAM.
- **Showcase Data Sanitization:** Replaced old mobile interface screenshot with a 100% sanitized, high-resolution visual (`showcase/telegram_bot.jpg`) eliminating local path leaks.

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
- **Idempotence & Auto-Purge (TelegramDeduplicator):** Handled a Wear OS Telegram client race condition that sent duplicate voice packets within milliseconds. Outlier duplicates are dropped via global ile_unique_id, and redundant chat bubbles are asynchronously removed using deleteMessage.
- **Multi-Key Failover Router (GeminiKeyPool):** Dynamic rotation of 3 independent Google AI Studio keys with zero-millisecond failover upon encountering HTTP 429 quota exhaustion.
- **Session Serialization (chat_lock):** Per-chat locking mechanism preventing concurrency race conditions across agent session files and guarding RPM thresholds.
- **Host Environment Resilience (Power SRE):** Windows power policy tuned for Modern Standby S0 (AC sleep disabled, hardware battery conservation thresholds ~80%, ARSO automatic restart sign-on).

---

## [1.3.0] - 2026-09-12
### Added
- **Dynamic BMR Server Compensation:** Fixed an upstream sync discrepancy where Samsung Health exported only active calories to Google Health Connect, omitting basal metabolic rate (BMR).
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
- **Encrypted HTTPS Gateway:** Secure public ingress to local service without requiring static public IP or inbound port forwarding.
- **Raw Data Lake:** Persistent disk storage of all incoming JSON payloads before ETL processing.

---

## [0.1-alpha] - 2026-08-01
### Added
- **Proof of Concept (PoC):** Python scripts querying Google Fit and Strava REST APIs manually.
- **Flat CSV Storage:** Basic volume and cardio summaries tracked in local spreadsheets.
- **Friction Discovery:** Identified excessive friction in manual tracking, prompting the transition to an automated pipeline.
