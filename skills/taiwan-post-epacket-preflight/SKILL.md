---
name: taiwan-post-epacket-preflight
description: "預檢臺灣國際 e 小包（Taiwan Post ePacket）批次 JSON。使用者要求檢查包裹尺寸、重量、品項或 CCC 稅則號碼格式時使用。"
---

# 國際 e 小包批次預檢

1. 使用者若指定本機 JSON 檔案，只處理該檔案。相對輸入路徑以呼叫 Skill 時的工作目錄為準。使用者明確要試跑範例時，改用本 Skill 的 `assets/batch.json`。缺少檔案且未指定試跑時，詢問路徑。
2. 以本份 `SKILL.md` 所在資料夾定位 `scripts/preflight.py` 和 `assets/batch.json`。執行前確認需要的檔案存在。以絕對路徑將腳本和輸入檔作為獨立引數傳入，並依所在 shell 安全引用路徑。確認所選直譯器的 `--version` 顯示 Python 3，再以 `python -I -B "<腳本路徑>" "<輸入路徑>"` 執行。也可用 `python3 -I -B`，Windows 的 Python Launcher 可用 `py -3 -I -B`。
3. 讓腳本讀取輸入。將回覆限於規則版本、狀態、問題代碼與欄位路徑，保留原始檔。依程式輸出解讀結果。

| 退出碼 | 預檢結果 |
| --- | --- |
| `0` | JSON 顯示 `pass` 或 `warn`。保留警告，例如範例的 `CCC_MISSING`。 |
| `1` | JSON 顯示 `fail`，列出不符的欄位與代碼。 |
| `2` | `stderr` 為 `Input could not be processed. Provide one readable UTF-8 JSON file up to 1 MiB.` 時，提示使用者確認檔案可讀、格式及大小。 |

對 `0` 或 `1`，先確認輸出為含 `ruleset`、`status` 和 `issues` 的預檢 JSON。若退出碼為 `2` 但 stderr 與表中訊息不符，檢查直譯器、腳本路徑與引數；回報預檢未完成。其他無法辨識的結果也視為預檢未完成。

本 Skill 執行離線欄位預檢，依指定 JSON 讀取並在終端機輸出結果。結論的適用範圍為該規則版本的欄位檢查。
