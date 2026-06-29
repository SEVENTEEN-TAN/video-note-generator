# 字幕 AI 修正与差异确认设计

## 概要

本功能在当前“Main 原 UI + 后端稳定性修复”的基线上增加一个实用工作流：当本地 Faster Whisper 识别出专有名词错误时，用户可以在字幕预览旁点击“AI 修正字幕”，让笔记大模型基于原始转写文本做专有名词、英文产品名、缩写、术语和明显错别字修正。系统不会直接覆盖原始转写，而是先生成修正版草稿，展示左右两栏差异，用户确认后才采用修正版，并自动基于修正版 transcript 生成新的笔记版本。

目标是提升笔记质量，不重做整体 UI，不引入字幕手动编辑器，不做复杂多版本字幕管理。

## 推荐方案

采用“原始 transcript + 当前修正版 transcript + 采用确认”的中间方案。

- 保留 `transcript.json` 作为本地或远端转写的原始结果。
- 生成 `transcript.corrected.pending.json` 作为待确认修正草稿。
- 用户在双栏 diff 弹窗中确认后，写入 `transcript.corrected.json`。
- 采用修正版后重写 `subtitles.srt`、`subtitles.vtt`、`subtitles.md`，并自动生成新的笔记版本。
- 后续“重新生成笔记”优先使用 `transcript.corrected.json`，没有修正版时继续使用原始 `transcript.json`。

## 备选方案

### 直接覆盖原始 transcript

实现最简单，但大模型修错后不可回退，不适合处理专有名词这种不确定任务。

### 多版本 transcript 管理

每次修正都创建 `transcript_corrections/correction_001.json` 这类版本，长期能力更完整，但当前会带来更多 UI、选择状态和打包规则，超出这次“轻量新增实用功能”的目标。

## 用户流程

1. 用户完成一个任务，结果区已经显示字幕预览。
2. 字幕标题行旁出现“AI 修正字幕”按钮。
3. 点击后，前端调用后端修正接口，按钮进入 loading 状态。
4. 后端读取原始 `transcript.json`，调用笔记模型，要求只修正每段文本，必须保留段数和时间戳。
5. 后端写入待确认草稿 `transcript.corrected.pending.json`，返回原文和修正文段。
6. 前端打开差异确认弹窗：
   - 左栏：原始字幕文本。
   - 右栏：AI 修正字幕文本。
   - 变化行高亮；未变化行保持低调。
   - 顶部显示变更段数。
7. 用户点击“采用修正版”。
8. 后端把 pending 草稿提升为 `transcript.corrected.json`，重写字幕文件，并基于修正版 transcript 重新生成一个新的笔记版本。
9. 前端刷新任务状态、字幕预览、笔记预览和笔记版本列表。

## UI 设计

只做局部 UI：

- 在已有字幕预览区标题旁增加一个小按钮：`AI 修正字幕`。
- 弹窗沿用当前设置弹窗的视觉结构，不引入新布局语言。
- 双栏区域使用等高滚动布局：
  - 左列标题：`原始字幕`
  - 右列标题：`AI 修正版`
  - 每段显示时间戳和文本。
  - 变更段用浅色背景和左边框标识。
- 弹窗底部按钮：
  - `取消`
  - `采用修正版并重新生成笔记`
- 采用期间禁用按钮并显示 loading。

不做：

- 不新增全局导航。
- 不重排主页面结构。
- 不做手动字幕逐行编辑。
- 不做三栏、复杂 diff 或 git 风格字符级算法。

## 后端接口

### 生成待确认修正

`POST /api/jobs/{job_id}/transcript-corrections`

请求体：

```json
{
  "note_api_key": "...",
  "note_base_url": "https://api.openai.com/v1",
  "note_model": "gpt-5.5",
  "instructions": "可选，用户补充的术语要求"
}
```

响应：

```json
{
  "job_id": "abc",
  "changed_count": 3,
  "segments": [
    {
      "index": 0,
      "start": 0.0,
      "end": 2.5,
      "original_text": "低贩 工作流",
      "corrected_text": "Dify 工作流",
      "changed": true
    }
  ]
}
```

### 采用修正并重新生成笔记

`POST /api/jobs/{job_id}/transcript-corrections/apply`

请求体：

```json
{
  "note_language": "zh",
  "note_style": "detailed",
  "extras": "",
  "note_api_key": "...",
  "note_base_url": "https://api.openai.com/v1",
  "note_model": "gpt-5.5",
  "frame_limit": 6
}
```

响应：

```json
{
  "job_id": "abc",
  "status": "queued"
}
```

采用接口可以同步完成修正版文件提升和字幕重写，然后复用现有后台任务机制生成新笔记版本。

## 大模型修正规则

模型必须遵守：

- 只修改文本，不改时间戳。
- 返回段数必须与输入段数一致。
- 每段必须按原始 `index` 返回。
- 不总结、不扩写、不添加原文没有的信息。
- 重点修正专有名词、产品名、英文缩写、明显同音误识别和错别字。
- 不确定的内容保持原文。
- 输出严格 JSON。

如果模型返回段数不一致、索引缺失、JSON 无法解析，后端返回 400，不写入 pending 文件。

## 数据文件

新增文件：

- `transcript.corrected.pending.json`：最近一次待确认修正草稿。
- `transcript.corrected.json`：当前已采用的修正版 transcript。

继续保留：

- `transcript.json`：原始转写结果。

字幕文件：

- `subtitles.srt`
- `subtitles.vtt`
- `subtitles.md`

采用修正版后，这三个字幕文件反映修正版 transcript；原始 transcript 仍可保留用于对比和未来回退。

## 笔记生成规则

- `regenerate_note_version()` 优先读取 `transcript.corrected.json`。
- 如果不存在修正版，则读取 `transcript.json`。
- 采用修正版后自动生成一个新的笔记版本，不覆盖已有笔记版本。
- 新版本仍使用现有 `note_versions` 索引和 ZIP 重建逻辑。

## 错误处理

- 缺少 `transcript.json`：返回 400，提示任务还没有可修正字幕。
- 缺少笔记 API Key 或模型：返回 400。
- 模型返回无效 JSON：返回 400，不写任何修正文件。
- 模型返回段数或 index 不一致：返回 400，不写任何修正文件。
- 采用时缺少 pending 草稿：返回 400。
- 采用后笔记生成失败：字幕修正版已经采用，任务状态显示失败，用户可再次重新生成笔记。

## 测试计划

后端测试：

- 大模型修正成功时生成 pending 文件，返回 changed_count。
- 大模型返回段数不一致时拒绝并不写 pending。
- 采用 pending 后写入 `transcript.corrected.json` 并重写字幕文件。
- 重新生成笔记优先使用 `transcript.corrected.json`。
- 缺少 transcript 或 pending 时返回 400。

前端验证：

- `npm --prefix frontend run build` 通过。
- 字幕预览旁出现 AI 修正按钮。
- 点击后显示双栏差异弹窗。
- 采用后刷新字幕和笔记版本。
- 没有字幕时按钮不可见。

## 验收标准

- 原始 `transcript.json` 不被覆盖。
- 用户采用前不会改变当前字幕文件。
- 双栏 diff 能清楚看出哪些段落被修改。
- 采用修正版后，字幕文件和新笔记版本都基于修正文段。
- 主页面整体结构和 Main UI 风格保持不变。
