# 可用性与稳定性改进设计

## 概要

本阶段目标是提高当前“本地优先视频笔记生成器”的可用性和实用性，同时不改变产品定位、不重做视觉风格、不扩大成云端产品。已经批准的第一阶段范围是 **B：稳定性 BUG + 现有功能补充**。

这批改动要解决两类问题：

- 后端真实风险：任务路径安全、笔记版本路径信任、损坏版本索引、CUDA 未就绪误放行、创建任务失败后留下孤儿目录。
- 前端使用体验：开始前不知道能不能跑、长任务看起来像卡住、失败后不知道还能利用哪些产物、下载产物不完整、笔记版本信息不够可读。

产品仍然是单用户本地工作台：上传视频、转写音频、生成结构化笔记、抽关键帧、管理历史任务和笔记版本、下载本地产物。本阶段不做登录、云同步、多人协作、多用户队列，也不重做 UI 设计系统。

## 当前依据

- 后端是 FastAPI，任务产物按 `outputs/{job_id}` 写入磁盘。
- 前端是 Vite + React，主要集中在 `frontend/src/App.tsx`，样式在 `frontend/src/styles.css`。
- 后端测试当前可通过：`python -m pytest backend/tests`。
- 前端生产构建当前可通过：`npm --prefix frontend run build`。
- 已复现一个真实路径安全 BUG：把编码后的 `.` 作为 job id 请求时，会解析到整个 `outputs` 根目录，并可通过删除接口删除该根目录。
- 三个子 Agent 的只读审计结论集中在：后端路径与版本索引加固、长任务进度清晰度、首次运行检查、失败恢复、产物下载入口、版本管理可见性。

## 已批准范围

### 1. 代码 BUG 优化

#### 任务 ID 路径安全

`safe_job_dir()` 必须拒绝会解析到 `OUTPUTS_ROOT` 根目录、父目录、路径分隔符、空段、`.`、`..` 的 job id。合法 job id 只能解析为 `OUTPUTS_ROOT` 下的一个直接子目录。

涉及文件：

- `backend/app/main.py`
- `backend/tests/test_job_validation.py`，或新建一个更聚焦的后端测试文件

必须满足：

- `GET /api/jobs/%2E` 返回客户端错误，不能把 `outputs` 根目录当成历史任务载入。
- `DELETE /api/jobs/%2E` 不能删除 `OUTPUTS_ROOT`。
- 正常生成的 job id 和已有单目录历史任务继续可用。

#### 笔记版本路径安全与损坏索引降级

`note_versions/versions.json` 里的路径不能被当成可信路径直接使用。载入或使用笔记版本时，必须拒绝或忽略逃出任务目录的路径。损坏或非法的 `versions.json` 不能导致整个历史列表接口失败。

涉及文件：

- `backend/app/note_versions.py`
- `backend/app/processor.py`
- `backend/app/job_store.py`
- `backend/tests/test_note_versions.py`
- `backend/tests/test_job_history.py`

必须满足：

- 用于 ZIP 目录名的版本 id 是安全的单段路径名。
- `note_path` 和 `frame_dir` 必须按任务目录内的相对路径解析，不能指向任务目录外。
- 损坏的 `versions.json` 在历史列表和载入场景中降级为空版本索引。
- 激活版本或打包 ZIP 时，恶意版本索引不能复制外部文件，也不能把外部文件写入 ZIP。
- 正常的版本创建、激活、选择、ZIP 打包行为保持兼容。

#### 版本索引和 ZIP 原子写入

版本索引和 ZIP 写入要避免中断时留下半截文件。当前阶段重点处理版本相关的 `versions.json` 和 `download.zip`，因为它们会在版本切换、重新生成、选择 ZIP 内容时反复写入。

涉及文件：

- `backend/app/note_versions.py`
- `backend/app/processor.py`
- 版本索引和 ZIP 创建相关测试

必须满足：

- `versions.json` 先写临时文件，再原子替换最终文件。
- `download.zip` 先写临时文件，再原子替换最终文件。
- ZIP 重建失败时，不留下一个看似可下载的新坏包。

#### CUDA 就绪保护

当用户选择本地 Faster Whisper 且设备为 CUDA 时，不能只因为 CPU 可用就放行任务。前端应在提交前阻止明显会失败的 CUDA 任务，后端也要在 API 层拒绝 CUDA runtime 未就绪的任务。

涉及文件：

- `frontend/src/App.tsx`
- `backend/app/main.py`
- 必要时可在 `backend/app/runtime_status.py` 增加小 helper
- 后端校验测试

必须满足：

- 如果 `local_whisper_device === "cuda"`，但运行状态显示 CUDA 不可用，前端主提交路径要显示明确提示，不创建任务。
- 提示里要给现有恢复路径：去设置里安装 CUDA 依赖，或切回 CPU。
- 后端也要拒绝 CUDA runtime 缺失的本地转写任务，保证绕过 UI 直接调 API 时同样安全。
- CPU 本地转写行为不变。

#### 创建任务前先完成校验

`create_job()` 应先构造并验证 `JobConfig`，再创建任务目录和复制上传文件。若文件复制或 metadata 写入阶段失败，应尽量清理这次新建的任务目录。

涉及文件：

- `backend/app/main.py`
- 后端校验测试

必须满足：

- `extras` 超长、本地 Whisper 运行参数非法、其他 `JobConfig` 校验失败时，不留下孤儿任务目录。
- 上传复制失败时返回明确 HTTP 错误，并清理本次新建目录。
- 成功创建任务和初始 metadata 写入行为保持不变。

### 2. 现有功能性补充

#### 开始前检查摘要

主配置面板的提交按钮附近增加一个紧凑的“开始前检查”。它只使用已有状态，不新增重量级轮询。

检查项：

- 后端是否连接。
- FFmpeg 是否可用。
- 本地 Faster Whisper 模式下：CPU 是否就绪、选中的模型是否存在、选择 CUDA 时 CUDA 是否就绪。
- 笔记 API Key 是否已填写。
- 远端转写模式下，转写 API Key 是否已填写。

行为：

- 摘要在提交前可见。
- 每项尽量给直接操作：打开设置、下载模型、安装本地/CUDA 依赖、切换到 CPU。
- 不显示 API Key 明文。

#### 长任务进度更清晰

进度区域要显示当前后端步骤、百分比、当前阶段耗时。步骤高亮不能只依赖中文文案完全相等。

涉及文件：

- `frontend/src/App.tsx`
- `frontend/src/styles.css`
- 如确实需要，也可给后端模型增加稳定 `stage` 字段；优先考虑前端根据 progress 和 step 前缀推导，减少后端接口变化。

行为：

- 分片转写时，即使后端步骤是 `字幕生成中：第 2/8 段转写中`，UI 仍然把“字幕生成”标为当前阶段。
- 用户能看到 `progress` 和 `stage_elapsed_seconds`。
- 失败任务能显示失败步骤和耗时。

#### 失败任务恢复面板

任务失败时，UI 不只显示错误文本，还要告诉用户哪些已生成产物还能用、下一步该怎么做。恢复建议从现有 artifacts 推导。

行为：

- 如果已有字幕或 `transcript.json`，显示下载动作，并允许在 `transcript.json` 存在时“只重新生成笔记”。
- 如果只有音频，显示音频下载，并说明需要重新转写。
- 如果没有可复用产物，显示“修复设置/依赖后重试完整任务”。
- 原始错误文本继续保留。

#### 完整产物下载

UI 要暴露所有已生成产物，同时保留常用下载按钮的效率。

行为：

- 顶部继续保留 Markdown、SRT、MP3、ZIP 快捷按钮。
- 增加“全部产物”区域，遍历 `job.artifacts`，包括 VTT、转写 JSON、metadata JSON、关键帧等。
- 下载继续复用现有浏览器/桌面下载逻辑。
- 桌面桥返回保存路径时显示“已保存到 ...”；浏览器模式显示“已触发下载”。

#### 笔记版本信息与 ZIP 选择显性化

后端已有版本元数据和 `selected_version_ids`，前端要把这些能力变成可用工作流，不做复杂 diff。

行为：

- 版本选项显示版本 id、风格、创建时间、模型、是否当前版本。
- 用户能看出哪些版本会进入 ZIP。
- 用户可以切换某个版本是否包含进 ZIP，且这个操作不改变当前预览版本。
- 当前版本仍然是写入根目录 `note.md` 和 `frames/` 的版本。
- 选择变化后沿用现有 PATCH 接口重建 ZIP。

### 3. 实用性新增功能候选

第一阶段不实现大型新工作流，但记录下一阶段最有价值的实用功能，后续单独设计和计划。

#### 字幕校正后重新生成笔记

用户价值：本地 Whisper 难免识别错专有名词。允许用户先修字幕，再重新生成笔记，可以提高最终笔记质量，同时避免重新转写视频。

未来形态：

- 保留原始 transcript 和字幕。
- 增加可编辑的字幕/转写视图，并校验时间戳格式。
- 保存一个修订后的 transcript 版本。
- 基于修订 transcript 重新生成新的笔记版本。

主要依赖：

- `backend/app/subtitles.py`
- `backend/app/note_versions.py`
- `backend/app/main.py`
- `frontend/src/App.tsx`

#### 时间戳联动本地视频预览

用户价值：点击笔记或字幕里的时间点，可以跳到原视频对应片段，方便校对和复习。

未来形态：

- 将原始视频作为该任务下的安全 asset 暴露。
- 把笔记/字幕里的时间戳解析成可点击控件。
- 点击后让本地视频预览跳到对应时间。

主要依赖：

- `backend/app/main.py`
- `backend/app/processor.py`
- `frontend/src/App.tsx`

## 架构方案

后端安全改动贴近现有路径和版本模块，不引入大而泛的抽象。只在能减少重复检查时增加小 helper：

- 任务目录校验 helper 放在 `main.py`，或在测试显示复用压力时再抽到小模块。
- 笔记版本路径解析 helper 放在 `note_versions.py`。
- 原子写入 helper 就近放在需要写文件的模块里。

前端继续沿用当前 `App.tsx` 和 `styles.css` 的工作台结构。本阶段不做组件大拆分。若新增面板导致可读性明显下降，可以在同一文件内抽小的纯渲染函数。

## 数据流

### 创建任务

1. 前端开始前检查读取现有 `health`、本地模型状态、转写模式、设备选择、API Key 是否填写。
2. 前端在明显不满足条件时阻止提交，例如 CUDA 未就绪。
3. 后端先把表单字段校验成 `JobConfig`。
4. 后端按需要检查本地模型和 CUDA runtime。
5. 校验成功后才创建任务目录并复制上传视频。
6. 后端写入初始 metadata，创建内存任务状态，并排入 `process_job`。

### 任务进度

1. 后端继续更新 `status`、`step`、`progress`、`step_started_at`、`updated_at`、`stage_elapsed_seconds`。
2. 前端按现有方式轮询任务状态。
3. 前端根据 progress 阈值和 step 前缀推导粗阶段高亮。
4. 前端把详细 `job.step` 和粗步骤列表分开显示。

### 笔记版本与 ZIP

1. 后端防御式加载版本索引。
2. 后端通过任务目录内安全路径解析版本 note 和 frame 路径。
3. 前端仍然通过现有接口获取版本列表。
4. 切换当前预览版本时，PATCH `active_version_id`。
5. 切换 ZIP 包含版本时，PATCH 更新后的 `selected_version_ids` 和当前 active version。
6. 后端原子重建 ZIP。

## 错误处理

- 非法 job id 返回客户端错误，永远不能解析到 `OUTPUTS_ROOT`。
- 非法版本元数据在使用时被忽略或拒绝，不能被信任。
- 损坏版本索引不能拖垮 `/api/jobs`。
- CUDA 未就绪给出可操作提示，不启动注定失败的转写任务。
- 创建任务失败时清理本次新建的局部目录。
- 失败任务继续通过现有 artifact 系统暴露已完成产物。

## 测试计划

### 后端

实现时先跑目标测试，再跑全量：

- `python -m pytest backend/tests/test_job_validation.py`
- `python -m pytest backend/tests/test_job_history.py`
- `python -m pytest backend/tests/test_note_versions.py`
- `python -m pytest backend/tests`

新增或更新测试覆盖：

- 编码后的点号 job id 不能载入或删除 outputs 根目录。
- 恶意版本路径不能逃出任务目录。
- 损坏 `versions.json` 不影响历史列表。
- ZIP 和版本索引原子写入后仍生成有效文件。
- CUDA runtime 未就绪时，本地 CUDA 转写任务被拒绝。
- 非法 `JobConfig` 输入不会留下孤儿任务目录。

### 前端

实现后运行：

- `npm --prefix frontend run build`

人工验证覆盖：

- 主界面开始前检查：缺 Key、缺模型、CPU 可用、CUDA 不可用、后端未连接。
- 长任务进度显示：详细 step、百分比、阶段耗时。
- 失败任务恢复面板：不同局部产物状态下的提示和动作。
- 全部产物列表和下载状态消息。
- 版本 ZIP 包含开关与当前预览版本切换。

## 不做的事

- 不做云同步、登录、账号、多用户队列。
- 不重做设计系统或首页。
- 本阶段不做源视频播放。
- 本阶段不做字幕编辑。
- 不大规模拆分 `frontend/src/App.tsx`。
- 不重做密钥存储；当前本地明文设置行为保留，并继续显示警告。

## 验收标准

- 使用 `.` 或编码点号作为 job id 时，不能载入、下载穿透或删除 outputs 根目录。
- 恶意或损坏的笔记版本元数据不能逃出任务目录，也不能拖垮历史列表。
- 版本索引和 ZIP 写入具备足够原子性，中断时不留下一个新公开的半写文件。
- CUDA 未就绪时不会启动 CUDA 任务，CPU 本地转写保持原行为。
- 非法任务配置在创建目录等副作用前被拦住。
- 主界面清楚显示开始前状态、长任务当前进度、失败恢复动作、全部产物、可读版本信息。
- 后端现有测试通过。
- 前端生产构建通过。
