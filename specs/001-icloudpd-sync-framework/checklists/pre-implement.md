# Pre-Implementation Requirements Quality Checklist: iCloud 照片下载器

**Purpose**: Validate requirements completeness, clarity, and consistency across all 6 modules before `/speckit-implement`
**Created**: 2026-05-20
**Depth**: Standard (全模块)
**Audience**: 作者自查
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [tasks.md](../tasks.md)

---

## 环境与配置管理模块

- [x] CHK001 - 配置项枚举是否完整？FR-001 要求"通过环境变量或配置文件读取所有运行参数"，是否所有参数（含通知渠道、流水线步骤、同步策略）均已列入 `contracts/config-schema.md`？ [Completeness, Spec §FR-001]
- [x] CHK002 - 必填 vs 可选配置项的边界是否清晰？是否每种配置都有明确的默认值和必填标记？ [Clarity, Spec §FR-002]
- [x] CHK003 - FR-003 要求"配置变更后无需重建容器即可生效"，具体实现方式（inotify 热加载 / SIGHUP 重载 / 定时轮询 / Docker restart）是否已在 plan/research 中明确决策？ [Gap, Spec §FR-003]
- [x] CHK004 - FR-004 要求"仅能写入指定的下载目录和缓存目录"，是否明确定义了白名单路径列表和违规行为的处理方式（拒绝写入 / 告警 / 终止）？ [Clarity, Spec §FR-004]
- [x] CHK005 - FR-004a 删除策略的三种选项（保留/删除/回收站）是否在配置 schema 中完整定义？回收站路径和保留天数是否可配置且已文档化？ [Completeness, Spec §FR-004a]
- [x] CHK006 - 配置文件格式从 YAML 迁移到其他格式（如有需要）的兼容性策略是否已考虑？ [Gap]

## 认证与安全模块

- [x] CHK007 - MFA 流程的完整状态机是否已定义？（等待验证码 → 超时 → 重发 → 验证成功 → 验证失败 → 设备选择）每个状态转换的条件和超时是否明确？ [Completeness, Spec §FR-005]
- [x] CHK008 - FR-005 明确 Telegram Bot 接收 MFA 验证码，若 Telegram Bot 离线/未配置时，回退流程（日志输出 URL）是否在 FR 或 Assumptions 中完整描述？ [Coverage, Spec §FR-005]
- [x] CHK009 - FR-006 会话持久化使用 chmod 600 权限，是否已明确 cookie 文件的存储路径、命名规则、以及 Docker volume 挂载后的跨容器迁移兼容性？ [Clarity, Spec §FR-006]
- [x] CHK010 - FR-007 "检测会话过期并提示重新认证"——过期检测的时间窗口（检查间隔）和通知方式（仅 Telegram / 日志 / 两者）是否已定义？ [Clarity, Spec §FR-007]
- [x] CHK011 - FR-008 密码脱敏要求是否涵盖了所有日志输出路径（stdout、文件日志、Telegram 通知、错误堆栈）？脱敏后的可见字符数是否已规定？ [Completeness, Spec §FR-008]
- [x] CHK012 - Apple ID 高级数据保护 (ADP) 场景在 spec Edge Cases 中提到但在 FR 中无对应处理要求——是明确排除（ADP 不支持）还是待定义？ [Gap, Spec Edge Cases]

## 核心同步引擎

- [x] CHK013 - FR-009 元数据比对策略的"修改"判定标准是否明确？（仅时间戳 / 文件大小 / 校验和 / 组合策略）`file_match_policy` 的三个选项各自的具体行为是否已定义？ [Clarity, Spec §FR-009]
- [x] CHK014 - FR-010 目录结构选项（日期/相册/无）的完整枚举和每种选项的文件命名冲突处理规则是否已定义？ [Completeness, Spec §FR-010]
- [x] CHK015 - FR-011 断点续传的"断点"粒度（文件级别 / 分块级别）是否明确？崩溃恢复 3 次后的最终状态（停止并通知 / 进入等待下一周期）是否已定义？ [Clarity, Spec §FR-011]
- [x] CHK016 - FR-012a 限流自适应降速的速率范围（最高速率 → 最低速率）和降速算法（线性 / 指数 / 百分比阶梯）是否已明确？ [Clarity, Spec §FR-012a]
- [x] CHK017 - 同步引擎状态机（IDLE→CHECKING→DOWNLOADING→PROCESSING→WAITING→PAUSED）的各状态转换触发条件和时间约束是否完整定义？ [Completeness, data-model.md]
- [x] CHK018 - SC-002 (100 张照片开销 <10%) 和 SC-008 (50k 元数据 <5min) 的测量方法（工具、环境、网络条件假设）是否已定义，以便可复现验证？ [Measurability, Spec §SC-002/SC-008]

## 后置处理流水线

- [x] CHK019 - FR-014 插件发现机制（内置扫描路径 / 用户指定模块路径 / 注册表）是否在 contracts 或 plan 中完整定义？ [Completeness, Spec §FR-014]
- [x] CHK020 - FR-016a 接口契约中 `metadata` 字典的完整字段列表和类型是否已文档化？新增字段的向后兼容策略是否已定义？ [Clarity, Spec §FR-016a]
- [x] CHK021 - FR-015 重试机制是否区分了可重试错误（网络/临时）和不可重试错误（配置无效/文件损坏）？重试间隔是否已定义？ [Clarity, Spec §FR-015]
- [x] CHK022 - FR-016 "单步失败不阻塞流水线"——失败步骤后的后续步骤是否仍接收原始文件（跳过失败步骤的处理结果）还是中断整条流水线对当前文件？ [Clarity, Spec §FR-016]
- [x] CHK023 - 后置处理任务执行超时（边缘情况提到"数小时"）是否需要超时机制？若需要，超时后行为（跳过该步骤 / 标记失败 / 终止流水线）是否已定义？ [Gap, Spec Edge Cases]

## 消息通知总线

- [x] CHK024 - FR-017 系统事件类型枚举是否完整？（当前: 启动、完成、错误、认证过期、空间不足、限流）是否遗漏了"同步暂停""同步恢复""MFA 请求"等事件？ [Completeness, Spec §FR-017]
- [x] CHK025 - FR-019 "用户选择性订阅事件类型"——未订阅时的默认行为（全部发送 / 仅错误 / 无通知）是否已定义？ [Clarity, Spec §FR-019]
- [x] CHK026 - FR-020 通知缓存 24 小时——缓存存储位置、最大缓存数量、缓存满时的策略（丢弃最旧 / 丢弃最低优先级 / 拒绝新事件）是否已定义？ [Clarity, Spec §FR-020]
- [x] CHK027 - SC-005 (通知延迟 <30s) 的测量起点（事件触发时刻 / 缓存写入时刻 / 发送尝试时刻）是否明确？ [Measurability, Spec §SC-005]
- [x] CHK028 - Webhook 通知渠道的自定义 Header 和重试策略是否已定义？ [Completeness, Spec §FR-018]

## 远程控制与监听

- [x] CHK029 - FR-022 Telegram 自然语言命令解析的支持范围（仅精确匹配 / 模糊匹配 / 关键词提取）和未识别命令的反馈是否已定义？ [Clarity, Spec §FR-022]
- [x] CHK030 - FR-023 "指令合法性校验"的具体校验规则（命令白名单 / 参数格式 / 频率限制）是否已定义？ [Clarity, Spec §FR-023]
- [x] CHK031 - Telegram Bot 离线时，FR-021 回退到的"本地配置文件指令通道"的指令格式、轮询间隔、指令执行后的清理规则是否已定义？ [Completeness, Spec §FR-021]
- [x] CHK032 - SC-006 (远程控制延迟 <5s) 是否考虑了 Telegram API 的网络延迟不可控因素？若 Telegram 服务器延迟 >5s，是否仍视为不达标？ [Measurability, Spec §SC-006]
- [x] CHK033 - 多个授权用户通过 Telegram 同时发送冲突指令（如 A 暂停 / B 恢复）时的优先级/竞态处理是否已定义？ [Gap, Spec §US4]

## 跨模块一致性

- [x] CHK034 - spec 中"照片"一词在 FR-010 已更新为"照片、视频和 Live Photo"，其他 FR 和 User Story 描述是否已统一为"媒体资产"或"照片/视频"？ [Consistency]
- [x] CHK035 - data-model.md 定义的实体属性是否与 spec FR 中的字段要求一致？（如 MediaAsset.checksum 与 FR-009 file_match_policy=checksum 的对应关系） [Consistency]
- [x] CHK036 - plan.md 的 Technical Context 声明 `内存 <512MB`，但 spec Success Criteria 中无对应内存约束——这是实现约束还是应升级为 SC？ [Conflict, plan.md vs spec.md]
- [x] CHK037 - research.md 决策"使用 YAML 配置"与 contracts/config-schema.md 一致，但 quickstart.md 中 `config.example.yaml` 是否完整反映所有 schema 字段？ [Traceability]
- [x] CHK038 - tasks.md 中 T003 创建 venv、T006 Dockerfile 和 T008 entrypoint.sh——Docker 内是否使用 venv 还是直接 pip install？plan 和 research 中这两个路径是否一致？ [Conflict]

## 边界情况 & 异常流程

- [x] CHK039 - "多容器实例同时运行"边缘情况在 spec 中列为关注点，但 FR 中无实例锁/互斥机制——是明确接受风险还是遗漏？ [Gap, Spec Edge Cases]
- [x] CHK040 - "iCloud 会话被用户手动撤销"——spec Edge Cases 提到但 FR-007 仅覆盖"过期检测"，是否区分"过期"与"撤销"两种状态？ [Gap, Spec Edge Cases]
- [x] CHK041 - "网络长时间中断后恢复"——spec Edge Cases 提到但 FR-011 仅覆盖断点续传，中断期间 iCloud 端的增量变更是否可被正确检测？ [Coverage, Spec Edge Cases]
- [x] CHK042 - "本地磁盘空间不足"——spec Edge Cases 提到且 FR-017 包含"空间不足"事件，但下载前是否有预检机制（预留空间 / 最小可用空间阈值）？ [Gap, Spec Edge Cases]
- [x] CHK043 - 首次运行（空本地目录）与第 N 次运行的差异行为是否在 spec 中有明确区分？ [Coverage]

## Notes

- 所有 CHK 项均测试**需求质量**，不测试实现行为
- [Gap] 标记表示规范中疑似遗漏；[Clarity] 表示需求存在但不够精确
- 建议在 `/speckit-implement` 前逐项 review，对 [Gap] 项做出决策（补充 spec / 明确排除 / 推迟到 v2）

---

## 补充：CHK034–038 决议跟进（venv 策略）

> 决议：开发环境使用 venv，Docker 容器内不使用 venv。

- [x] CHK044 - plan.md §Constitution Check 中 "II. Python venv: ✅ PASS" 是否明确区分了开发环境(venv)与 Docker 环境(pip install directly)？ [Consistency, plan.md]
- [x] CHK045 - research.md §6 Docker 镜像选型中提到 `python:3.11-slim` 应直接 pip install 依赖，是否与 tasks.md T003 (创建 venv) 和 T008 (entrypoint.sh) 的 Docker 内依赖安装策略一致？ [Conflict, research.md vs tasks.md]
- [x] CHK046 - quickstart.md "Docker 构建与运行" 一节中是否反映了 Docker 内无 venv 的设计？Dockerfile 的 pip install 步骤是否明确？ [Consistency, quickstart.md]
- [x] CHK047 - contracts/config-schema.md 中是否需要补充 Docker 运行时 pip 依赖列表（与 requirements.txt 的关系）？ [Gap, contracts/]

---

## 补充：CHK016 决议跟进（限流策略参考 docker-icloudpd）

> 决议：参考 docker-icloudpd 的限流/延迟策略。docker-icloudpd 使用 `download_delay` 配置项 + 固定间隔 sleep，而非自适应降速。

- [x] CHK048 - FR-012a 当前要求"自适应降速至 50%"，是否需修改为与 docker-icloudpd 一致的固定延迟策略（`download_delay` 可配间隔 + 失败后固定间隔重试）？ [Conflict, Spec §FR-012a vs docker-icloudpd reference]
- [x] CHK049 - 若采用 docker-icloudpd 的固定延迟模式，FR-012a 的"持续自适应调整直到限流解除"措辞是否需要重写为"下载间隔 + 重试等待"？ [Clarity, Spec §FR-012a]
- [x] CHK050 - contracts/config-schema.md 中是否需要新增 `download_delay`（下载间延迟秒数）和 `retry_interval`（失败重试间隔秒数）配置项，替代/补充当前的隐式限流策略？ [Completeness, contracts/config-schema.md]
- [x] CHK051 - tasks.md T053 "Add rate limiting adaptive logic" 是否需要重写为 "Add fixed-delay download throttling (docker-icloudpd pattern)"？ [Consistency, tasks.md]
- [x] CHK052 - research.md §7 同步引擎设计中是否记录了 docker-icloudpd 的 `download_delay` + sleep 模式作为限流参考实现？ [Traceability, research.md]
