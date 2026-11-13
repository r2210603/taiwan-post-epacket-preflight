---
name: taiwan-post-epacket-preflight
description: "離線預檢中華郵政批次 JSON。使用者要檢查國際 e 小包（Taiwan Post ePacket）、國際快捷（EMS）、國際包裹或國內包裹的尺寸、重量、品項，或 e 小包的 CCC 格式時使用。"
---

# 中華郵政批次寄件預檢

1. 使用者指定本機 JSON 時，只處理該檔案。相對路徑以呼叫 Skill 時的工作目錄為準。缺少檔案且未指定試跑時，詢問路徑。
2. 讓程式依 JSON 頂層的 `mailType` 選擇規則。可用 `epacket`、`ems`、`international-parcel`、`domestic-parcel`。省略時沿用舊版 e 小包。若使用者指定其他郵件種類，執行結果卻顯示不同服務的 `ruleset`，請指出不符並要求修正 JSON。保留原檔。
3. 以本份 `SKILL.md` 所在資料夾定位程式與範例。ZIP 版的程式在 `scripts/preflight.py`，範例在 `assets/`。外掛版的程式在外掛根目錄的 `preflight.py`，範例在外掛根目錄的 `examples/`。依郵件種類選擇 `batch.json`、`ems.json`、`international-parcel.json` 或 `domestic-parcel.json`。使用者只說試跑範例時，用原有 e 小包範例。
4. 確認所需檔案存在，以絕對路徑將腳本和輸入檔作為獨立引數傳入，依 shell 安全引用。確認 `--version` 顯示 Python 3，再以 `python -I -B "<腳本路徑>" "<輸入路徑>"` 執行。也可用 `python3 -I -B` 或 Windows 的 `py -3 -I -B`。
5. 讓腳本讀取輸入，回覆規則版本、狀態、問題代碼與欄位路徑。

| 退出碼 | 預檢結果 |
| --- | --- |
| `0` | JSON 顯示 `pass` 或 `warn`。保留警告，例如範例的 `CCC_MISSING`。 |
| `1` | JSON 顯示 `fail`，列出不符的欄位與代碼。 |
| `2` | `stderr` 為 `Input could not be processed. Provide one readable UTF-8 JSON file up to 1 MiB.` 時，提示使用者確認檔案可讀、格式及大小。 |

對 `0` 或 `1`，先確認輸出為含 `ruleset`、`status` 和 `issues` 的預檢 JSON。若退出碼為 `2` 但 stderr 與表中訊息不符，檢查直譯器、腳本路徑與引數；回報預檢未完成。其他無法辨識的結果也視為預檢未完成。

規則版本 `twpost-mail-type-v1` 表示頂層 `mailType` 無效。遇到 `DESTINATION_OUT_OF_SCOPE` 時，請使用國內包裹或兩岸郵件的對應流程。遇到 `ROUTE_LIMITS_UNCHECKED` 時，告知本次缺少該路線的重量及尺寸上限。遇到 `INDIVISIBLE_ELIGIBILITY_UNCHECKED` 時，告知工具依輸入套用不可分裝的限度，交寄資格須另行確認。

本 Skill 適用於長方體郵件的離線欄位預檢。回覆以該規則版本的檢查結果為限。寄達地的即時收寄情況、禁限寄要求及特殊交寄通路須以中華郵政公告為準。
