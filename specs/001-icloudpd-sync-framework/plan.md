# Implementation Plan: iCloud 照片下载器

**Branch**: `001-icloudpd-sync-framework` | **Date**: 2026-05-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-icloudpd-sync-framework/spec.md`

## Summary

构建一个基于 Docker 的 iCloud 照片自动下载器，以 Python 重写 [docker-icloudpd](https://github.com/ericcug/docker-icloudpd)
的核心功能，采用模块化架构。主要技术决策：用 Python 替代 Shell 脚本编排，保持与 icloudpd 库的兼容性，
通过 Telegram Bot 实现双向通信（通知 + MFA + 远程控制），采用 Python 模块作为后置处理插件机制。

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: icloudpd==1.32.2 (icloud-photos-downloader, 直接导入内部 API), pyicloud-ipd, python-telegram-bot, PyYAML, pytest, pillow
**Storage**: 本地文件系统 (照片/视频存储在 bind-mounted 目录)
**Testing**: pytest + pytest-cov + pytest-mock; 所有模块在 `tests/` 目录下
**Target Platform**: Linux (Docker Alpine/Ubuntu), macOS 开发环境
**Project Type**: Docker 容器化 CLI 应用
**Performance Goals**: 100 张照片同步开销 <10% 网络时间; 50k 照片元数据比对 <5 分钟
**Constraints**: Docker 单实例; 非 root 运行; 开发用 venv 隔离, Docker 直接 pip install; 内存 <512MB
**Scale/Scope**: ≤50,000 媒体资产; 6 大功能模块; 27 项功能需求

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Docker-First | ✅ PASS | Dockerfile + docker-compose.yml 作为交付物 |
| II. Python venv | ✅ PASS | 开发环境使用 venv/; Docker 容器内直接 pip install (无需 venv) |
| III. Test-First | ✅ PASS | 每个模块对应 tests/ 下的 pytest 测试 |
| IV. Comprehensive Docs | ✅ PASS | 所有模块/类/函数使用 Google-style docstrings |
| V. Library-First | ✅ PASS | 核心基于 icloudpd 库; 不替换其功能 |

**Gate Result**: ALL PASS — 可以进入 Phase 0。

## Project Structure

### Documentation (this feature)

```text
specs/001-icloudpd-sync-framework/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (plugin interface, CLI schema, config schema)
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
src/
├── icloud_docker/            # 主包
│   ├── __init__.py
│   ├── config/               # 环境与配置管理模块
│   │   ├── __init__.py
│   │   ├── loader.py         # 配置文件/环境变量加载与校验 (FR-001~FR-004a)
│   │   └── schema.py         # 配置项定义与默认值
│   ├── auth/                 # 认证与安全模块
│   │   ├── __init__.py
│   │   ├── session.py        # iCloud 登录（调用 icloudpd.authentication.authenticator）
│   │   ├── mfa.py            # Telegram MFA Provider 实现 (FR-005~FR-008)
│   │   └── cookie_store.py   # Cookie 持久化与过期检测
│   ├── sync/                 # 核心同步引擎
│   │   ├── __init__.py
│   │   ├── engine.py         # 同步协调器/状态机 (FR-009~FR-012a)
│   │   ├── differ.py         # 云端/本地元数据比对（直接调用 pyicloud_ipd）
│   │   ├── downloader.py     # 文件下载 + 固定延迟限流（docker-icloudpd 模式）
│   │   └── icloud_wrapper.py # PyiCloudService 封装（会话管理、MFA 回调）
│   ├── pipeline/             # 后置处理流水线
│   │   ├── __init__.py
│   │   ├── base.py           # 插件抽象基类 (FR-014, FR-016a)
│   │   ├── runner.py         # 流水线编排器 (FR-013, FR-015, FR-016)
│   │   └── builtin/          # 内置后置处理器
│   │       ├── __init__.py
│   │       └── heic_convert.py  # HEIC→JPG 转换 (参考 docker-icloudpd)
│   ├── notify/               # 消息通知总线
│   │   ├── __init__.py
│   │   ├── bus.py            # 事件总线与分发 (FR-017, FR-019, FR-020)
│   │   └── channels/         # 通知渠道
│   │       ├── __init__.py
│   │       ├── telegram.py   # Telegram Bot 通知 (FR-018)
│   │       └── webhook.py    # 通用 Webhook
│   ├── control/              # 远程控制与监听
│   │   ├── __init__.py
│   │   ├── telegram_bot.py   # Telegram Bot 命令处理 (FR-021~FR-024)
│   │   └── file_watch.py     # 本地配置文件指令通道 (fallback)
│   └── main.py               # 应用入口

tests/
├── __init__.py
├── conftest.py               # fixtures: mock icloudpd, temp dirs, config
├── config/
│   ├── test_loader.py
│   └── test_schema.py
├── auth/
│   ├── test_session.py
│   ├── test_mfa.py
│   └── test_cookie_store.py
├── sync/
│   ├── test_engine.py
│   ├── test_differ.py
│   ├── test_downloader.py
│   └── test_icloud_wrapper.py
├── pipeline/
│   ├── test_base.py
│   ├── test_runner.py
│   └── test_heic_convert.py
├── notify/
│   ├── test_bus.py
│   └── test_channels.py
├── control/
│   ├── test_telegram_bot.py
│   └── test_file_watch.py
└── test_integration.py       # 端到端集成测试

config/                        # Docker 运行时配置
├── docker-compose.yml
├── Dockerfile
├── config.example.yaml        # 用户配置模板
└── entrypoint.sh              # 容器入口 (权限设置 + 启动 Python)
```

**Structure Decision**: 单项目结构 (Option 1)，包名 `icloud_docker`，各模块独立可测。参考 docker-icloudpd 的功能划分，但以 Python 包形式组织。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (无违规) | | |

## Phase 0: Research

See [research.md](./research.md) for:
- docker-icloudpd 架构分析与 Python 化策略
- icloudpd 库 API 接口研究（直接导入）
- docker-icloudpd 限流/延迟策略研究
- Telegram Bot API 集成方案
- 后置处理插件接口设计
- 配置格式选择 (YAML vs .conf)
- Docker 镜像选型 (python:3.11-slim)

## Phase 1: Design

See:
- [data-model.md](./data-model.md) — 实体模型与状态机
- [contracts/](./contracts/) — 插件接口契约、CLI 命令规格、配置文件 schema
- [quickstart.md](./quickstart.md) — 开发者快速上手
