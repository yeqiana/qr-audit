# Markdown + GenUI HTML 报告生成约定

## 1. 目标

每一份正式扫描报告同时有 `报告名称.md` 和 `报告名称.html`。Markdown 是可阅读、可 diff、可归档的正式文本；HTML 是同名静态页面，可在无网络环境下直接打开。

## 2. 与 Plan-Ship 的集成方式

采用 Plan-Ship 的报告交付原则：

- HTML 是 Markdown 的同名阅读副本，不取代 Markdown；
- 样式内嵌，页面离线可打开；
- 移动端友好，语义化标题、表格和键盘焦点；
- 不依赖 CDN、外部字体、外部图片、外部 JavaScript；
- 不伪造交互状态；静态图解必须明确是文本表示；
- 内容状态和证据来自同一份报告数据；
- 发布前检查 MD/HTML 的关键字段、行数、状态和数量一致。

本 Skill 的核心扫描和 HTML 输出不强制依赖 Plan-Ship，也不强制依赖第三方 Skill。若当前宿主已加载 [`gen-ui`](https://github.com/yeqiana/gen-ui)，Agent 应实际读取其 `SKILL.md` 及必要协议，再用于对话内展示；不得把它当作扫描引擎，也不得猜测接口。

## 3. 结构化报告模型

`render_reports.py` 接收 JSON：

```json
{
  "schema_version": "1.0",
  "reports": [{
    "file_stem": "1-group-WAVES_QR-scan",
    "title": "group / WAVES_QR 扫描结果",
    "status": "PARTIAL",
    "generated_at": "2026-11-04T15:20:00+08:00",
    "metrics": [{"label": "图片文件数", "value": 161}],
    "sections": [
      {"type": "paragraph", "text": "本报告只表示本地离线解码结果。"},
      {"type": "table", "title": "扫描明细", "headers": ["图片", "状态"], "rows": [["a.png", "DECODED"]]},
      {"type": "list", "title": "待复核", "items": ["b.png"]},
      {"type": "code", "title": "运行信息", "language": "text", "content": "run_id=..."},
      {"type": "diagram", "title": "扫描流程", "caption": "静态文本表示，不是交互图", "content": "输入 -> 预处理 -> 解码"}
    ]
  }]
}
```

允许 section 类型：`paragraph`、`callout`、`table`、`list`、`code`、`diagram`。未知类型应失败，不得静默丢弃。

## 4. HTML 安全和可访问性

- 所有用户输入、文件名、载荷、错误信息均按 HTML 文本转义。
- 不自动把 URL 转换成 `<a>`。
- CSP 使用 `default-src 'none'`，仅允许内嵌样式和明确允许的 data 图片（默认不嵌图）。
- 不生成 `<script>`、iframe、form 或外部资源。
- 使用 `<main>`、标题层级、`<table>`、`<th scope>` 和 `<caption>`。
- 支持窄屏横向滚动表格，提供 `:focus-visible` 和打印样式。
- HTML 只展示静态内容，不声称有搜索、筛选或实时更新能力。

## 5. Markdown 保真

不要用 `line.split("|")` 解析 Markdown 表格。二维码载荷或错误文本可能包含 `|`、反斜线、反引号或换行。应从结构化 JSON 生成两种格式，表格行按单元格渲染并正确转义。

HTML 生成后检查每个 MD 都有同名 HTML、title/status/metrics 一致、表格行列数一致、状态未丢失、没有外部 URL 或 `<script>`，并把 report-model SHA-256 写入 HTML meta 和渲染清单。
