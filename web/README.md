# Benny & 叮當 網頁版

桌面版 AI 伴侶的網上版本：任何人打開網址、輸入通行碼，就可以喺瀏覽器同 Benny 同叮當傾偈（打字或者講廣東話）。

> 網頁版係獨立嘅：只會**讀取**桌面版嘅程式（人設解析、經文同書庫檢索、記憶模組），唔會改動桌面版任何檔案。
> 網頁版放喺 GitHub 嘅 `web` 分支；`main` 分支仍然係桌面版。

## 同桌面版嘅分別

| | 桌面版 | 網頁版 |
|---|---|---|
| 對話模型 | 本機 Ollama qwen3:14b | OpenRouter（預設 `anthropic/claude-haiku-5.5`） |
| 語音 | 電腦喇叭／咪高峰 | 瀏覽器錄音同播放（Azure 廣東話） |
| 使用者 | 你一個人 | 有通行碼嘅訪客，每人記憶獨立 |
| 書庫 | 金庸 + 三國演義 | 只有三國演義（金庸有版權，唔放上網） |
| 聖經、佛經 | ✓ | ✓ |
| 用量限制 | 冇 | 有（保護 OpenRouter 同 Azure 帳單） |

## 部署步驟

你需要：

1. **OpenRouter 帳戶**：https://openrouter.ai → Keys → 建立 API key，預付少量額度（例如 5–10 美元）。
2. **一部 VPS**：例如 Hetzner 或 DigitalOcean，Ubuntu 24.04、2 vCPU、4GB RAM（每月約 5–8 美元）。
3. **Cloudflare 帳戶**（免費）：用 Cloudflare Tunnel 攞 HTTPS 網址，唔使喺 VPS 開任何 port。
   想用自己網域就要將網域加入 Cloudflare；冇網域都可以用 Cloudflare 提供嘅子網域。
4. **Azure 語音 key**（可以沿用桌面版嗰個；唔填就只有文字對話）。

### 1. 喺你電腦準備資料

資料（聖經、佛經、三國演義書庫）唔放 GitHub，要由桌面版複製一份：

```powershell
cd C:\AI-Girlfriend\AIbenny-web\web
$env:PYTHONPATH = "$PWD;$PWD\..\apps\backend\src;$PWD\..\packages\openmimicry-memory\src"
python scripts\prepare_data.py --desktop "C:\AI-Girlfriend\openmimicry-main\openmimicry-main"
```

完成後會有 `web\data\`（約 17MB），入面有 `bible.sqlite`、`buddhist.sqlite`、`novels.sqlite`（只有三國演義）。
呢個腳本只會讀取桌面版資料，唔會改動佢。

### 2. 喺 Cloudflare 建立 Tunnel

1. Cloudflare 主控台 → Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared。
2. 複製 token（`eyJ...` 開頭嗰串）。
3. Public Hostname：揀你嘅網址，Service 填 `http://web:8080`。

### 3. 設定 VPS

```bash
# 安裝 Docker
curl -fsSL https://get.docker.com | sh
# 攞程式（私人 repo：用 GitHub Personal Access Token 或 SSH key）
git clone -b web https://github.com/bosco230/AIbenny.git
cd AIbenny/web
cp .env.example .env
nano .env        # 填 WEB_PASSCODE、SESSION_SECRET、OPENROUTER_API_KEY、AZURE_SPEECH_KEY、CLOUDFLARE_TUNNEL_TOKEN
```

`SESSION_SECRET` 可以咁產生：`python3 -c "import secrets; print(secrets.token_hex(32))"`

再由你電腦將 `web\data` 上載去 VPS 嘅 `AIbenny/web/data`，例如：

```powershell
scp -r C:\AI-Girlfriend\AIbenny-web\web\data root@你的VPS地址:~/AIbenny/web/
```

### 4. 啟動

```bash
docker compose up -d --build
docker compose logs -f web     # 睇到 "Application startup complete" 就得
```

第一次啟動會下載 bge-m3（約 1.2GB，用嚟做記憶同書庫檢索）。
打開 Cloudflare 嘅網址，輸入通行碼就可以傾偈。

### 更新

```bash
cd ~/AIbenny && git pull && cd web && docker compose up -d --build
```

## 設定（`.env`）

| 變數 | 用途 |
|---|---|
| `WEB_PASSCODE` | 訪客要輸入嘅通行碼（至少 6 個字） |
| `SESSION_SECRET` | 簽署登入 cookie 嘅隨機字串（至少 32 個字） |
| `OPENROUTER_API_KEY` | OpenRouter key |
| `CHAT_MODEL` | 角色對話用嘅模型，預設 `anthropic/claude-haiku-5.5` |
| `HELPER_MODEL` | 記憶抽取同摘要用嘅平價模型，預設 `qwen/qwen3.7-flash` |
| `AZURE_SPEECH_KEY` / `AZURE_SPEECH_REGION` | 廣東話語音；留空就只有文字 |
| `CLOUDFLARE_TUNNEL_TOKEN` | Cloudflare Tunnel token |
| `LIMIT_*` | 用量限制（每 10 分鐘訊息數、每日訊息數、每日語音字數等） |

## 私隱同安全

- 每位訪客有自己嘅記憶檔（`data/visitors/<id>.sqlite`），睇唔到其他人，亦睇唔到你桌面版嘅私人記憶。
- 訪客可以撳「忘記我」清除自己所有記憶。
- 通行碼錯誤每分鐘最多試 5 次；登入 cookie 用 HMAC 簽署，唔可以偽造。
- 網頁版只公開 Benny 同叮當兩個角色圖片資料夾，其他檔案唔會被讀取。
- 費用保護：每人每日訊息同語音有上限，全站每日語音字數亦有上限。

## 本機開發測試

```powershell
cd C:\AI-Girlfriend\AIbenny-web\web
$env:PYTHONPATH = "$PWD;$PWD\..\apps\backend\src;$PWD\..\packages\openmimicry-memory\src"
python -m pytest tests -q
```
