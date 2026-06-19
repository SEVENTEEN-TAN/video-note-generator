# 视频笔记生成器 MVP 计划

## Summary

构建一个本地 `React + FastAPI` 工作台式 Web App：用户上传视频，按功能临时填写 OpenAI-compatible API Key、Base URL、模型名和输出语言，点击执行后生成并下载 4 类产物：原视频音频 MP3、带时间戳字幕、关键帧图片、带配图引用的 Markdown 视频笔记。

已确认的产品决策：

- UI：工作台式工具，不做营销页。
- 技术栈：React + FastAPI。
- 字幕策略：优先稳定时间戳，使用 OpenAI 音频转写的 segment 级时间戳。
- 模型配置：按功能使用 OpenAI-compatible API 格式填写 API Key、Base URL、模型名。
- API Key：字幕转写和笔记生成分别在界面临时输入，仅当前任务使用，不落盘。
- 笔记语言：UI 可选，例如中文、英文、跟随原文。

参考依据：

- OpenAI 官方文档说明音频转写支持 `timestamp_granularities[]`，可输出带时间戳结构化结果：[Speech to text](https://developers.openai.com/api/docs/guides/speech-to-text)。
- OpenAI 官方文档当前推荐新项目使用 `gpt-5.5`，并建议对结构化输出使用 schema：[Using GPT-5.5](https://developers.openai.com/api/docs/guides/latest-model)、[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)。
- 阿里云百炼官方文档说明 Qwen 支持 OpenAI 兼容接口，迁移时主要调整 API Key、BASE_URL 和模型名：[OpenAI compatible - Chat](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope)。

## Key Changes

- 创建 monorepo 结构：
  - `frontend/`：Vite + React + TypeScript，负责上传、配置、进度、预览和下载。
  - `backend/`：FastAPI，负责视频处理、OpenAI 转写、LLM 笔记生成、关键帧抽取和产物打包。
  - `outputs/`：运行时生成目录，按任务 ID 分组，默认不提交。
- 后端使用 Python 是因为 FastAPI、文件上传、后台任务、字幕/Markdown 生成都直接；前端使用 React 是因为后续做进度流、预览面板、可视化任务状态更自然。
- FFmpeg 不假设系统已安装。实现时优先在后端依赖里使用可携带的 FFmpeg 包或启动时探测：
  - 若检测不到可用 FFmpeg，后端返回明确错误，UI 显示“缺少视频处理依赖”。
  - 若可用，使用 FFmpeg 生成 MP3、按时间戳抽关键帧。
- UI 第一屏结构：
  - 顶部：应用名、任务状态、执行按钮。
  - 左侧配置区：视频上传、模型提供商、模型名、API Key、笔记语言、关键帧数量上限。
  - 中间进度区：音频分离、字幕生成、笔记生成、关键帧抽取、Markdown 输出。
  - 右侧结果区：Markdown 预览、字幕预览、关键帧缩略图、下载按钮。
- Product Design 后续执行约束：
  - 正式实现 UI 前，先用 `@product-design` 基于“工作台式视频笔记工具”生成 3 个视觉方向。
  - 用户选定一个视觉方向后，再按该方向实现前端，不临场发明配色、布局和组件风格。

## Processing Flow

- 上传视频：
  - 前端通过 `multipart/form-data` 上传视频和任务配置。
  - 后端创建 `job_id`，返回任务状态端点。
- 音频分离：
  - 使用 FFmpeg 从视频中提取 `audio.mp3`。
  - 同时用 `ffprobe` 或 FFmpeg 获取视频时长，用于进度和关键帧边界校验。
- 字幕生成：
  - 使用 OpenAI 音频转写接口，模型默认 `whisper-1`，`response_format=verbose_json`，`timestamp_granularities=["segment"]`。
  - 输出 `transcript.json`、`subtitles.srt`、`subtitles.vtt`、`subtitles.md`。
  - `subtitles.md` 格式为 `HH:MM:SS - HH:MM:SS 文本`，便于人工阅读和后续提示词引用。
- 笔记生成：
  - 后端使用 OpenAI-compatible Chat API：
    - 字幕转写配置：`transcription_mode`、`transcription_api_key`、`transcription_base_url`、`transcription_model`，默认 `audio_transcriptions` + `https://api.openai.com/v1` + `whisper-1`。
    - 若兼容服务没有 `/audio/transcriptions`，可使用 `chat_audio` 多模态音频兜底；该模式会分片发送音频并要求模型返回 JSON 字幕段，不做总时长硬限制。
    - 笔记生成配置：`note_api_key`、`note_base_url`、`note_model`，默认 `https://api.openai.com/v1` + `gpt-5.5`。
    - Qwen 或其他国产兼容模型可通过把 `note_base_url` 改为对应兼容地址、把 `note_model` 改为对应模型名来使用。
  - 先让模型基于带时间戳字幕生成结构化 JSON：
    - `title`
    - `summary`
    - `chapters[]`，包含标题、起止时间、要点、引用字幕时间
    - `key_moments[]`，包含时间点、配图理由、对应章节
    - `markdown_body`
  - 再由后端把 JSON 渲染为最终 Markdown，避免模型直接写错图片路径或文件名。
- 关键帧抽取：
  - 从 `key_moments[]` 中选最多 N 个时间点，默认 6 个。
  - 对每个时间点用 FFmpeg 抽取 `frames/frame_001.jpg` 等图片。
  - 若时间点太靠近视频开头/结尾，自动夹紧到合法范围。
  - Markdown 中插入相对路径图片引用，例如 `![关键帧 01](frames/frame_001.jpg)`。
- 下载产物：
  - 单独下载 Markdown、字幕、MP3。
  - 提供一键下载 ZIP，包含：
    - `note.md`
    - `audio.mp3`
    - `subtitles.srt`
    - `subtitles.vtt`
    - `subtitles.md`
    - `frames/*.jpg`
    - `metadata.json`

## Prompt Plan

- 系统提示词定位：
  - 你是专业的视频内容编辑、课程笔记整理师和知识管理专家。
  - 必须只依据字幕内容生成笔记，不编造视频中未出现的信息。
  - 必须保留可追溯的时间点，用于章节定位和关键帧抽取。
  - 输出应适合 Markdown 阅读，结构清楚，标题具体，不写空泛总结。
- 用户提示词输入：
  - 视频文件名、总时长、目标语言、字幕片段列表。
  - 可选偏好：简洁/详细、关键帧数量、是否偏课程笔记/会议纪要/教程复盘。
- 输出 schema：
  - 使用固定 JSON schema 或 Pydantic/Zod schema 校验。
  - 如果模型提供商不支持严格结构化输出，则用 JSON mode 风格提示词 + 后端 JSON parse + 一次重试。
- Markdown 模板：
  - 标题
  - 摘要
  - 目录
  - 分章节笔记，每节包含时间范围、关键帧、要点、详细说明
  - 关键结论
  - 可行动清单
  - 原始字幕链接或附录

## API Interfaces

- `POST /api/jobs`
  - 输入：视频文件、transcription_mode、transcription_api_key、transcription_base_url、transcription_model、note_api_key、note_base_url、note_model、note_language、frame_limit。
  - 输出：`{ job_id }`。
- `GET /api/jobs/{job_id}`
  - 输出：状态、当前步骤、进度百分比、错误信息、已生成产物列表。
- `GET /api/jobs/{job_id}/preview/note`
  - 输出：Markdown 文本预览。
- `GET /api/jobs/{job_id}/assets/{path}`
  - 输出：关键帧、字幕、音频等静态产物。
- `GET /api/jobs/{job_id}/download.zip`
  - 输出：完整结果 ZIP。
- 后端不会把 API Key 写入 `outputs/`、日志或 metadata；只保存在当前请求的内存上下文里。

## Error Handling

- 上传前端限制：
  - 支持常见视频格式：`mp4`、`mov`、`mkv`、`webm`、`avi`。
  - 大文件提示本地处理时间可能较长。
- 后端明确处理：
  - FFmpeg 不可用。
  - 视频无法解析或没有音轨。
  - API Key 缺失或认证失败。
  - 转写文件过大导致 API 拒绝：首版给出明确错误，不做自动切片；自动切片作为后续增强。
  - LLM 返回非法 JSON：自动重试一次，仍失败则保留字幕和音频产物，并显示笔记生成失败。
- 任务失败时保留已成功产物，UI 允许下载已有文件。

## Test Plan

- 后端单元测试：
  - 时间格式转换：秒数和 `HH:MM:SS,mmm` / `HH:MM:SS.mmm` 互转。
  - `verbose_json` segment 转 SRT/VTT/Markdown。
  - LLM JSON 转 Markdown，并正确插入图片相对路径。
  - 关键帧时间点夹紧逻辑。
- 后端集成测试：
  - 使用一个极短本地测试视频，验证 MP3、字幕文件、Markdown、关键帧、ZIP 都能生成。
  - Mock OpenAI/Qwen 响应，避免测试消耗 API 额度。
- 前端测试：
  - 上传表单校验。
  - Provider 切换时显示对应 API Key、模型名、BASE_URL 字段。
  - 任务状态轮询和失败态展示。
  - Markdown、字幕、关键帧预览组件渲染。
- 手工验收：
  - 用 1 个 1-3 分钟视频跑通完整流程。
  - 验证字幕时间存在、Markdown 图片可打开、ZIP 解压后相对路径有效。
  - 验证 API Key 不出现在日志、metadata、下载文件中。

## Assumptions

- 首版是本地单用户工具，不做登录、历史任务云同步、队列持久化或多用户并发隔离。
- 首版笔记内容主要依赖字幕，不做视频画面理解；关键帧只根据字幕时间点抽取。
- 首版默认不自动切分超大音频；如果转写 API 文件大小限制触发，给出明确错误和后续增强建议。
- 默认字幕时间戳来源是 OpenAI `whisper-1`；如果替换转写 Base URL/模型，需要该接口兼容 OpenAI audio transcriptions 且支持 segment 时间戳。
- Qwen 等国产模型建议用于笔记生成；除非对应服务兼容音频转写和时间戳，否则不要替换字幕转写模型。
- 生成目录默认可清理；后续可以加“保留最近 N 个任务”设置。
