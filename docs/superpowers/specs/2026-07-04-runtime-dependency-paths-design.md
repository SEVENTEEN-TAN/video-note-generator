# 本地运行时依赖路径配置设计

## 概要

当前本地 Faster Whisper 运行时把几类路径混在一起展示：外部 Python 路径、Python 包安装位置、worker 实际 import 路径、Faster Whisper 模型缓存目录。常规环境下可以工作，但当用户修改 pip 安装目标、用户级 site-packages、HuggingFace 缓存目录或模型缓存目录时，容易出现“安装成功但检测失败”或“本机已有模型但应用仍提示下载”的误判。

本设计采用“自动检测 + 用户可配置覆盖”的方案。应用继续保留现有默认行为，但在本地设置中允许用户显式指定外部 Python 路径和 Faster Whisper 模型目录，并在运行环境检测中展示实际使用的路径和错误原因。对于 pip 安装路径，先提供低风险的 `--user` 安装模式和诊断信息；不默认支持任意 `--target`，避免安装后 worker 不自动 import 的问题。

## 目标

- 让用户可以在 UI 中配置外部 Python 路径，等价于 `VIDEO_NOTE_PYTHON_PATH`。
- 让用户可以在 UI 中配置 Faster Whisper 模型目录，等价于 `FASTER_WHISPER_MODEL_DIR`。
- 环境变量继续拥有最高优先级，便于脚本、桌面包和高级用户覆盖。
- 依赖安装、运行时检测、模型下载、任务启动校验必须使用同一套路径解析逻辑。
- 运行环境卡片和设置页展示当前实际使用的 Python、模型目录、worker 路径、CUDA DLL 搜索目录和主要 import 错误。
- pip 安装支持默认模式和 `--user` 模式；安装完成后以 worker runtime status 作为真实成功依据。

## 非目标

- 不创建或管理内置虚拟环境。
- 不自动迁移用户已有 HuggingFace 缓存。
- 不支持任意 pip `--target` 的 UI 配置。自定义 target 需要额外处理 `PYTHONPATH`，当前先避免引入半可用状态。
- 不重做设置页布局，只在现有本地转写配置附近增加高级路径区域。

## 配置优先级

新增一个集中式运行时配置读取层，优先级如下：

1. 环境变量：`VIDEO_NOTE_PYTHON_PATH`、`FASTER_WHISPER_MODEL_DIR`。
2. 本地 settings/config 中保存的用户配置。
3. 现有默认值：PATH 中的 Python，以及 app data 下的 `backend/models/faster-whisper`。

这个优先级必须在后端统一使用，不能让不同模块分别读取不同来源。

## 后端设计

扩展 settings 模型，新增字段：

- `external_python_path: str = ""`
- `faster_whisper_model_dir: str = ""`
- `python_package_install_mode: "default" | "user" = "default"`

新增或调整运行时路径 helper：

- `get_configured_external_python_path()`：返回环境变量或 settings 中的 Python 覆盖。
- `get_configured_model_root()`：返回环境变量或 settings 中的模型目录覆盖。
- `get_python_package_install_args(mode)`：默认返回空列表，`user` 返回 `["--user"]`。

调整调用方：

- `transcription.find_external_python()` 使用统一配置读取。
- `runtime_paths.get_model_root()` 或 `transcription.get_faster_whisper_model_root()` 使用统一模型目录读取。
- `model_downloads` 下载到同一个模型目录。
- `runtime_status` 返回 `configured_by` 信息，说明 Python 和模型目录来自环境变量、settings 还是默认值。
- `PackageInstallController` 按 settings 中的安装模式拼接 pip 参数，并在安装完成后由前端刷新 `/api/runtime` 确认 worker 是否真正可用。

为避免循环导入，配置 helper 应放在 settings 或单独的小模块中，路径模块和 transcription 模块都可以依赖它。

## 前端设计

在设置弹窗的本地 Faster Whisper 区域增加一个“高级本地路径”区域：

- 外部 Python 路径输入框，提示示例：`C:\Users\...\python.exe`。
- Faster Whisper 模型目录输入框，提示该目录应包含 `small` 或 HuggingFace cache 结构。
- pip 安装模式下拉：`默认`、`用户目录 (--user)`。
- 保存设置后刷新运行环境检测。

运行环境卡片继续保持紧凑，但展示更有诊断价值的文本：

- 外部 Python：实际路径和来源。
- 模型目录：实际路径、来源、已发现模型。
- Python 包依赖：worker 是否能 import `faster_whisper` 和 `ctranslate2`。
- CUDA：检测到的 DLL 搜索目录和错误。

## 错误处理

- 用户配置的 Python 路径不存在或不可执行时，runtime status 返回明确错误，依赖安装按钮禁用或安装请求返回 400。
- 用户配置的模型目录不存在时不视为致命错误；提示未发现模型，并允许下载到该目录。
- pip 安装返回成功但 worker 仍无法 import 时，不显示“环境已就绪”，而显示安装完成但检测仍失败的 worker 错误。
- 环境变量覆盖 settings 时，UI 显示“由环境变量覆盖”，避免用户以为保存设置没有生效。

## 测试计划

后端测试：

- settings 中的外部 Python 路径会被 `find_external_python()` 使用。
- 环境变量优先于 settings 中的外部 Python 路径。
- settings 中的模型目录会被 runtime status、模型下载状态和任务校验共同使用。
- 环境变量优先于 settings 中的模型目录。
- pip 安装模式为 `user` 时，安装命令包含 `--user`。
- runtime status 返回路径来源和 worker import 错误。

前端验证：

- `npm --prefix frontend run build` 通过。
- 设置页能保存并回显高级路径字段。
- 保存后运行环境检测刷新，显示实际 Python 和模型目录。

## 验收标准

- 用户不设置任何高级路径时，现有默认流程不变。
- 用户保存外部 Python 路径后，检测、依赖安装和 worker 调用都使用同一个 Python。
- 用户保存模型目录后，模型检测、模型下载和本地任务启动校验都使用同一个目录。
- 当环境变量覆盖 settings 时，UI 能清楚显示覆盖来源。
- 安装依赖的成功状态不再等同于 worker 可用；最终可用性以 runtime status 为准。
