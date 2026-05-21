# Research: iCloud 照片下载器

**Date**: 2026-05-20

## 1. docker-icloudpd 架构分析

### 现有架构

[ericcug/docker-icloudpd](https://github.com/ericcug/docker-icloudpd) 是 Shell 脚本驱动的 Alpine Linux 容器：

- **launcher.sh**: 容器入口，权限初始化 (user/group/umask)，加载配置，启动同步循环
- **sync-icloud.sh** (~120KB): 主同步脚本，包含认证检查→元数据比对→下载→后处理→通知完整流程
- **authenticate.exp**: Expect 脚本，自动化 iCloud 登录交互
- **healthcheck.sh**: 检查 cookie 有效性、下载/比对退出码
- **sendmessage.sh**: 通知发送 (Telegram/Webhook/Discord 等)
- **reauth.sh**: 重新认证辅助脚本

### Python 化策略

| Shell 组件 | Python 替代方案 | 决策理由 |
|-----------|----------------|---------|
| launcher.sh | `src/icloud_docker/main.py` + `config/entrypoint.sh` | entrypoint.sh 仅做最小权限设置，主逻辑在 Python |
| sync-icloud.sh | `src/icloud_docker/sync/engine.py` | 拆分 Shell 单文件为独立模块 |
| authenticate.exp | `src/icloud_docker/auth/session.py` | icloudpd 库提供 Python API，无需 Expect |
| healthcheck.sh | `src/icloud_docker/sync/engine.py` (health check endpoint) | 输出状态文件供 Docker HEALTHCHECK |
| sendmessage.sh | `src/icloud_docker/notify/` | 多渠道路由，统一事件模型 |
| reauth.sh | `src/icloud_docker/auth/session.py` + `control/telegram_bot.py` | Telegram 双向通信完成 MFA |

**Decision**: 全 Python 重构，直接导入 icloudpd 库的 Python API，提升性能和稳定性。
**Rationale**: Shell 脚本难以测试和维护（sync-icloud.sh 120KB 单文件）；Python 天然支持模块化、单元测试、类型提示；直接导入 icloudpd 内部 API 避免 subprocess 进程开销，可复用成熟的重试/断点续传/cookie 管理逻辑。
**Alternatives**: 部分 Python + 部分 Shell（混合架构）—— 增加维护复杂度，不选。

## 2. icloudpd 库 API 接口 (直接调用)

icloudpd 库 (v1.32.2) 提供完整的 Python API，直接导入使用：

### 核心 API 层级

| 模块 | 关键类/函数 | 用途 |
|------|-----------|------|
| `pyicloud_ipd.base` | `PyiCloudService` | iCloud 主客户端：登录、会话管理 |
| `pyicloud_ipd.services.photos` | `PhotosService`, `PhotoAsset` | 照片库操作：列出/搜索/下载 |
| `icloudpd.authentication` | `authenticator()` | 完整认证流程（含 MFA 回调） |
| `icloudpd.download` | `download_photo()` | 单文件下载 + 重试逻辑 |

### PyiCloudService 接口

```python
from pyicloud_ipd.base import PyiCloudService

# 创建客户端（cookie_directory 实现会话持久化）
service = PyiCloudService(
    apple_id="user@example.com",
    password="app-specific-password",
    cookie_directory="/config/cookies"
)

# 认证（含 MFA 交互通过回调）
service.authenticate(force_refresh=False)

# 获取 PhotosService
photos_service = service.photos  # → PhotosService
```

### PhotosService 接口

```python
# 懒加载分页遍历所有照片（Generator）
for photo in photos_service.photos:
    # photo is PhotoAsset
    print(photo.id, photo.filename, photo.created)
    for version_size, version in photo.versions.items():
        url = version.url
        # photo.download(session, url) → Response
```

### PhotoAsset 关键属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `id` | str | iCloud recordName（全局唯一标识） |
| `filename` | str | 原始文件名 |
| `created` | datetime | 创建时间 |
| `versions` | Dict[VersionSize, AssetVersion] | 可用版本（Original/Alternative/Thumbnail） |
| `download(session, url)` | Response | 下载文件 |

### MFA 交互

`authenticator()` 函数接受 `mfa_provider` 回调参数，支持自定义 MFA 输入源：

```python
from icloudpd.authentication import authenticator
from icloudpd.mfa_provider import MFAProvider

# 实现自定义 MFA Provider（如 Telegram Bot 接收验证码）
class TelegramMFAProvider(MFAProvider):
    def provide_code(self) -> str:
        return self.wait_for_telegram_code()

# 注入到 authenticator
service = authenticator(
    username="user@example.com",
    mfa_provider=TelegramMFAProvider(),
    cookie_directory="/config/cookies",
    ...
)
```

**Decision**: 直接导入 icloudpd 库的 Python API，不通过 subprocess CLI 调用。
**Rationale**: 
- 用户明确要求与 icloudpd 库不解耦，直接调用接口以获得更高性能和稳定性
- 直接调用避免进程启动开销（每张照片 subprocess 调用不可接受）
- 可复用 library 内部的下载重试、断点续传、cookie 管理等成熟逻辑
- MFA 流程可通过回调注入 Telegram Bot，无需 expect 或 stdin 交互
**Alternatives**: 
- subprocess CLI 调用 —— 被用户否决（性能差、耦合松散）
- HTTP REST 封装 —— 过度设计

## 3. Telegram Bot 集成方案

参考 docker-icloudpd 的 Telegram 2-way communication：

### 功能矩阵

| Telegram Bot 角色 | 实现方式 |
|-------------------|---------|
| 通知发送 | `python-telegram-bot` 异步发送消息 |
| MFA 验证码接收 | Bot 监听用户消息，解析验证码 → 注入认证流程 |
| 远程控制命令 | Bot 识别 `/pause`, `/resume`, `/sync`, `/status` 等命令 |
| 状态查询 | Bot 返回当前同步进度 |

**Decision**: 使用 `python-telegram-bot` 库，单 Bot 实例同时处理通知、MFA、控制三类功能。
**Rationale**: 单 Bot 简化配置（仅需一个 token），docker-icloudpd 已验证此模式可行。
**Alternatives**: 分离通知 Bot 和控制 Bot —— 配置复杂，无实质安全收益。

### 命令设计

| 命令 | 功能 | 对应 FR |
|------|------|--------|
| `/sync` | 立即启动同步 | FR-022 |
| `/pause` | 暂停同步 | FR-022 |
| `/resume` | 恢复同步 | FR-022 |
| `/status` | 查询状态/进度 | FR-022, FR-024 |
| `/reauth` | 重新认证 | FR-005 |
| `<6位验证码>` | MFA 验证码 | FR-005 |

## 4. 后置处理插件接口

**Decision**: Python 抽象基类 (ABC)，三生命周期方法：

```python
class BaseProcessor(ABC):
    version: str  # 插件版本
    
    @abstractmethod
    def init(self, config: dict) -> None: ...
    
    @abstractmethod
    def process(self, file_path: Path, metadata: dict) -> Path: ...
    
    @abstractmethod
    def cleanup(self) -> None: ...
```

**Rationale**: ABC 强制实现完整接口，类型安全；`version` 支持未来插件兼容性检查。
**Alternatives**: 
- Protocol (PEP 544) —— 更灵活但不强制继承，可被 `hasattr` 绕过
- CLI 脚本 —— 与用户选择 B 矛盾，且性能差（每文件启动进程）

## 5. 配置格式选择

| 格式 | 优点 | 缺点 |
|------|------|------|
| YAML | 可读性好，支持注释，层次化 | 需要 PyYAML |
| .conf (key=value) | docker-icloudpd 兼容，简单 | 不支持嵌套结构 |
| TOML | Python 生态标准 | 对非开发者不够直观 |
| 环境变量 | Docker 原生 | 复杂配置难以表达 |

**Decision**: YAML 配置文件为主要格式，环境变量覆盖为辅助（Docker 惯例）。
**Rationale**: YAML 支持嵌套结构（如流水线定义、通知渠道配置），可读性好；环境变量支持简单参数覆盖，不破坏 Docker 部署体验。
**Alternatives**: 纯环境变量 —— 流水线定义和多渠通知配置会非常冗长。

## 5a. iCloud API 限流策略（参考 docker-icloudpd）

docker-icloudpd 采用固定延迟模式处理 iCloud API 限流：

- **download_delay**: 配置项，每次文件下载后等待的秒数（默认 0）
- **retry 固定间隔**: 失败后 sleep 固定秒数（10s, 30s, 120s, 300s）后重试
- **无自适应算法**: 不使用指数退避或动态速率调整

### 决策对比

| 策略 | docker-icloudpd | 自适应降速（原方案） |
|------|----------------|-------------------|
| 实现复杂度 | 低（固定 sleep） | 高（需监测响应码、计算速率） |
| 可预测性 | 高（用户明确知道延迟） | 低（速率动态变化） |
| 有效性 | ✅ 已验证（数千用户） | 未验证 |
| 可配置性 | 简单（两个参数） | 复杂（需速率上限/下限/步长） |

**Decision**: 采用 docker-icloudpd 的固定延迟模式。配置项 `download_delay`（下载间延迟秒数）和 `retry_interval`（失败重试等待秒数）。
**Rationale**: docker-icloudpd 已验证数千用户场景；固定延迟更可预测；用户可控性强；实现复杂度低。
**Alternatives**: 自适应降速 —— 复杂度高，在固定下载间隔 + 429 响应自动翻倍 `download_delay` 即可达到类似效果。

## 6. Docker 镜像选型

| 镜像 | 体积 | Python 支持 | 适用性 |
|------|------|------------|--------|
| Alpine | ~50MB | 需编译安装 | ics-icloudpd 参考项目使用 |
| Ubuntu (slim) | ~80MB | 原生支持 | 兼容性好，调试方便 |
| python:3.11-slim | ~120MB | 原生 | 最简 Dockerfile |

**Decision**: `python:3.11-slim` 为基础镜像。
**Rationale**: 预装 Python 3.11+，无需编译依赖；slim 版保持体积适中；与 venv 隔离策略一致。
**Alternatives**: Alpine —— 体积更小但 musl libc 兼容性问题多，docker-icloudpd 已验证此问题 (需额外编译 icloudpd 依赖)。

## 7. 同步引擎设计

参考 docker-icloudpd 的同步循环逻辑：

```
loop:
  1. 检查认证会话有效性 → 过期则触发重新认证
  2. 比对云端/本地元数据 → 生成差异列表
  3. 下载差异文件 → 断点续传
  4. 每个文件完成后 → 触发后置处理流水线
  5. 发送周期通知 (进度/完成/错误)
  6. 等待 download_interval 后进入下一轮
```

**Decision**: 采用状态机管理同步生命周期，状态：IDLE → CHECKING → DOWNLOADING → PROCESSING → WAITING → IDLE。
**Rationale**: 状态机使得暂停/恢复/崩溃恢复行为可预测、可测试。
**Alternatives**: 线性脚本流（docker-icloudpd 模式）—— 难以实现暂停/恢复。
