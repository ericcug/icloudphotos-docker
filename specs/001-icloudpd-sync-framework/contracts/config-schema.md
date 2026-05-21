# Configuration Schema

**Version**: 1.0.0

## Format

YAML 配置文件，路径为 `/config/config.yaml` (Docker 内) 或 `./config.yaml` (本地开发)。
所有键使用 `snake_case`。

## Schema

```yaml
# === 必填项 ===
apple_id: "user@example.com"        # iCloud Apple ID
password: "app-specific-password"    # iCloud 应用专用密码 (非 Apple ID 密码)

# === 存储路径 ===
download_path: "/data/photos"       # 照片下载目录
folder_structure: "YYYY/MM"         # 目录结构: "YYYY/MM" | "YYYY-MM-DD" | "album" | "none"

# === 同步设置 ===
download_interval: 86400            # 同步周期间隔(秒)，默认 86400 (24 小时)

# === 下载限流（参考 docker-icloudpd 固定延迟模式）===
download_delay: 0                    # 每次下载间的延迟(秒)，0 表示无延迟，建议值 1-5
retry_interval: 120                  # 下载失败重试等待(秒)，默认 120
retry_count: 3                       # 单文件最大重试次数
file_permissions: "644"             # 文件权限: "600" | "640" | "644" | "660" | "664" | "666"
directory_permissions: "755"        # 目录权限
keep_unicode: true                  # 保留 Unicode 文件名
set_exif_datetime: true             # 从 EXIF 设置文件修改时间
file_match_policy: "name"           # 文件匹配策略: "name" | "size" | "checksum"

# === 删除策略 (FR-004a) ===
delete_policy: "keep"               # "keep" (保留本地) | "delete" (同步删除) | "trash" (移至回收站)
trash_days: 30                      # 回收站保留天数 (delete_policy=trash 时)

# === 中国区设置 ===
icloud_china: false                 # 使用 icloud.com.cn (中国区)
auth_china: false                   # 使用中国区认证服务器

# === 通知配置 (可选) ===
notification:
  telegram:
    enabled: false
    bot_token: ""                   # Telegram Bot Token
    chat_id: ""                     # 目标 Chat ID
    polling_interval: 5             # 消息轮询间隔(秒)
  webhook:
    enabled: false
    url: ""                         # Webhook URL
    method: "POST"
    headers: {}
  events:                           # 订阅的事件类型 (为空则全部)
    - "start"
    - "complete"
    - "error"
    - "auth_expired"
    - "low_space"
    - "rate_limited"

# === 后置处理流水线 (可选) ===
pipeline:
  steps:
    - name: "heic_convert"          # 处理器名称
      config:                       # 处理器参数
        quality: 85
        remove_original: false
      retry: 3                      # 失败重试次数
      enabled: true

    - name: "custom_watermark"      # 用户自定义处理器
      config:
        text: "© MyFamily"
      retry: 1
      enabled: true

# === 高级设置 ===
log_level: "info"                   # "debug" | "info" | "warning" | "error"
debug_logging: false                # 启用调试日志 (会输出敏感信息脱敏版本)

# === 环境变量覆盖 ===
# 以下环境变量可覆盖配置文件中的对应值:
# ICLOUD_APPLE_ID, ICLOUD_PASSWORD, ICLOUD_DOWNLOAD_PATH,
# ICLOUD_TELEGRAM_TOKEN, ICLOUD_TELEGRAM_CHAT_ID
```

## 环境变量覆盖规则

1. 环境变量名 = `ICLOUD_` + 大写下划线形式 (如 `apple_id` → `ICLOUD_APPLE_ID`)
2. 环境变量存在时覆盖 YAML 中的值
3. 密码类字段 (`password`, `bot_token`) 建议仅通过环境变量设置，不写入 YAML
4. 嵌套配置不支持环境变量覆盖 (如 `pipeline.steps` 仅通过 YAML 配置)
