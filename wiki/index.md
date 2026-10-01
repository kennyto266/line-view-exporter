---
updated_at: "2026-10-01"
type: index
---
# Line View Exporter — Wiki 總目錄

> 3ds Max 匯出三視圖(Front / Side / Top)→ **SVG** → AI 可編輯 path。
> 09-29 交付。用家係 Max 新手、**冇 Illustrator** — 所以揀 SVG 路線。

## 兩個版本

| 版本 | 檔案 | 狀態 |
|---|---|---|
| 3ds Max(MAXScript) | `LineViewExporter.ms` | ✅ 3ds Max 2027 實測 PASS(用家部機) |
| Blender(Python) | `LineViewExporter_Blender.py` | ⚠️ 未實測(畀 Mac 朋友用) |

## 修過嘅 bug(MAXScript 陷阱,返工記住)

1. **`by` 係 MAXScript 保留字** — 唔可以用做變數名
2. **`fileIn` scope** — fileIn 入嚟嘅 script 有 scope 問題,要處理

Repo:**public** `github.com/kennyto266/line-view-exporter`(branch `master`)。
