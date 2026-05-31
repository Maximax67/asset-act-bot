# Asset Act Bot

Telegram bot that reads Google Sheets, generates signed asset-acceptance acts
through an external document API, and uploads them to Google Drive.

## Quick Start

### 1. Clone & enter project

```bash
git clone https://github.com/Maximax67/asset-act-bot
cd asset-act-bot
```

### 2. Create Python virtual environment (Python ≥ 3.11 required)

```bash
python -m venv .venv
source .venv/bin/activate   # Linux / macOS
.venv\Scripts\activate      # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` — see the **Configuration** section below for field descriptions.

### 5. Grant Google Service Account Access

Grant the service account **Viewer** access on both spreadsheets and
**Contributor / Editor** access on the target Drive folder.

### 6. Run locally (polling mode)

Set `MODE=polling` in `.env` and run:

```bash
python run_polling.py
```

## Configuration Reference

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `BOT_TOKEN` | ✅ | — | Telegram bot token from @BotFather |
| `ADMIN_CHAT_ID` | ✅ | — | Chat ID that may run commands |
| `MESSAGE_THREAD_ID` | | — | Thread/topic ID inside the chat for file upload |
| `MODE` | | `webhook` | `webhook` or `polling` |
| `WEBHOOK_URL` | | — | Public base URL of your deployment |
| `WEBHOOK_SECRET` | | — | Telegram webhook secret token |
| `WEBHOOK_MANAGE_TOKEN` | | — | Bearer token for `/webhook/setup` and `/webhook/delete` |
| `GOOGLE_CLIENT_EMAIL` | ✅ | — | Service account email |
| `GOOGLE_PRIVATE_KEY` | ✅ | — | Service account private key |
| `GOOGLE_TOKEN_URI` | | `https://oauth2.googleapis.com/token` | Service account token URI |
| `ASSETS_SHEET_ID` | ✅ | — | Google Spreadsheet ID for assets |
| `ASSETS_SHEET_NAME` | | `Sheet1` | Sheet tab name (empty → default) |
| `DEPARTMENTS_SHEET_ID` | ✅ | — | Google Spreadsheet ID for departments |
| `DEPARTMENTS_SHEET_NAME` | | `Sheet1` | Sheet tab name |
| `SHARED_DRIVE_ID` | | — | Drive folder / Shared Drive ID for uploads |
| `DOC_GENERATOR_BASE_URL` | ✅ | — | Base URL of the doc generator |
| `DOCUMENT_ID` | ✅ | — | Template document ID in the generator |
| `DOC_FORMAT` | | `docx` | `docx` or `pdf` |
| `FILE_NAME_PATTERN` | | `{date} Акт. {deptname}` | Output file name pattern |
| `THOUSAND_SEPARATOR` | | ` ` (space) | Thousands separator in numbers |
| `DECIMAL_SEPARATOR` | | `,` | Decimal separator |
| `CURRENCY_SUFFIX` | | — | Appended to formatted amounts |
| `ALLOW_ROUNDING_ADJUST` | | `true` | Auto-fix rounding on last owner |
| `EXECUTION_MAX_TIME` | | `300` | Pipeline timeout in seconds; `0` disables the limit |

## Google Sheets Layout

### Assets sheet

| Col | Index | Field |
| --- | --- | --- |
| C | 3 | Asset name |
| E | 5 | Inventory number |
| F | 6 | Unit of measure |
| G | 7 | Total quantity |
| I | 9 | Total price |
| J | 10 | Owner codes (comma / newline separated, e.g. `DEPT-A-5, DEPT-B-3`) |
| K | 11 | Generate flag (`TRUE` to include) |

### Departments sheet

| Col | Index | Field |
| --- | --- | --- |
| A | 1 | Department code (must match owner tokens) |
| B | 2 | Director position |
| C | 3 | Director full name (Surname First Patronymic) |
| D | 4 | Receiver position |
| E | 5 | Receiver full name |

## Document Template Variables

These are sent to the generator API as `{"variables": {...}}`:

| Variable | Description |
| --- | --- |
| `TotalQuantityWords` | Total item count in Ukrainian words |
| `TotalQuantityNumeric` | Total item count as digit string |
| `TotalSumNumeric` | Formatted total sum (e.g. `1 234,56`) |
| `TotalSumWords` | Total sum in Ukrainian words + грн/коп |
| `SecondDirectorPosition` | Director's job title |
| `SecondDirectorName` | Director's formatted name (`First LAST`) |
| `ReceiverPosition` | Receiver's job title |
| `ReceiverName` | Receiver's formatted name |
| `Val` | Alias for `TotalSumNumeric` |
| `items` | Array of item objects (see below) |

Each element of `items`:

| Key | Description |
| --- | --- |
| `name` | Asset name |
| `inventory` | Inventory number |
| `unit` | Unit of measure |
| `qty` | Quantity (string) |
| `unit_price` | Formatted unit price |
| `sum` | Formatted line total |
| `note` | Optional note |

## Deployment to Vercel

```bash
npm i -g vercel
vercel --prod
```

Set all `.env` variables in **Vercel → Settings → Environment Variables**,
then register the webhook:

```bash
curl -X POST https://your-app.vercel.app/webhook/setup \
  -H "Authorization: Bearer your_webhook_manage_token"
```

To remove the webhook:

```bash
curl -X POST https://your-app.vercel.app/webhook/delete \
  -H "Authorization: Bearer your_webhook_manage_token"
```

**IMPORTANT:** set Vercel function max execution time to 300 seconds in **Vercel → Settings → Functions**. Otherwise the generation requests will be terminated due to timeout error.

## Bot Commands

| Command | Description |
| --- | --- |
| `/generate_asset` | Run the full generation pipeline |
| `/help` | Show help |
| `/start` | Welcome message |
