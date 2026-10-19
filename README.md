# Rolimons Ad Poster

Automatically posts your [Rolimons](https://www.rolimons.com/trades) trade ads every ~15 minutes,
rotating through ads you set up. It runs as a simple app on **Windows** and **Android**, so you don't need Python.
Fully open source, with no servers involved: each device posts on its own.

> **View-only for trades:** it posts Rolimons trade ads and can *show* your Roblox trades. It can't accept,
> decline or send Roblox trades, and it never asks you to type or paste your Roblox password or
> `.ROBLOSECURITY` cookie. If any tool asks you to paste those, it's a scam.
> On Android, the optional **Read my trades directly** setting keeps an encrypted copy of your Roblox sign-in
> on your phone so the app can read your trades ([details below](#reading-your-trades-directly-android)).
> It's off by default.

**Features**
- Build ads by searching items by name, with item pictures and live Rolimons values
- Posts on Rolimons' 15-minute cooldown with a small random delay, rotating through your ads
- Skips ads offering items you no longer own
- Runs in the system tray, can start with Windows, and can start posting automatically
- Windows notifications when posting stops, when your cookie is about to expire, or when an update is out
- Optional posting hours (for example 09:00–23:00), a plain-English history of every post, pause and problem
  (with what to do about it), and a "Skip to next ad" button
- Value checks: warns about overpaying ads and can favor high-demand ads
- **Received trades:** see the trades people send you on Roblox, view-only, in its own tab
- **Android, optional:** your trades as a list in the app, with item pictures and Rolimons values, and
  new-trade alerts even with the app closed

## Download (Windows)

1. Go to [**Releases**](https://github.com/rxst0/rolimons-ad-poster/releases/latest) and download **`RolimonsAdPosterSetup.exe`**.
2. Run it and click **Install**. No admin rights are needed.
3. Open **Rolimons Ad Poster** from the Start Menu, Windows Search, or the desktop shortcut.

The app tells you when a new version is out. Run the new installer to update; your ads and cookie are kept.
To uninstall, go to **Settings → Apps → Installed apps → Rolimons Ad Poster**. This also deletes your saved cookie.

**"Windows protected your PC"?** The app isn't code-signed, so Windows warns about it.
Click **More info → Run anyway**. You can always read the source code here and build it yourself (see below).

*Portable option:* download `RoliAdPoster.exe` instead and run it from any folder. It saves its settings next to itself.

## Download (Android)

1. On your phone, open [**Releases**](https://github.com/rxst0/rolimons-ad-poster/releases/latest) and download **`RolimonsAdPoster.apk`**.
2. Open the file. If Android asks, allow your browser to **install unknown apps**, then tap **Install**.
   Play Protect may warn because the app isn't from the Play Store; tap **More details → Install anyway**.
3. Open **Rolimons Ad Poster**, tap **Sign in to Rolimons**, and log in and verify like on the website.
   The app picks up your cookie by itself, so there's nothing to copy.
4. Add your ads and tap **Start posting**. A notification stays in your status bar while it posts, even with
   the screen off. You're notified when posting pauses (daily ad limit, posting hours, no internet), resumes
   or stops, and (once you've signed in to Roblox in the Trades tab) when someone sends you a new trade.
   New-trade alerts only work while the app is open or recently used, unless you turn on
   [Read my trades directly](#reading-your-trades-directly-android).
   In **Settings**, tap **Allow running in the background** so Android doesn't pause it.
   Some phones (Samsung, Xiaomi, OnePlus) also have their own battery saver: set the app to *Unrestricted* there.

To update, install the newer APK over the old one; your ads and cookie are kept. The app tells you when one is out.
Run posting on **one device at a time**: two devices posting for the same account would hit each other's cooldown.

## Setup (2 minutes)

### 1. Rolimons cookie
This lets the app post ads as you on Rolimons. It is **not** your Roblox login.

1. Go to [rolimons.com](https://www.rolimons.com), log in, and verify your Roblox account.
2. Press **F12** to open developer tools.
3. **Chrome / Edge:** *Application* tab → *Cookies* → `https://www.rolimons.com`
   **Firefox:** *Storage* tab → *Cookies* → `https://www.rolimons.com`
4. Find **`_RoliVerification`** and copy its **Value** (copying the whole row also works).
5. In the app, click **Set cookie** and paste it.

Your Roblox user ID is filled in from the cookie, and the app shows when the cookie expires.
Don't share this value.

### 2. Make your ads
Click **New ad**:
- Search items by name or acronym (for example `dom` or `DC`).
- Click **Add to offer** for up to 4 items you're giving away.
- Click **Add to want** for items you want, and/or tick tags like `upgrade`, `downgrade`, `any`, `demand`.
  Items plus tags can total 4 at most.
- The bottom of the editor shows the Rolimons value of both sides. Items you don't own are highlighted.

### 3. Start
Click **Start posting**. It posts one ad, waits out Rolimons' 15-minute cooldown plus a small random
delay, then posts the next one. The window shows a live countdown and which ad is next; **Skip** jumps
ahead. While posting, closing the window keeps the app running in the tray (near the clock).
Right-click the tray icon to open, stop, skip or quit.

## Viewing your Roblox trades (PC)

Everything lives in one window with tabs: **Ad poster**, **Received trades**, **History**, **Settings** and
**Help**. The **Received trades** tab shows Roblox's own trades page (inbound, outbound, completed); sign in
to Roblox inside it the first time, like in a browser.

- **View only.** Accepting, declining, countering and sending are blocked inside the tab before anything
  leaves your PC, and those buttons are hidden. Respond to trades on roblox.com or in the Roblox app
  (**Open on roblox.com** opens your normal browser).
- **Your Roblox login stays in that tab.** It uses Microsoft Edge WebView2 (built into Windows 10 and 11).
  The sign-in is kept in the tab's own browser profile (`roblox-session` next to the app, encrypted by
  Windows like Edge's cookies). This app's code never reads, copies or sends it.
- **Sign out:** Settings → *Sign out of Roblox*, or uninstall the app (which deletes that folder).
- **RoValra built in.** The tab loads [RoValra](https://github.com/NotValra/RoValra), a free open-source Roblox
  extension by Valra, which adds item values and projected-item warnings to trade pages. The bundled copy is a
  pinned, checksum-verified release with two changes: its branding images are replaced (its license excludes
  them), and a small shim blocks its trade-changing requests (it has a "Decline losing trades" feature) so the
  tab stays view-only. Like any Roblox extension, it runs while you're signed in to Roblox in that tab. Turn it
  off in Settings → *Show RoValra on trade pages*.

## Reading your trades directly (Android)

By default the Trades tab shows Roblox's own trades page, and your Roblox sign-in stays inside that page:
the app never reads it. That page only runs while the app is open, so new-trade alerts stop soon after
you leave the app.

Turn on **Settings → Read my trades directly** to get:
- your trades as a list in the app (inbound, outbound, completed, inactive), with item pictures,
  Rolimons values, a give/get total and a warning for projected items; tap a trade to see every item
- new-trade alerts every couple of minutes, even with the app closed. The status bar shows
  *Checking for new Roblox trades* while this runs. It uses a little more battery, like posting does.

How it works, and what changes:
- **The app reads your Roblox sign-in.** After you sign in on the Roblox page in the Trades tab, the app
  copies your `.ROBLOSECURITY` cookie and stores it encrypted with an Android Keystore key, which never
  leaves the phone. The background service runs in a separate process that can't see the page's
  sign-in, so it needs this copy.
- **It's only used to read trades.** The Java code that holds the cookie sends a fixed list of read-only
  requests: `GET trades.roblox.com/v1/trades/{inbound|outbound|completed|inactive}` and
  `GET trades.roblox.com/v2/trades/{id}`. It can't send any other URL, method or body, so it can't
  accept, decline, counter or send a trade, or change anything else on your account. The cookie isn't
  passed to the app's Python code, isn't logged, and is only sent to Roblox.
- If Roblox replaces your cookie in a reply, the app saves the new one and copies it back into the Roblox
  page, so you stay signed in there.
- **Turning the option off deletes the copy.** *Sign out of Roblox* and uninstalling the app delete it too.
  Android's cloud backup is turned off for this app, so the copy isn't uploaded.
- Anyone with your unlocked, rooted phone could in principle get the cookie, just like from any browser
  on that phone. If you'd rather not take that risk, leave the option off.

## Settings

| Setting | What it does |
|---|---|
| Ad order | Post ads in order, or pick randomly (never the same ad twice in a row) |
| Extra random delay | Seconds added after each 15-minute cooldown so timing isn't robotic |
| Max ads per 24 hours | Safety cap (default 55) |
| Skip ads offering items I don't own | Checks your Rolimons inventory before posting |
| Only post during these hours | For example 09:00–23:00, or overnight like 18:00–02:00 |
| Warn when an ad overpays / Don't post ads that overpay | Value checks using Rolimons values |
| Smart pick | Posts ads that offer high-demand items more often |
| Keep posting in the tray | Closing the window while posting hides it to the tray |
| Start with Windows | Opens the app (in the tray) when you sign in |
| Start posting automatically | Starts posting as soon as the app opens |
| Show notifications / Check for updates | Windows notifications and update checks |
| Read my trades directly (Android) | Trades list in the app and background new-trade alerts, using a stored copy of your Roblox sign-in ([details](#reading-your-trades-directly-android)) |

## Troubleshooting

| Message | Fix |
|---|---|
| *Rolimons rejected your cookie* | Your cookie was reset (for example by logging out). Get a fresh one (step 1). |
| *⚠ Item not owned* | Rolimons doesn't list that item in your inventory. Its data can lag a few minutes after a trade. |
| *Unknown item IDs* | That item isn't a Rolimons-tracked limited. Edit the ad. |
| *Still on cooldown* | Normal. It waits and retries automatically. |
| Network errors | It retries with growing delays (5s, 10s, 20s… up to 15 min). |

Files the app keeps next to the `.exe` (installed version: `%LOCALAPPDATA%\Programs\Rolimons Ad Poster`):
- `config.json`: your ads and settings
- `.env`: your Rolimons cookie
- `state.json`: post times and history, so a restart still respects the cooldown
- `logs\poster.log`: every post attempt
- `cache\`: item pictures

---

## For developers

Requires Python 3.10+.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python gui.py            # desktop app (add --minimized to start in the tray)
.venv\Scripts\python -m pytest tests   # run the tests
.venv\Scripts\python main.py --check   # CLI: validate setup, post nothing
.venv\Scripts\python main.py --once    # CLI: post one ad
.venv\Scripts\python main.py           # CLI: post on a timer until Ctrl+C
build_exe.bat                          # builds the .exe files, plus the installer if Inno Setup 6 is installed
                                       # (winget install JRSoftware.InnoSetup)
```

The CLI reads `config.json` (see `config.example.json`) and the cookie from `.env`
(see `.env.example`) or the `ROLI_VERIFICATION` environment variable.

Code layout (`roliposter/`): `api.py` (Rolimons requests and replies), `poster.py` (timer loop, rotation,
retries), `inventory.py` (owned items), `schedule.py` (posting hours), `items.py` / `values.py`
(item catalog and value checks), `thumbs.py` (item pictures), `tray.py`, `autostart.py`, `updates.py`,
`theme.py`, `trades_viewer.py` (view-only rules for the trades tab), `roblox_trades.py` (parses Roblox trade
replies for the Android trades list), `webview_embed.py` (WebView2 inside Tk), `config.py`, `cookie.py`, `state.py`, `startup.py`.

### Android app
The Android app lives in `android/` (Kivy) and bundles the same `roliposter` engine. Posting runs in a
foreground service (`android/service.py`) that talks to the screens through `status.json`/`control.json`
(`android/runner.py`). The same service runs the background new-trade checks. The Java helpers live in
`android/java/org/roliposter/`: `ViewOnlyWebViewClient` (blocks trade-changing requests),
`RobloxSession` (the encrypted sign-in copy), `RobloxApi` (the fixed read-only requests),
`TradeWatcher` (background checks) and `TradeNotifier` (notifications).
```
py -3.12 -m venv .venv-mobile
.venv-mobile\Scripts\pip install kivy==2.3.1 requests
.venv-mobile\Scripts\python android\main.py   # phone-sized preview on the PC
```
APKs are built on Linux with Buildozer by GitHub Actions: `android.yml` builds a debug APK and smoke-tests it
on an emulator (screenshots are uploaded as an artifact), and the release workflow builds the signed APK.
Signing uses the `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD` and `ANDROID_KEY_ALIAS` repository secrets.

### Releasing
Bump `__version__` in `roliposter/__init__.py`, commit, then push a matching tag:
```
git tag v1.3.0
git push origin v1.3.0
```
GitHub Actions runs the tests, builds the installer and `.exe` files, and publishes the release.
Tests also run on every push to `main`.

### Code signing
Releases aren't signed, which is why Windows SmartScreen warns on first run. Signing needs a code-signing
certificate (paid), or a free open-source signing service such as SignPath Foundation, which you apply for.

### Endpoint notes
Rolimons has no official API for posting ads, so this may break if they change it.
- `POST https://api.rolimons.com/tradeads/v1/createad`, with the cookie `_RoliVerification`, and a JSON body of
  `player_id`, `offer_item_ids`, `request_item_ids`, `request_tags`.
- Confirmed replies: no cookie returns `401 {"code":4}`, a bad cookie returns `401 {"code":5}`, and an invalid
  ad returns `400 {"code":2}` (for example "Invalid offered item count").
- Confirmed success reply: `201 {"success":true}`.
- The cooldown reply hasn't been seen yet, because the app waits out the cooldown itself. It is detected by
  pattern (a message mentioning "cooldown" or "wait"), and the first one is logged verbatim as
  `Rolimons reply (COOLDOWN): ...` in `logs\poster.log`.
- Owned items: `GET https://api.rolimons.com/players/v1/playerassets/{userId}` (public).

## License

[MIT](LICENSE). Bundled third-party software keeps its own license: Inter font (SIL OFL 1.1,
`assets/fonts/Inter-LICENSE.txt`) and RoValra (GPL-3.0; built by `tools/fetch_rovalra.py`, with its license,
source link and a list of changes in `NOTICE.txt` inside the bundled extension folder).
