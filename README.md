# 视频笔记生成器 MVP

本项目是一个本地运行的 `React + FastAPI` 视频笔记生成工具。上传视频后，后端会抽取 MP3、生成带时间戳字幕、调用模型生成结构化笔记，并根据笔记关键时间点抽取视频关键帧，最终输出 Markdown 和 ZIP。

## 运行方式

### Windows 桌面版 EXE

构建桌面版：

```powershell
.\scripts\build-desktop.ps1
```

构建完成后运行：

```powershell
.\dist\VideoNoteGenerator\VideoNoteGenerator.exe
```

桌面版会启动内置 FastAPI 服务并打开一个本地 UI 窗口。`outputs/`、本地配置和 Faster Whisper 模型缓存会写到 exe 所在目录旁边；API Key 不会写入任务产物，只有用户点击“保存设置”时才会写入本地配置文件。

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
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

### 前端

```powershell
cd frontend
npm install
npm run dev
```

打开 Vite 输出的本地地址。前端会把 `/api` 请求代理到 `http://127.0.0.1:8000`。

## 使用说明

1. 上传视频文件。
2. 选择字幕转写来源：本地 Faster Whisper 或远端 API。
3. 临时输入笔记生成 API Key；只有远端字幕转写才需要字幕 API Key。
4. 按需修改 Base URL 和模型名。
5. 可点击“保存设置”把 Base URL、模型、风格和 API Key 保存到本地配置文件。
6. 选择笔记语言和关键帧数量。
7. 点击开始生成，等待任务完成后下载产物。

## 模型配置

界面会明确列出不同功能实际使用的模型：

- 字幕转写：默认使用本地 `Faster Whisper`，模型为 `small`。运行环境卡片会检测 FFmpeg、本地 Faster Whisper、外部 Python worker 和本地模型目录。不需要字幕转写 API Key。CPU 默认使用 `int8` 推理，普通电脑建议先用 `small`；更高准确率可选 `medium` 或 `large-v3`，但会更慢、占用更高。
- 远端字幕转写：可切换到 `Audio Transcriptions 端点`，默认模型 `whisper-1`，默认 Base URL 为 `https://api.openai.com/v1`。模型需要支持 audio transcriptions 和 segment 级时间戳。如果兼容服务没有 `/audio/transcriptions`，可切换到 `Chat 多模态音频兜底`。
- 笔记生成：默认 `gpt-5.5`，默认 Base URL 为 `https://api.openai.com/v1`。如果使用 Qwen，可把 Base URL 改为 `https://dashscope.aliyuncs.com/compatible-mode/v1`，模型名改为 `qwen-plus` 或其他兼容模型。
- 音频分离：使用 FFmpeg，不调用 AI 模型。
- 关键帧抽取：使用 FFmpeg 和笔记模型返回的关键时间点，不单独调用视觉模型。

任务运行时的 API Key 不写入 `outputs/`、`metadata.json` 或日志，也不会进入 ZIP。若用户点击 UI 里的“保存设置”，API Key 会以明文 JSON 写入本机 `config/settings.json`，适合单机自用，不适合共享电脑。本地 Faster Whisper 模式没有字幕转写 API Key。

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

## 产物

每个任务会生成到 `outputs/{job_id}/`：

- `audio.mp3`
- `transcript.json`
- `subtitles.srt`
- `subtitles.vtt`
- `subtitles.md`
- `frames/*.jpg`
- `note.md`
- `metadata.json`
- `download.zip`

## 限制

- 大音频会自动切片转写，避免触发单文件上传限制。
- 超长字幕会分块生成局部笔记，再合并为最终笔记，避免把完整字幕一次性塞进模型浪费 Token。
- 字幕时间戳默认使用本地 Faster Whisper；切换到远端模式后，Base URL 和模型名可以在 UI 中手动修改。
- Qwen 等国产模型建议用于“笔记生成”配置；只有当对应服务兼容 OpenAI audio transcriptions 且支持时间戳时，才适合替换“字幕转写”配置。若它只支持 Chat 多模态音频，可选择 `Chat 多模态音频兜底`，但时间戳精度通常弱于标准转写端点，成本也可能更高；后端会继续按 120 秒音频分片发送，避免单次请求过大。
- 首版是本地单用户工具，不做登录、多用户队列或云同步。
