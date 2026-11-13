# 中華郵政批次寄件預檢

同一個 Skill 可預檢國際 e 小包、國際快捷（EMS）、國際包裹與國內包裹的批次 JSON。只使用 Python 標準函式庫，已在 Windows 的 Python 3.12.14 測試。工具只讀取指定檔案，在終端機輸出結果。

## 執行

在此資料夾執行以下命令。範例為合成資料，會顯示 `CCC_MISSING` 提示。

```powershell
python -B preflight.py examples/batch.json
python -B preflight.py examples/ems.json
python -B preflight.py examples/international-parcel.json
python -B preflight.py examples/domestic-parcel.json
python -B -m unittest -v
```

若系統的 `python` 指向 Microsoft Store 捷徑，請用已安裝的 Python 執行檔。

程式輸出 JSON，包含規則版本、整體狀態及問題的欄位路徑與代碼。退出碼 `0` 表示 `pass` 或僅有 `warn`，`1` 表示 JSON 已讀取但結構或欄位規則失敗，`2` 表示命令用法錯誤或無法讀取、解析輸入。錯誤不回顯檔名或欄位內容。輸入須為 UTF-8 JSON，可有 BOM，最大 1 MiB，重複 JSON 鍵及 `NaN` 等非 JSON 數值會拒絕。

## 選擇郵件種類

每份 JSON 在頂層用 `mailType` 指定一種服務。舊 JSON 可省略，沿用原有 e 小包規則。明確指定服務時，寄達國、運輸方式、內容類型和國內包裹選項只接受在適用的郵件資料列內。每批 `parcels` 的本機處理上限為 100 件，尺寸用公分，重量用公斤。依 [examples](examples/) 的合成範例整理資料。這些是本工具的 JSON 欄位。直接從 Python 呼叫 `validate_batch()` 時，小數請傳入 `Decimal`。

| `mailType` | 每件郵件的選項 |
| --- | --- |
| `epacket` | 沿用原有格式 |
| `ems` | `destinationCountry` 用兩位大寫國碼。 `contentType` 預設 `goods`，文件件可填 `documents`，此時 `items` 省略或留空陣列 |
| `international-parcel` | `destinationCountry` 用兩位大寫國碼。 `transport` 選 `air`（航空）、`surface`（水陸）或 `sal`（陸空聯運） |
| `domestic-parcel` | `domesticProfile` 必填，依下列國內包裹規則選擇 |

## 規則範圍

### 國際 e 小包

`epacket-2023-08-preflight-v1` 以舊版批次流程的子集為準。JSON 根物件的 `parcels` 有 1–100 件，每件 `items` 有 1–5 列。包裹及品項重量使用公斤，三邊使用公分。工具支援最多 128 位小數的重量及尺寸（科學記號展開後計算，包含尾端的零），並精確加總。包裹重須大於零且不超過 2 公斤。最長邊不超過 60 公分，三邊和不超過 90 公分，排序後最大的兩邊至少分別達 14 和 9 公分。現行寄件條件以[中華郵政國際 e 小包說明](https://subservices.post.gov.tw/post/internet/Postal/index.jsp?ID=1499060698896)為準。

每列 `items` 需要非空字串 `name`、正整數 `quantity`、正數 `unitPrice` 與正數 `weightKg`。`quantity` 按數值判斷，`2`、`2.0` 與 `2e0` 都有效。`weightKg` 是該列全部商品的重量，品項列直接加總，不再乘以數量。`hsCode` 的空白與 11 碼都會提示。去掉空白、句點與連字號後，10 碼只代表符合本工具的格式檢查。工具保留原資料，沒有驗算 CCC 檢查碼。其他欄位會略過。

### 國際快捷（EMS）與國際包裹

商品件可填 1–40 列品項。品項的 `weightKg` 指整列重量，合計不得超過包裹總重。CCC 格式檢查適用於 e 小包。國際包裹按[郵務營業規章第 48 條](https://www.post.gov.tw/post/internet/Law/index.jsp?ID=170301&ch_class_id=30)檢查最小面，含信函最小尺寸的 2 毫米許可差。EMS 最小尺寸須依寄達地另查。

以下是 2026-11-13 核對的規則快照。對表內路線檢查每件重量、最長邊與長度加周圍長（最長邊加其餘兩邊各兩倍）。其餘路線回報 `ROUTE_LIMITS_UNCHECKED`。國碼檢查兩位大寫字母及常見錯值。臺灣及中國大陸郵路分別使用國內及兩岸流程，填入 `TW` 或 `CN` 時回報 `DESTINATION_OUT_OF_SCOPE`。查無路線且包裹總重至少 1000 公斤時，品項合計另回報 `ITEM_WEIGHT_TOTAL_UNCHECKED`。

| 服務 | 快照涵蓋的國碼 | 中華郵政來源 |
| --- | --- | --- |
| EMS | AU、CA、DE、GB、HK、JP、KR、MO、SG、US | [尺寸與重量限制](https://www.post.gov.tw/post/internet/Postal/index.jsp?ID=2010215) |
| 國際包裹航空 | AU、CA、DE、FR、GB、HK、JP、KR、MO、SG、US | [航空表](https://www.post.gov.tw/post/internet/Postal/index_list_all.jsp?ID=2030205) |
| 國際包裹水陸 | AU、CA、FR、JP、MY、SG、TH、US、VN | [水陸表](https://www.post.gov.tw/post/internet/Postal/index_list_all.jsp?ID=2030207) |
| 國際包裹陸空 | CA、PR、US | [陸空表](https://subservices.post.gov.tw/post/internet/Postal/index_list_all.jsp?ID=2030206) |

EMS 與國際包裹品項參照 [EZPost 國際寄件登打範例](https://ezpost.post.gov.tw/itmatt/)。實際收寄狀態、目的地附加條件、禁限寄與圓筒尺寸須另查。

### 國內包裹

按[中華郵政國內包裹規定](https://www.post.gov.tw/post/internet/Postal/index.jsp?ID=2030101)選擇每件的 `domesticProfile`。程式採用官網業務說明列出的 14 × 9 公分最小面。國內件只檢查包裹欄位。

| 選項 | 上限 |
| --- | --- |
| `standard` | 20 公斤，三邊合計 150 公分 |
| `restricted-area` | 20 公斤，三邊合計 120 公分，適用官方列出的梨山里、平等里與翠華村華岡 |
| `indivisible` | 30 公斤，最長邊 150 公分，長度加周圍長 300 公分。工具會提示須確認符合不可分裝條件 |

本工具依使用者選擇的國內規則檢查。受限制地區須選 `restricted-area`。i 郵箱等特殊通路的尺寸及圓筒規則須另查。

工具只做離線欄位預檢。試算表產檔、EZPost 上傳與郵局受理須另行處理。

## 安裝 Codex 或 Claude Code 外掛

使用 GitHub 作為外掛來源。四種服務共用原來的外掛名稱 `epacket` 和 Skill 名稱 `taiwan-post-epacket-preflight`。預檢需要已安裝的 Python 3。

**Codex CLI**（須支援 `codex plugin add`）

```sh
codex plugin marketplace add r2210603/taiwan-post-epacket-preflight
codex plugin add epacket@ctg-epacket
```

開啟新會話，輸入「請用 ePacket 預檢 Skill 跑內建範例」，或輸入 `$` 並從清單選擇這個 Skill。

**Claude Code**（CLI 2.1.292 或更新版本）

```sh
claude plugin install epacket --marketplace r2210603/taiwan-post-epacket-preflight
```

開啟新會話，執行 `/epacket:taiwan-post-epacket-preflight 用內建範例試跑`。合成範例應回傳 `warn` 和 `CCC_MISSING`。

## ZIP 安裝

從 [GitHub Releases](https://github.com/r2210603/taiwan-post-epacket-preflight/releases) 下載 `taiwan-post-epacket-preflight-skill.zip`。

若要從原始碼打包，在專案根目錄執行以下命令，並指定新的輸出檔名。

```powershell
python -I -B scripts/build_skill.py taiwan-post-epacket-preflight-skill.zip
```

解壓後，把整個 `taiwan-post-epacket-preflight` 資料夾複製到對應位置。

| 平台 | 專案內的 Skill 位置 | 叫用 |
| --- | --- | --- |
| [Codex](https://learn.chatgpt.com/docs/build-skills) | `.agents/skills/taiwan-post-epacket-preflight/` | `$taiwan-post-epacket-preflight` |
| [Claude Code](https://code.claude.com/docs/en/skills) | `.claude/skills/taiwan-post-epacket-preflight/` | `/taiwan-post-epacket-preflight` |

從安裝 Skill 的專案啟動新會話。可先輸入「請用合成範例試跑國際 e 小包預檢」。檢查自己的檔案時，提供本機 JSON 路徑。


## 授權

本專案以 [MIT 授權](LICENSE) 發佈。
