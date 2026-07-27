# MyAnimeList connection

Ko-Stream can import **your full MAL animelist** into the catalog (title, synopsis, poster, list status).

## 1. Register a MAL API app

1. Go to https://myanimelist.net/apiconfig
2. Click **Create ID**
3. App name: `Ko-Stream Local` (anything)
4. App type: **Other**
5. Redirect URI — pick **one** and use it everywhere (must match exactly):

   **`http://localhost:5001/auth/mal/callback`** (recommended)

   or

   **`http://127.0.0.1:5001/auth/mal/callback`**

   `localhost` and `127.0.0.1` are **not** interchangeable for MAL.

6. Save **Client ID** and **Client Secret**

## 2. Set environment variables

PowerShell (same session as `ko-stream serve`):

```powershell
$env:MAL_CLIENT_ID = "your-client-id"
$env:MAL_CLIENT_SECRET = "your-client-secret"
$env:MAL_REDIRECT_URI = "http://localhost:5001/auth/mal/callback"
```

## 3. Connect in the UI

1. Start Ko-Stream: `ko-stream serve` (must stay running)
2. Open http://127.0.0.1:5001/catalog → **Connect MyAnimeList**
3. Follow the 3 steps on the connect page

## Login loop (password asked again and again)

This happens **on MyAnimeList’s site**, before Ko-Stream receives anything. Try in order:

1. **Redirect URI mismatch** — at https://myanimelist.net/apiconfig the Redirect URL must be **character-for-character** identical to `MAL_REDIRECT_URI` (including `localhost` vs `127.0.0.1` and port `5001`).
2. **Log in first** — on the connect page use **Step 1: Log in to MyAnimeList**, then **Step 2: Authorize**.
3. **Normal login** — open https://myanimelist.net/login.php in the same browser, confirm you see your profile, then retry.
4. **Extensions** — disable ad blockers / privacy tools for `myanimelist.net`.
5. **Another browser** — try Chrome or Firefox.
6. **No autofill** — type username and password manually.

## Manual fallback

If authorization works but redirect fails (browser shows “can’t connect”):

1. Copy the **full URL** from the address bar (contains `?code=...`)
2. Paste it on the connect page → **Complete connection**

Ko-Stream must still be running and you must have opened Connect within the last 30 minutes.

## Re-sync later

On the Catalog page: **Sync animelist now**

Sync also refreshes your mangalist and (for anime) batches **episode titles** from Jikan / MAL HTML into `data/mal/cache/`. Manga and manhwa do **not** get chapter titles from Sync: neither the official MAL API nor Jikan exposes per-chapter names (only `num_chapters`). Local chapter labels come from folder/CBZ filenames and optional `ComicInfo.xml` inside CBZ files.

## Security

- Tokens stored locally in `data/mal/tokens.json` (gitignored)
- Never commit Client Secret or tokens
