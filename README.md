# 🎬 Instagram Reel Generator

![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)

> **Create portrait videos with stunning headline overlays from Instagram URLs or video uploads.** 
> Built with FFmpeg for rendering, Pillow for drawing, Tesseract for OCR, and OpenRouter for AI-powered headlines.

## ✨ Features
- **URL & Upload Support**: Paste an Instagram URL or upload your own video.
- **AI Captions**: Automatically extract text from screenshots using Tesseract and generate headlines via OpenRouter.
- **Mobile-Friendly**: Run on GitHub Codespaces right from your phone.
- **Local Deployment**: Fully containerized with Docker for easy local setup.

---

## Run on GitHub from your phone

The app runs in the existing GitHub Codespace for short sessions; your local computer can stay off. Set up the [five-action iPhone shortcut](IPHONE.md) once, then:

1. Tap **Reel Generator**. The shortcut wakes the Codespace and opens the app in Safari.
2. Paste an Instagram URL and leave the caption blank for AI, or upload a video and enter a caption or generate one from a screenshot. Generate and download your reel. Use Upload if Instagram blocks a URL download.
3. Close Safari when finished. GitHub stops the Codespace after its idle timeout; it does not need to run all day.

The current idle window is **10 minutes**, and app activity alone does not guarantee an extension. If startup takes longer than the shortcut's wait, refresh the page. Sign in to GitHub if prompted; no additional app login is required.

With **no payment method saved**, GitHub blocks Codespaces when the included allowance runs out. No billing setup or upgrade is needed. If you later add a payment method, first set a $0 Codespaces budget that stops paid usage. See [GitHub's billing rules](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces).

See [CODESPACES.md](CODESPACES.md) for the browser-only fallback and maintenance details.

## Optional local Docker setup

Install Docker, Docker Compose, and Python 3, then:

```bash
python3 scripts/setup-env.py
# Optionally set OPENROUTER_API_KEY in .env for automatic captions.
docker compose up -d --build
```

Open <http://localhost:5050>. Docker publishes port 5050, mapped to the app's internal port 7008. No app login or password is required. The setup command creates private configuration and refuses to overwrite an existing `.env`. Set `OPENROUTER_API_KEY` in `.env` for AI captions; never commit that file.

Compose binds to localhost by default. For phone access, use the private HTTPS Codespaces flow in [CODESPACES.md](CODESPACES.md), or configure an HTTPS reverse proxy restricted to your account. `BIND_ADDRESS` can change the Compose binding when setting up that proxy.

Dependencies are pinned in `requirements.txt`. Rebuild after pulling dependency changes. Container builds copy only runtime files and assets, run as an unprivileged user, and exclude local credentials, archives, virtual environments, and Git history. The container health check uses the unauthenticated minimal `/api/health` response.

## Make a reel

- **Upload:** choose a video and enter a caption. A silent video is supported. Optionally upload a screenshot and extract an AI caption; that step requires a configured OpenRouter key. OCR errors preserve your current caption.
- **Instagram URL:** paste a supported Instagram URL. A manual caption skips AI generation; automatic headlines require `OPENROUTER_API_KEY`. Instagram may block cloud IPs even with cookies; use Upload when downloading fails.

The app validates inputs and bounds processing. Defaults are 100 MiB per video, 10 MiB per screenshot, 180 seconds of video, and one active processing job. Concurrent work gets HTTP 429 instead of creating an unbounded queue. Oversized uploads return 413. Captions have a 500-character limit and must fit the overlay; the API returns a clear validation error when they cannot fit.

These limits can be configured with `MAX_VIDEO_BYTES`, `MAX_SCREENSHOT_BYTES`, `MAX_VIDEO_SECONDS`, and `MAX_CONCURRENT_JOBS`. `DOWNLOAD_TIMEOUT_SECONDS` defaults to 180 and `RENDER_TIMEOUT_SECONDS` to 600. `OPENROUTER_MODEL` can select a supported free model; it cannot enable paid inference. Free-service availability and rate limits depend on the provider and account.

## Optional Instagram cookies

Cookies are optional and contain account credentials. Export a Netscape-format cookie file, keep it private (`chmod 600`), and set `COOKIES_PATH` in `.env` to its absolute path. Then use:

```bash
docker compose -f docker-compose.yml -f docker-compose.cookies.yml up -d --build
```

The override mounts the existing file read-only and refuses to create a missing source path. It runs as the host `REEL_UID` and `REEL_GID` written by the setup command, so private cookie files remain readable without changing their permissions. If `.env` predates those fields, add your `id -u` and `id -g` values. The application copies cookies into a private job directory before calling yt-dlp, which may update its own copy.

For Codespaces, use the optional `COOKIES_TXT` secret instead of a host bind mount. Never add cookies to the Docker build or source control.

## API

Application routes, processing, and API documentation require no app credentials. `GET /api/health` returns `{"ok":true}` when the server is running. Keep the Codespaces port private or use localhost for local access.

`POST /api/generate` accepts multipart form fields `url` or `video`, plus optional `caption`, and returns `video/mp4`. Uploaded videos require `caption` (entered manually or obtained from OCR). `POST /api/extract-caption` accepts `screenshot` and returns a generated `caption`. Errors use a JSON `detail` message. Check HTTP status before saving a response as a video.

For example:

```bash
curl --fail-with-body \
  --form 'video=@clip.mp4' \
  --form 'caption=Your headline here' \
  http://localhost:5050/api/generate --output reel.mp4
```

A private Codespaces port requires GitHub authentication; no additional app login is needed. The phone browser flow is documented separately.

## Run locally without Docker

Install Python 3.11 or newer, FFmpeg (including `ffprobe`), and Tesseract OCR using your system package manager. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/setup-env.py
bash scripts/run-local.sh
```

Skip setup if `.env` already exists. The launcher loads `.env` as trusted shell configuration; keep values shell-compatible and quote any spaces. The server listens on port 7008. `font.ttf` and `logo.png` are required runtime assets and are included in the Docker image.

## Checks

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
node tests/frontend.test.cjs
```

Media integration checks need FFmpeg and Tesseract; browser-script checks use Node.js. Tests use temporary files and mocked external services; they do not consume OpenRouter credits or change a live Codespace.

## Existing credential exposure

Earlier versions included API credentials in source and cookie data in Git history and locally built images. Removing current literals does not revoke those credentials or erase old copies:

1. Revoke the exposed OpenRouter key in your provider account and configure a new key locally and in Codespaces secrets.
2. Invalidate the exposed Instagram sessions and export fresh cookies if URL downloads need them.
3. Rebuild the runtime image from the corrected Dockerfile. Remove old credential-bearing images and backups after checking whether anything still relies on them.
4. Coordinate Git history cleanup with repository collaborators before rewriting or force-pushing history. Existing clones and archives retain their own copies.

This change does not rotate provider credentials, delete existing backups/images, or rewrite shared history. Keep `.env`, cookies, and the local backup archives out of source control.
