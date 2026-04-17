# Deploying to Render

Click-by-click guide to get this running at a public URL so your team can use it from a browser.

**Total time:** ~10 minutes the first time. After that, every `git push` redeploys automatically.

**Cost:** $9.50/mo total
- Starter web service: $7/mo
- Persistent disk (10 GB): $2.50/mo

---

## 1. Create a Render account

1. Go to https://render.com
2. Click **Sign Up** → **Sign in with GitHub**
3. Authorize Render to see your repos

## 2. Create the web service

1. From the Render dashboard, click **New +** → **Blueprint**
2. Under **Connect a repository**, pick `aymanar4b/ai-video-editor`
3. Render will detect the `render.yaml` file and show a preview of what it's going to create (1 web service + 1 disk)
4. Click **Apply**

## 3. Set the environment variables

Render will ask for the 3 secret values (defined in `render.yaml` with `sync: false`):

| Variable | Value |
|---|---|
| `NANO_BANANA_API_KEY` | Your Gemini API key (from https://aistudio.google.com/apikey) |
| `OPENAI_API_KEY` | Your OpenAI key, or leave empty if not using GPT Image 1.5 |
| `APP_PASSWORD` | The shared password for your team (e.g. `tikscalejohn2002`) |

Paste each value and click **Save**.

## 4. Wait for the first build

- First deploy takes **5-10 minutes** — it's pulling the Python image, installing deps, and downloading the MediaPipe face model.
- Watch progress in the **Logs** tab.
- When it says `Listening on 0.0.0.0:10000`, you're live.

## 5. Get your URL

At the top of the service page, Render shows a URL like:

```
https://tikscale-thumbnails.onrender.com
```

Visit it. Your browser will prompt for a username and password:
- **Username:** `tikscale`
- **Password:** whatever you set for `APP_PASSWORD`

Done. Share the URL + password with your team.

---

## Updating the app

Any time you push to `main` on GitHub:

```bash
git add .
git commit -m "your changes"
git push origin main
```

Render auto-detects the push, rebuilds, and redeploys in ~2 minutes. Your team just refreshes the page.

---

## Troubleshooting

### "Application failed to respond"

Check the Render Logs tab for the actual error. Most common causes:
- Missing `NANO_BANANA_API_KEY` → paste it into the env vars
- Out of memory on first generation → bump plan from `starter` to `standard` in `render.yaml`
- Crash during startup → scroll to the first Python traceback in logs

### Generations fail silently

Each generation takes 1-3 min. Render's free tier kills long-running requests at 30s, but the starter plan ($7/mo) allows 10 min — that's why we're on starter, not free.

If you accidentally downgraded to free, bump it back up in the service settings.

### Gemini quota exhausted

The error card will tell you directly: "Gemini API quota exhausted — wait and retry." Either wait 60 seconds or upgrade your Gemini API key to paid billing at https://aistudio.google.com/apikey.

### OpenAI key not working

Error card will say "OPENAI_API_KEY is empty" or "OpenAI API key is invalid". Check:
1. Env var is set in Render dashboard (Service → Environment)
2. Key starts with `sk-proj-` or `sk-`
3. You've added billing at https://platform.openai.com/account/billing (the API doesn't work without a paid balance)

### Disk is full

10 GB fits thousands of thumbnails, but if generations pile up you may eventually hit it. Options:
1. Clear old generations via SSH into the Render shell
2. Bump `sizeGB` in `render.yaml` (costs $0.25/GB/mo more)

---

## Local development

Nothing about this setup breaks local dev. When `APP_PASSWORD` is empty (which it is in your local `.env`), auth is disabled. Just run `python app.py` as always.
