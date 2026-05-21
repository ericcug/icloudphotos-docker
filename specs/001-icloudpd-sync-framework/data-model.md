# Data Model: iCloud 照片下载器

**Date**: 2026-05-20

## Entities

### 配置 (Configuration)

```yaml
# 对应 spec Key Entity: 配置
config:
  apple_id: str              # iCloud 账号 (必填)
  password: str              # iCloud 密码 (必填，日志中脱敏)
  download_path: Path        # 下载目录 (必填)
  folder_structure: str      # 目录结构: "YYYY/MM" | "YYYY-MM-DD" | "album"
  download_interval: int     # 同步间隔(秒)，默认 86400 (24h)
  file_permissions: str      # 文件权限，默认 "644"
  auth_china: bool           # 中国区 iCloud，默认 false

  notification:              # 通知配置 (可选)
    telegram:
      enabled: bool
      bot_token: str
      chat_id: str
    webhook:
      enabled: bool
      url: str
    events: list[str]        # 订阅事件: start, complete, error, auth_expired, low_space

  pipeline:                  # 后置处理流水线 (可选)
    steps:
      - name: str            # 处理器标识
        config: dict         # 处理器配置参数
        retry: int           # 重试次数，默认 3

  sync:                      # 同步策略
    delete_policy: str       # "keep" | "delete" | "trash"
    keep_unicode: bool       # 保留 Unicode 文件名
    set_exif_datetime: bool  # 设置 EXIF 时间
    file_match_policy: str   # "name" | "size" | "checksum"
```

**Validation Rules**:
- `apple_id` MUST 包含 `@`
- `download_path` MUST 可写且存在
- `folder_structure` MUST 为枚举值之一
- `download_interval` MUST ≥ 60 秒

### 认证会话 (Auth Session)

```python
@dataclass
class AuthSession:
    cookie_file: Path           # Cookie 文件路径
    apple_id_hash: str          # Apple ID 的哈希 (文件名)
    token: str                  # Session token
    expires_at: datetime        # 过期时间
    trusted_devices: list[str]  # 信任设备列表
    auth_type: str              # "MFA" | "Web"
    
    def is_valid(self) -> bool: ...
    def days_remaining(self) -> int: ...
```

**State Transitions**:
```
[未认证] --登录+MFA--> [已认证/有效] --过期--> [已过期]
                                                      |
                                              Telegram MFA 重认证
                                                      |
                                                      v
                                              [已认证/有效]
```

### 媒体资产 (Media Asset)

```python
@dataclass
class MediaAsset:
    # iCloud 标识
    record_name: str            # iCloud 唯一标识符 (主键)
    filename: str               # 原始文件名
    media_type: str             # "photo" | "video" | "live_photo"
    
    # 元数据
    size_bytes: int
    width: int
    height: int
    created_at: datetime
    modified_at: datetime
    checksum: Optional[str]     # 文件校验和 (file_match_policy=checksum 时)
    
    # 本地状态
    local_path: Optional[Path]
    download_status: str        # "pending" | "downloading" | "downloaded" | "failed"
    local_modified_at: Optional[datetime]
```

**Identity Rule**: `record_name` 是 iCloud 分配的全局唯一标识符。

**Download State Transitions**:
```
[pending] --> [downloading] --> [downloaded]
    |                             |
    +--------> [failed] <---------+
                    |
                    v
               [pending] (重试)
```

### 同步任务 (Sync Task)

```python
@dataclass
class SyncTask:
    task_id: str                # UUID
    started_at: datetime
    finished_at: Optional[datetime]
    status: str                 # "idle" | "checking" | "downloading" | "processing" | "waiting" | "paused" | "failed"
    total_assets: int           # 云端总资产数
    processed_assets: int       # 已处理数
    downloaded_assets: int      # 已下载数
    failed_assets: int          # 失败数
    errors: list[str]           # 错误列表
```

**Sync Engine State Machine**:
```
                          ┌──────────┐
                          │   IDLE   │
                          └────┬─────┘
                               │ 开始同步 / 定时器触发
                               v
                          ┌──────────┐
                    ┌─────│ CHECKING │─────┐
                    │     └────┬─────┘     │
                    │          │ 差异      │ 无差异
                    │          v           v
                    │   ┌────────────┐  ┌─────────┐
                    │   │ DOWNLOADING│  │ WAITING │──┐
                    │   └─────┬──────┘  └─────────┘  │
                    │         │ 文件下载完成          │
                    │         v                       │
                    │   ┌────────────┐               │
                    │   │ PROCESSING │               │
                    │   └─────┬──────┘               │
                    │         │ 流水线完成            │
                    │         v                       │
                    │   ┌─────────┐                  │
                    └──>│ WAITING │<─────────────────┘
                        └────┬────┘
                             │ 暂停命令
                             v
                        ┌─────────┐
                        │ PAUSED  │──> 恢复命令 → IDLE
                        └─────────┘
```

### 后置处理步骤 (Post-Processing Step)

```python
@dataclass
class PipelineStep:
    name: str                   # 处理器标识
    processor: BaseProcessor    # 处理器实例
    config: dict                # 配置参数
    retry_count: int            # 最大重试次数
    order: int                  # 执行顺序
```

### 系统事件 (System Event)

```python
@dataclass
class SystemEvent:
    event_type: str             # "start" | "complete" | "error" | "auth_expired" | "low_space" | "rate_limited"
    timestamp: datetime
    severity: str               # "info" | "warning" | "error" | "critical"
    message: str
    details: Optional[dict]     # 额外信息
```

## Relationships

```
Configuration 1──1 SyncEngine
SyncEngine    1──* MediaAsset (通过 iCloud API)
SyncEngine    1──1 SyncTask (当前任务)
SyncEngine    1──* PipelineStep (通过配置)
SyncEngine    1──1 AuthSession
SyncEngine    1──* SystemEvent (通过 EventBus)
EventBus      1──* NotificationChannel
```
