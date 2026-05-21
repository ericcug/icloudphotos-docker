# Tasks: iCloud 照片下载器

**Input**: Design documents from `/specs/001-icloudpd-sync-framework/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Tests are MANDATORY for every feature per the project constitution. Each user story MUST include corresponding test tasks.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/icloud_docker/`, `tests/` at repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Create project directory structure per plan.md in `src/icloud_docker/` and `tests/`
- [x] T002 [P] Create `requirements.txt` with dependencies: icloudpd==1.32.2, requests, python-telegram-bot, PyYAML, pillow, pytest, pytest-cov, pytest-mock
- [x] T003 [P] Create `venv/` virtual environment for local development and install dependencies (Docker 构建不使用 venv，直接 pip install)
- [x] T004 [P] Create `pyproject.toml` with project metadata (name=icloud_docker, python>=3.11) and pytest config
- [x] T005 [P] Create `config/config.example.yaml` template with all schema fields from `contracts/config-schema.md`
- [x] T006 [P] Create `config/Dockerfile` based on `python:3.11-slim` with non-root user setup and direct `pip install -r requirements.txt` (no venv in container)
- [x] T007 [P] Create `config/docker-compose.yml` with volume mounts for /config, /data
- [x] T008 [P] Create `config/entrypoint.sh` for container startup (permission setup + Python launch)
- [x] T009 [P] Create `tests/conftest.py` with shared pytest fixtures (tmp_path, config_dict, mock_icloud_service)
- [x] T010 Create `.dockerignore` excluding venv/, tests/, .git/, .specify/

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T011 Implement configuration loader `src/icloud_docker/config/schema.py` — define Config dataclass, YAML schema, environment variable override logic (FR-001~FR-004a)
- [x] T012 Implement configuration loader `src/icloud_docker/config/loader.py` — load YAML, validate required fields, apply env var overrides, return Config instance
- [x] T013 [P] Implement logger module `src/icloud_docker/__init__.py` — setup structured logging to stdout, configurable log levels, password filter (FR-008)
- [x] T014 [P] Implement application entry point `src/icloud_docker/main.py` — parse CLI args (--config), load config, initialize logger, orchestrate startup sequence

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - 环境配置与首次同步 (Priority: P1) 🎯 MVP

**Goal**: 用户配置 iCloud 账号后，系统通过 Telegram MFA 完成认证并开始首次照片同步

**Independent Test**: 配置好 config.yaml 后运行 main.py，通过 Telegram Bot 发送 MFA 验证码完成认证，系统开始下载 iCloud 照片到指定目录

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T015 [P] [US1] Unit tests for config schema validation in `tests/config/test_schema.py` — test required fields, env var override, invalid values
- [x] T016 [P] [US1] Unit tests for config loader in `tests/config/test_loader.py` — test YAML load, validation, env override, missing config error
- [x] T017 [P] [US1] Unit tests for auth session in `tests/auth/test_session.py` — test login flow mock, MFA provider injection, session persistence
- [x] T018 [P] [US1] Unit tests for cookie store in `tests/auth/test_cookie_store.py` — test cookie save/load, expiry detection, permissions (chmod 600)
- [x] T019 [P] [US1] Unit tests for MFA provider in `tests/auth/test_mfa.py` — test TelegramMFAProvider, code validation, timeout handling
- [x] T020 [P] [US1] Unit tests for iCloud wrapper in `tests/sync/test_icloud_wrapper.py` — test PyiCloudService creation, authenticate(), photos property mock
- [x] T021 [P] [US1] Unit tests for metadata differ in `tests/sync/test_differ.py` — test local vs cloud diff, new/modified/deleted detection, delete_policy
- [x] T022 [P] [US1] Unit tests for downloader in `tests/sync/test_downloader.py` — test download_photo mock, retry, resume, rate limiting (FR-012a)
- [x] T023 [US1] Integration test for US1 end-to-end in `tests/test_integration.py` — test config load → auth → differ → download pipeline with mocks

### Implementation for User Story 1

- [x] T024 [P] [US1] Implement cookie store `src/icloud_docker/auth/cookie_store.py` — save/load session cookie to filesystem with chmod 600, check expiry
- [x] T025 [P] [US1] Implement MFA provider `src/icloud_docker/auth/mfa.py` — TelegramMFAProvider class implementing icloudpd.mfa_provider.MFAProvider interface
- [x] T026 [US1] Implement auth session `src/icloud_docker/auth/session.py` — wrap icloudpd.authentication.authenticator() with TelegramMFAProvider injection, cookie persistence (FR-005~FR-008)
- [x] T027 [P] [US1] Implement iCloud wrapper `src/icloud_docker/sync/icloud_wrapper.py` — wrap PyiCloudService creation, authenticate call, expose photos_service property
- [x] T028 [P] [US1] Implement metadata differ `src/icloud_docker/sync/differ.py` — iterate service.photos Generator, compare with local filesystem, produce diff dict (FR-009)
- [x] T029 [US1] Implement downloader `src/icloud_docker/sync/downloader.py` — download single asset using icloudpd.download, resume support, rate limit detection (FR-010~FR-012a)
- [x] T030 [US1] Implement sync engine `src/icloud_docker/sync/engine.py` — state machine (IDLE→CHECKING→DOWNLOADING→WAITING), coordinate differ+downloader, crash recovery retry (FR-011)
- [x] T031 [US1] Wire US1 in main.py — load config → auth → sync engine start, add --once flag for single sync run

**Checkpoint**: User Story 1 可独立验证——配置→认证(Telegram MFA)→首次同步→下载完成

---

## Phase 4: User Story 2 - 后置处理流水线 (Priority: P2)

**Goal**: 照片下载完成后，用户配置的后置处理步骤按序执行

**Independent Test**: 配置 HEIC→JPG 转换步骤，下载一张 HEIC 照片后验证 JPG 文件生成且流水线日志正确

### Tests for User Story 2

- [x] T032 [P] [US2] Unit tests for BaseProcessor ABC in `tests/pipeline/test_base.py` — test ABC enforcement, version check, incomplete implementation error
- [x] T033 [P] [US2] Unit tests for pipeline runner in `tests/pipeline/test_runner.py` — test sequential execution, retry on failure, skip disabled steps, error isolation (one failure doesn't block others)
- [x] T034 [P] [US2] Unit tests for HEIC converter in `tests/pipeline/test_heic_convert.py` — test HEIC→JPG conversion, non-HEIC passthrough, quality config

### Implementation for User Story 2

- [x] T035 [P] [US2] Implement BaseProcessor ABC `src/icloud_docker/pipeline/base.py` — abstract base class with init/process/cleanup lifecycle and ProcessorError (FR-016a)
- [x] T036 [P] [US2] Implement built-in HEIC converter `src/icloud_docker/pipeline/builtin/heic_convert.py` — pillow-based conversion, quality config, remove_original option
- [x] T037 [US2] Implement pipeline runner `src/icloud_docker/pipeline/runner.py` — load steps from config, instantiate processors, sequential execution with retry and error isolation (FR-013, FR-015, FR-016)
- [x] T038 [US2] Integrate pipeline runner into sync engine — call runner.process(file_path, metadata) after each successful download in engine.py

**Checkpoint**: US1 + US2 可独立验证——下载完成后 HEIC→JPG 转换自动执行

---

## Phase 5: User Story 3 - 消息通知与状态监控 (Priority: P2)

**Goal**: 关键系统事件通过 Telegram/Webhook 通知用户，支持状态查询

**Independent Test**: 模拟认证过期事件，验证 Telegram 收到通知消息

### Tests for User Story 3

- [x] T039 [P] [US3] Unit tests for event bus in `tests/notify/test_bus.py` — test event dispatch, subscription filtering, cache on failure
- [x] T040 [P] [US3] Unit tests for notification channels in `tests/notify/test_channels.py` — test Telegram send, Webhook POST, channel fallback

### Implementation for User Story 3

- [x] T041 [P] [US3] Define system event types `src/icloud_docker/notify/bus.py` — SystemEvent dataclass, EventBus with subscribe/publish (FR-017, FR-019)
- [x] T042 [P] [US3] Implement notification cache and retry — 24h cache for failed sends, retry on recovery (FR-020)
- [x] T043 [US3] Implement Telegram notification channel `src/icloud_docker/notify/channels/telegram.py` — send message via Bot API (FR-018)
- [x] T044 [US3] Implement Webhook notification channel `src/icloud_docker/notify/channels/webhook.py` — HTTP POST to configured URL (FR-018)
- [x] T045 [US3] Integrate event bus into sync engine — publish start/complete/error/auth_expired/low_space events at appropriate lifecycle points

**Checkpoint**: US3 可独立验证——触发事件后 Telegram 收到对应通知消息

---

## Phase 6: User Story 4 - 远程控制与监听 (Priority: P3)

**Goal**: 用户通过 Telegram Bot 发送命令控制同步，无需登录宿主机

**Independent Test**: 通过 Telegram 发送 /pause 命令，验证同步引擎在下一个检查点暂停

### Tests for User Story 4

- [x] T046 [P] [US4] Unit tests for Telegram command handler in `tests/control/test_telegram_bot.py` — test /pause, /resume, /sync, /status command parsing and responses
- [x] T047 [P] [US4] Unit tests for file-based command fallback in `tests/control/test_file_watch.py` — test command file polling, parsing, cleanup

### Implementation for User Story 4

- [x] T048 [P] [US4] Implement Telegram Bot command handler `src/icloud_docker/control/telegram_bot.py` — python-telegram-bot setup, command parsing (/pause, /resume, /sync, /status, /reauth), natural language support (FR-021~FR-024)
- [x] T049 [US4] Implement file-based command fallback `src/icloud_docker/control/file_watch.py` — poll command file for instructions, support same command set (FR-021 fallback)
- [x] T050 [US4] Integrate Telegram Bot with sync engine state machine — bridge Bot commands to engine.pause()/resume()/sync_now()
- [x] T051 [US4] Wire Telegram Bot into main.py startup — launch Bot polling thread alongside sync engine

**Checkpoint**: US4 可独立验证——Telegram /pause → 引擎暂停 → /resume → 引擎恢复

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T052 [P] Add `config/healthcheck.sh` for Docker HEALTHCHECK — check cookie validity, sync process liveness
- [x] T053 [P] Add fixed-delay download throttling per docker-icloudpd pattern — configurable `download_delay` and `retry_interval` in `src/icloud_docker/sync/downloader.py`, with automatic interval doubling on 429 responses
- [x] T054 [P] Add comprehensive docstrings (Google-style) to all public modules/classes/functions per constitution
- [x] T055 [P] Add `tests/test_integration.py` end-to-end test with mocked external dependencies (iCloud API, Telegram)
- [x] T056 Run `quickstart.md` validation — venv setup → pytest → Docker build → docker-compose up
- [x] T057 Performance validation — 100-item mock sync overhead <10%, 50k metadata diff <5min per SC-002/SC-008; verify download_delay/retry_interval behavior under simulated 429 responses

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational — No dependencies on other stories
- **User Story 2 (Phase 4)**: Depends on Foundational — Needs sync engine from US1 for integration (T038)
- **User Story 3 (Phase 5)**: Depends on Foundational — Needs sync engine from US1 for integration (T045)
- **User Story 4 (Phase 6)**: Depends on Foundational — Needs sync engine from US1 for integration (T050)
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **US1 (P1)**: Can start after Foundational — No dependencies on other stories
- **US2 (P2)**: Can start after Foundational but T038 needs US1 sync engine
- **US3 (P2)**: Can start after Foundational but T045 needs US1 sync engine  
- **US4 (P3)**: Can start after Foundational but T050 needs US1 sync engine

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Models/utilities before services
- Services before engine integration
- Story complete before moving to next priority

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel (T002-T009)
- All Foundational tasks marked [P] can run in parallel
- Once Foundational phase completes, all US test tasks can start in parallel
- Within US1: T015-T023 (tests) all [P]; T024/T025/T027/T028 (independent modules) all [P]
- US2, US3, US4 can have their test phases start in parallel after Foundational

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests in parallel:
Task: "Unit tests for config schema in tests/config/test_schema.py"
Task: "Unit tests for config loader in tests/config/test_loader.py"
Task: "Unit tests for auth session in tests/auth/test_session.py"
Task: "Unit tests for cookie store in tests/auth/test_cookie_store.py"
Task: "Unit tests for MFA provider in tests/auth/test_mfa.py"
Task: "Unit tests for iCloud wrapper in tests/sync/test_icloud_wrapper.py"
Task: "Unit tests for metadata differ in tests/sync/test_differ.py"
Task: "Unit tests for downloader in tests/sync/test_downloader.py"

# After tests fail, launch independent modules in parallel:
Task: "Implement cookie store in src/icloud_docker/auth/cookie_store.py"
Task: "Implement MFA provider in src/icloud_docker/auth/mfa.py"
Task: "Implement iCloud wrapper in src/icloud_docker/sync/icloud_wrapper.py"
Task: "Implement metadata differ in src/icloud_docker/sync/differ.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T010)
2. Complete Phase 2: Foundational (T011-T014)
3. Complete Phase 3: User Story 1 (T015-T031)
4. **STOP and VALIDATE**: 配置 config.yaml → 运行 main.py → Telegram MFA → 首次同步
5. Deploy MVP Docker image

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add US1 → 照片下载可用 (MVP!)
3. Add US2 → 后置处理流水线
4. Add US3 → 通知与监控
5. Add US4 → Telegram 远程控制
6. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1 (critical path - must complete first for integration points)
   - Developer B: User Story 2 (can start independent modules while US1 engine builds)
   - Developer C: User Story 3 + 4 (can start independent modules)
3. Integration points (T038, T045, T050) require US1 engine → brief sync needed

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
