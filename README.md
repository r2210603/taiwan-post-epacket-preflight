# 國際 e 小包批次預檢

這是 v0.1 離線預檢工具。它檢查國際 e 小包批次 JSON 的包裹尺寸、重量、品項和 CCC 格式。只使用 Python 標準函式庫，已在 Windows 的 Python 3.12.14 測試。工具只讀取指定檔案，在終端機輸出結果。

## 執行

在此資料夾執行以下命令。範例為合成資料，會顯示 `CCC_MISSING` 提示。

```powershell
python -B preflight.py examples/batch.json
python -B -m unittest -v
```

若系統的 `python` 指向 Microsoft Store 捷徑，請用已安裝的 Python 執行檔。

程式輸出 JSON，包含規則版本、整體狀態及問題的欄位路徑與代碼。退出碼 `0` 表示 `pass` 或僅有 `warn`，`1` 表示 JSON 已讀取但結構或欄位規則失敗，`2` 表示命令用法錯誤或無法讀取、解析輸入。錯誤不回顯檔名或欄位內容。輸入須為 UTF-8 JSON，可有 BOM，最大 1 MiB，重複 JSON 鍵及 `NaN` 等非 JSON 數值會拒絕。

## 規則範圍

`epacket-2023-08-preflight-v1` 以舊版批次流程的子集為準。JSON 根物件的 `parcels` 有 1–100 件，每件 `items` 有 1–5 列。包裹及品項重量使用公斤，三邊使用公分。工具支援最多 128 位小數的重量及尺寸（科學記號展開後計算，包含尾端的零），並精確加總。包裹重須大於零且不超過 2 公斤。最長邊不超過 60 公分，三邊和不超過 90 公分，排序後最大的兩邊至少分別達 14 和 9 公分。現行寄件條件以[中華郵政國際 e 小包說明](https://subservices.post.gov.tw/post/internet/Postal/index.jsp?ID=1499060698896)為準。

每列 `items` 需要非空字串 `name`、正整數 `quantity`、正數 `unitPrice` 與正數 `weightKg`。`quantity` 按數值判斷，`2`、`2.0` 與 `2e0` 都有效。`weightKg` 是該列全部商品的重量，品項列直接加總，不再乘以數量。`hsCode` 的空白與 11 碼都會提示。去掉空白、句點與連字號後，10 碼只代表符合本工具的格式檢查。工具保留原資料，沒有驗算 CCC 檢查碼。其他欄位會略過。

此版範圍止於欄位預檢。目的地及幣別代碼、海關品名、禁限寄要求、試算表產檔與 EZPost 上傳驗證須另行處理。預檢通過無法證明郵局受理。

## 授權

本專案以 [MIT 授權](LICENSE) 發佈。
