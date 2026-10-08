# Rolimons Ad Poster

Automatically posts your [Rolimons](https://www.rolimons.com/trades) trade ads every ~15 minutes,
rotating through ads you set up. It runs as a simple Windows app, so you don't need Python.

> **Safe by design:** it only posts Rolimons trade ads. It never sends Roblox trades and never asks
> for your `.ROBLOSECURITY` cookie or Roblox password. If any tool asks for those, it's a scam.

## Download

1. Go to [**Releases**](https://github.com/rxst0/rolimons-ad-poster/releases/latest) and download **`RoliAdPoster.exe`**.
2. Put it in its own folder (for example `Documents\RoliAdPoster`). It saves its settings next to itself.
3. Double-click it.

**"Windows protected your PC"?** The app isn't code-signed, so Windows warns about it.
Click **More info → Run anyway**. You can always read the source code here and build it yourself (see below).

## Setup (2 minutes)

### 1. Roblox user ID
Open your Roblox profile. The number in the address bar is your ID:
`roblox.com/users/`**`123456789`**`/profile`. Paste it into **Roblox user ID**.
You can also paste the whole profile link.

### 2. Rolimons cookie
This lets the app post ads as you on Rolimons. It is **not** your Roblox login.

1. Go to [rolimons.com](https://www.rolimons.com), log in, and verify your Roblox account.
2. Press **F12** to open developer tools.
3. **Chrome / Edge:** *Application* tab → *Cookies* → `https://www.rolimons.com`
   **Firefox:** *Storage* tab → *Cookies* → `https://www.rolimons.com`
4. Find **`_RoliVerification`** and copy its **Value**.
5. In the app, click **Set cookie** and paste it.

Don't share this value. If the app says your cookie expired, repeat these steps.

### 3. Make your ads
Click **New ad**:
- Search items by name or acronym (for example `dom` or `DC`).
- Click **Add to offer** for up to 4 items you're giving away.
- Click **Add to want** for items you want, and/or tick tags like `upgrade`, `downgrade`, `any`, `demand`.
  Items plus tags can total 4 at most.
- The bottom of the editor shows the Rolimons value of both sides.

### 4. Start
Click **Start posting** and leave the app open. It posts one ad, waits out Rolimons' 15-minute
cooldown plus a small random delay, then posts the next ad. The window shows a live countdown and
every attempt is logged. Click **Stop** any time.

## Settings

| Setting | What it does |
|---|---|
| Ad order | Post ads in order, or pick randomly (never the same ad twice in a row) |
| Extra random delay | Seconds added after each 15-minute cooldown so timing isn't robotic |
| Max ads per 24 hours | Safety cap (default 55) |
| Warn when an ad overpays | Logs a warning if an ad offers much more value than it asks for |
| Don't post ads that overpay | Skips those ads entirely |
| Smart pick | Posts ads that offer high-demand items more often |

## Troubleshooting

| Message | Fix |
|---|---|
| *Rolimons rejected your cookie* | Your cookie is wrong or expired. Get a fresh one (step 2). |
| *Unknown item IDs* | That item isn't a Rolimons-tracked limited. Edit the ad. |
| *Still on cooldown* | Normal. It waits and retries automatically. |
| Network errors | It retries with growing delays (5s, 10s, 20s… up to 15 min). |

Files the app keeps next to the `.exe`:
- `config.json`: your ads and settings
- `.env`: your Rolimons cookie
- `state.json`: recent post times, so a restart still respects the cooldown
- `logs\poster.log`: every post attempt

---

## For developers

Requires Python 3.10+.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python gui.py            # desktop app
.venv\Scripts\python main.py --check   # CLI: validate setup, post nothing
.venv\Scripts\python main.py --once    # CLI: post one ad
.venv\Scripts\python main.py           # CLI: post on a timer until Ctrl+C
build_exe.bat                          # builds dist\RoliAdPoster.exe
```

The CLI reads `config.json` (see `config.example.json`) and the cookie from `.env`
(see `.env.example`) or the `ROLI_VERIFICATION` environment variable.

Code layout (`roliposter/`): `api.py` (Rolimons request and response handling), `poster.py` (timer loop,
rotation, retries), `items.py` / `values.py` (item catalog and value checks), `config.py`, `cookie.py`,
`state.py`, `startup.py`.

### Endpoint notes
Rolimons has no official API for posting ads, so this may break if they change it.
- `POST https://api.rolimons.com/tradeads/v1/createad`, with the cookie `_RoliVerification`, and a JSON body of
  `player_id`, `offer_item_ids`, `request_item_ids`, `request_tags`.
- Confirmed error responses: no cookie returns `401 {"code":4}`, and a bad cookie returns `401 {"code":5}`.
- Success and cooldown responses are detected heuristically: a 2xx response is success, and a message
  mentioning "cooldown" or "wait" is a cooldown. If Rolimons changes them, update `classify_response` in `roliposter/api.py`.
