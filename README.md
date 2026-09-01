# 视频笔记生成器 MVP

本项目是一个本地运行的 `React + FastAPI` 视频笔记生成工具。上传视频后，后端会抽取 MP3、生成带时间戳字幕、调用模型生成结构化笔记，并根据笔记关键时间点抽取视频关键帧，最终输出 Markdown 和 ZIP。

完整处理链路、模块职责、人工确认门和产物契约见 [`docs/architecture.md`](docs/architecture.md)。

## 运行方式

### 开发环境一键初始化

在 PowerShell 中执行：

```powershell
.\scripts\init-dev.ps1 -Verify
```

脚本会创建 `.venv`、安装后端与本地 Faster Whisper 依赖、安装前端依赖，并验证后端测试和前端生产构建。项目通过 `imageio-ffmpeg` 提供可用的 FFmpeg，因此开发环境不要求系统 `PATH` 中预装 FFmpeg。

### Windows 桌面版 EXE

构建桌面版：

```powershell
.\scripts\build-desktop.ps1
```

构建完成后运行：

```powershell
.\dist\VideoNoteGenerator\VideoNoteGenerator.exe
```

桌面版会启动内置 FastAPI 服务并打开一个本地 UI 窗口。`outputs/`、本地配置和 Faster Whisper 模型缓存会写到 exe 所在目录旁边；API Key 不会写入任务产物，只有用户点击“保存设置”时才会使用当前 Windows 用户的 DPAPI 加密后写入本地配置文件。

默认桌面包走轻量策略：不把 Faster Whisper 模型文件打进包里，也不强行收集 `faster-whisper`、`ctranslate2`、`av`、`numpy` 等本地 ASR 大依赖。若桌面包内没有本地 ASR 依赖，程序会尝试调用系统 Python 里的外部 worker。用户可自行安装：

```powershell
python -m pip install -r backend/requirements.txt
```

如需把 `small` 模型也复制进桌面包：

```powershell
.\scripts\build-desktop.ps1 -BundleSmallModel
```

如果使用默认轻量包且选择“本地 Faster Whisper”，程序会先检查 exe 旁边是否存在本地模型。默认路径是：

```text
dist\VideoNoteGenerator\backend\models\faster-whisper
```

支持两种目录结构：扁平目录 `small\config.json`、`small\model.bin` 等，或 HuggingFace cache 目录 `models--Systran--faster-whisper-small\snapshots\...`。缺模型时 UI 会询问是否下载；只有用户点击下载后才会联网，生成任务本身不会偷偷下载模型。

### 后端

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

### 前端

```powershell
npm --prefix frontend install
npm --prefix frontend run dev
```

打开 Vite 输出的本地地址。前端会把 `/api` 请求代理到 `http://127.0.0.1:8000`。

后端 Pydantic 模型或 FastAPI 路由变化后，重新导出 OpenAPI 并生成前端 API 类型：

```powershell
.\scripts\generate-api-types.ps1
```

`npm --prefix frontend run build` 会先检查 `frontend/src/api.generated.ts` 是否与已导出的 `frontend/openapi.json` 一致；后端测试还会检查导出的 OpenAPI 是否与当前 FastAPI 应用一致。

## 使用说明

1. 上传视频文件。
2. 选择字幕转写来源：本地 Faster Whisper 或远端 API。
3. 按需修改 Base URL、模型名、笔记语言和关键帧数量；只有远端字幕转写需要在创建任务时提供字幕 API Key。
4. 点击开始生成，等待字幕完成并检查或修正字幕。
5. 确认字幕时再提供笔记生成 API Key，随后生成结构化笔记、关键帧和复核资料。
6. 复核笔记与候选帧并定稿，然后下载产物。
7. 可点击“保存设置”把 Base URL、模型、风格和 API Key 保存到本地配置文件。

每次选择视频并开始生成会创建一个独立任务；同一任务可以通过“重新生成笔记”产生多个笔记版本。历史任务可在界面中重新载入或删除，删除任务会同时删除该任务下的所有笔记版本。

## 模型配置

界面会明确列出不同功能实际使用的模型：

- 字幕转写：默认使用本地 `Faster Whisper`，模型为 `small`。运行环境卡片会检测 FFmpeg、本地 Faster Whisper、外部 Python worker 和本地模型目录。不需要字幕转写 API Key。新安装默认自动选择 CPU/CUDA 与合适精度；CPU 通常使用 `int8`，CUDA 通常使用 `float16`。普通电脑建议先用 `small`；更高准确率可选 `medium` 或 `large-v3`，但会更慢、占用更高。
- 远端字幕转写：可切换到 `Audio Transcriptions 端点`，默认模型 `whisper-1`，默认 Base URL 为 `https://api.openai.com/v1`。模型需要支持 audio transcriptions 和 segment 级时间戳。如果兼容服务没有 `/audio/transcriptions`，可切换到 `Chat 多模态音频兜底`。
- 笔记生成：默认 `gpt-5.5`，默认 Base URL 为 `https://api.openai.com/v1`。任务创建阶段只保存笔记偏好，不要求笔记凭据；用户确认字幕时才提交笔记 API Key。如果使用 Qwen，可把 Base URL 改为 `https://dashscope.aliyuncs.com/compatible-mode/v1`，模型名改为 `qwen-plus` 或其他兼容模型。
- 音频分离：使用 FFmpeg，不调用 AI 模型。
- 关键帧抽取：使用 FFmpeg 和笔记模型返回的关键时间点，不单独调用视觉模型。

任务运行时的 API Key 不写入 `outputs/`、`metadata.json` 或日志，也不会进入 ZIP。若用户点击 UI 里的“保存设置”，Windows 版会把 API Key 使用当前 Windows 用户作用域的 DPAPI 加密后写入本机 `config/settings.json`；复制到其他 Windows 用户或其他电脑后不能直接解密。旧版明文设置仍可读取，并会在下一次保存时迁移到加密格式。本地 Faster Whisper 模式没有字幕转写 API Key。

### 上传大小与磁盘空间

后端会在解析 multipart 请求前检查 `Content-Length`，并在实际复制视频/SRT 时再次按读取字节数校验。任务创建和帧数建议使用相同的流式复制规则；超限返回 `413`，空间不足返回 `507`，失败时会清理尚未注册的任务目录或临时目录。

默认限制：

- 视频：20 GiB
- SRT：16 MiB
- 上传完成后保留空间：256 MiB

可通过环境变量按字节调整：

```powershell
$env:VIDEO_NOTE_MAX_VIDEO_UPLOAD_BYTES = "21474836480"
$env:VIDEO_NOTE_MAX_SUBTITLE_UPLOAD_BYTES = "16777216"
$env:VIDEO_NOTE_UPLOAD_MIN_FREE_BYTES = "268435456"
```

视频和字幕上限必须大于零，保留空间可以设为零。无效值会作为运行配置错误返回，不会静默退回其他限制。

### 本地 Faster Whisper CUDA 加速

设置弹窗里的“字幕转写配置”可以选择本地 Faster Whisper 的运行设备和计算精度：

- CPU：兼容优先，推荐 `int8`。
- CUDA GPU：NVIDIA 显卡加速，推荐 `float16`，显存紧张时可试 `int8_float16`。

本机需要 NVIDIA 驱动和可用的 CTranslate2 CUDA 环境。设置页的“运行环境”会显示是否检测到 CUDA 设备，以及 cuBLAS/cuDNN 运行库是否能被外部 Python worker 加载。

如果 CUDA 设备可见，但任务报 `cublas64_12.dll is not found or cannot be loaded`，说明 NVIDIA 驱动存在，但 CUDA 推理运行库缺失。可在外部 Python 环境中安装：

```powershell
python -m pip install -r backend/requirements-cuda.txt
```

也可以在设置页的“字幕转写配置”中点击“安装 CUDA 加速依赖”，程序会调用当前检测到的外部 Python 执行同等安装。安装后重启后端或刷新运行环境检测；worker 会自动把 Python 包里的 `nvidia/*/bin` 加到 DLL 搜索路径。

也可以在启动后端前用环境变量覆盖旧版/脚本运行场景。默认配置优先保证 Windows CPU 可用：

```powershell
$env:FASTER_WHISPER_DEVICE="cpu"
$env:FASTER_WHISPER_COMPUTE_TYPE="int8"
```

如果你确认本机 CUDA/CTranslate2 运行库可用，可以在启动后端前改成：

```powershell
$env:FASTER_WHISPER_DEVICE="cuda"
$env:FASTER_WHISPER_COMPUTE_TYPE="float16"
```

也可以通过 `FASTER_WHISPER_MODEL_DIR` 指定模型缓存目录。

### 本地转写性能档位、进度与断点恢复

本地 Faster Whisper 提供三个实用档位：

- `快速`：使用更轻的解码参数，适合先快速获得可检索字幕。
- `均衡`：默认档位，在速度与准确率之间折中。
- `准确`：增加解码搜索，适合术语较多或音质较差的视频，但耗时更长。

超过 30 分钟的本地音频会按时长自动分块。公开 MP3 与 16 kHz 单声道 FLAC 转写输入由 FFmpeg 从源视频一次生成，避免先编码 MP3、再从 MP3 二次解码造成额外耗时和质量损失。内部 Faster Whisper 和外部 Python worker 都会在一次任务中只加载一次模型，并逐块写入原子断点结果。

界面会显示已处理时长、完成分块数、实际设备/精度、缓存复用块数和预计剩余时间。取消或程序异常中断后，只要源视频和本地工作目录仍存在，任务会显示“继续转写”；恢复时会复用与当前模型、语言、性能档位、音频文件完全匹配的已完成分块。

每个后台处理操作还会在任务目录写入不含密钥的 `.operation.json`。程序重启后会自动恢复本地分块转写、已上传字幕解析，以及已经生成笔记后的候选帧和质量报告阶段。远端转写或 AI 笔记调用中断时，应用会保留操作阶段并等待用户重新提交对应服务凭据；API Key 不会写入任务目录。

同一输出目录下的多个应用实例通过 `outputs/.runtime/coordination.sqlite3` 中的任务 lease 协调写操作。后台处理、人工复核修改、版本切换、定稿和删除不能同时修改同一个任务；lease 使用心跳、owner token 和递增 revision，程序异常退出后可由后续实例接管。原子文件写入、目录切换、笔记版本、候选帧、定稿和 ZIP 发布在提交前都会重新校验当前 owner 与 fencing revision，已经被新实例接管的旧任务不能继续发布迟到结果。FFmpeg 和转写取消轮询也会周期性检查 lease，以便旧执行尽快停止。取消请求仍通过任务 marker 跨进程传播，因此从另一个应用实例发起取消也能被当前执行进程观察到。

关键帧复核会显示重复风险、静态画质、场景稳定度以及相对字幕语义锚点的时间偏移。系统会在每个锚点前后约 1 秒内批量采样低分辨率灰度帧，通过邻帧差异避开转场和快速动画，再抽取高清候选图。画质和稳定度都由本地 FFmpeg 输出的灰度像素计算，不上传图片，也不新增视觉模型依赖；系统会标记黑屏、白屏、画面偏暗、过曝、低对比度、疑似模糊和转场风险，并优先选择无严重风险、稳定且非重复的候选帧。采样失败时会回退原语义时间，不影响任务继续处理。

每个笔记版本同时保存结构化 `draft.json` 和字幕 `evidence.json`。候选帧章节和人工复核稿优先从这些结构化文件构建，只有缺少草稿的旧任务或手工版本才兼容解析 Markdown。人工复核稿还会为每段保存字幕 Segment ID 和字幕指纹；用户编辑正文后，界面和质量报告会重新检查该段未在字幕原文出现的数字和技术标识，并按用户实际选择的帧计算配图质量。定稿后仍保留最终正文指纹，因此质量报告检查的是实际交付正文，而不只是模型原始草稿。这是字幕证据一致性检查，用于发现数字或版本号被模型改写的风险，不代表外部事实核验。

运行环境状态按能力显示。本地 Faster Whisper、CUDA、本地模型、远端 Audio Transcriptions、Chat Audio 和上传字幕流程分别判断；未安装本地转写依赖不会再让远端转写模式显示为整个应用不可用。

取消行为有两种：外部 Python worker 会被主动终止；应用进程内的 Faster Whisper 采用协作式取消，会在读取下一段解码结果前停止，因此极少数情况下可能需要等待当前底层解码步骤返回。若外部进程在 Windows 上无法立即回收，其输出会保留在独立会话目录，不会覆盖正式断点，并且同一任务在旧进程退出前不会启动第二个外部 worker。

如需释放空间，可以删除不再需要的整个任务目录。`work/asr/` 属于可恢复转写的本地缓存；删除它不会影响已经生成的最终字幕和笔记，但会失去分块续转能力。

## 产物

每个任务会生成到 `outputs/{job_id}/`：

- `audio.mp3`
- `transcript.json`
- `subtitles.srt`
- `subtitles.vtt`
- `subtitles.md`
- `frames/*.jpg`
- `note.md`
- `note_versions/{id}/draft.json`
- `note_versions/{id}/evidence.json`
- `note_versions/{id}/review/review_draft.json`
- `metadata.json`
- `download.zip`

`download.zip` 是面向使用和分享的最终结果包，不包含 `debug.log` 或 `debug/` 中的模型原始响应。任务停止后可以从结果区显式下载 `diagnostics.zip`；诊断包包含调试日志、模型原始响应、任务状态快照、operation 状态、质量报告和本地转写 checkpoint manifest，用于排查失败，不应作为普通笔记成果分享。

## 限制

- 大音频会自动切片转写，避免触发单文件上传限制。
- 超长字幕会分块生成局部笔记，再合并为最终笔记，避免把完整字幕一次性塞进模型浪费 Token。
- 字幕时间戳默认使用本地 Faster Whisper；切换到远端模式后，Base URL 和模型名可以在 UI 中手动修改。
- Qwen 等国产模型建议用于“笔记生成”配置；只有当对应服务兼容 OpenAI audio transcriptions 且支持时间戳时，才适合替换“字幕转写”配置。若它只支持 Chat 多模态音频，可选择 `Chat 多模态音频兜底`，但时间戳精度通常弱于标准转写端点，成本也可能更高；后端会继续按 120 秒音频分片发送，避免单次请求过大。
- 首版是本地单用户工具，不做登录、多用户队列或云同步。
