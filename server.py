from fastapi import FastAPI, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from typing import Optional
import anyio
import asyncio
import tempfile
import os
import shutil
import logging
import pytesseract
from PIL import Image, UnidentifiedImageError
from app_security import RequestGuardMiddleware
from generate_reel import ai_captions_enabled, process_reel, generate_caption, validate_caption, validate_instagram_url

app = FastAPI(title="Reel Generator API")
MAX_VIDEO_BYTES = int(os.environ.get("MAX_VIDEO_BYTES", 100 * 1024 * 1024))
MAX_SCREENSHOT_BYTES = int(os.environ.get("MAX_SCREENSHOT_BYTES", 10 * 1024 * 1024))
MAX_SCREENSHOT_PIXELS = 20_000_000
OCR_TIMEOUT = 30
logger = logging.getLogger(__name__)
app.add_middleware(
    RequestGuardMiddleware,
    max_video_bytes=MAX_VIDEO_BYTES,
    max_screenshot_bytes=MAX_SCREENSHOT_BYTES,
    max_jobs=int(os.environ.get("MAX_CONCURRENT_JOBS", "1")),
)

html_content = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Reel Generator [TUI]</title>
    <style>
        :root {
            --bg: #050505;
            --fg: #00ff41;
            --dim: #008f11;
            --alert: #ff003c;
            --focus-bg: rgba(0, 255, 65, 0.1);
        }
        * {
            box-sizing: border-box;
        }
        body {
            background-color: var(--bg);
            color: var(--fg);
            font-family: 'Fira Code', 'Courier New', Courier, monospace;
            margin: 0;
            padding: 1rem;
            display: flex;
            justify-content: center;
            line-height: 1.5;
            min-height: 100vh;
            overflow-x: hidden;
        }
        /* CRT overlay effect */
        body::after {
            content: "";
            position: fixed;
            top: 0; left: 0; width: 100vw; height: 100vh;
            background: repeating-linear-gradient(
                0deg,
                rgba(0,0,0,0.15),
                rgba(0,0,0,0.15) 1px,
                transparent 1px,
                transparent 2px
            );
            pointer-events: none;
            z-index: 999;
        }
        
        .container {
            width: 100%;
            max-width: 600px;
            margin-top: 1rem;
            position: relative;
            z-index: 10;
        }
        
        @media (min-width: 480px) {
            .container { margin-top: 2rem; padding: 1rem; }
        }
        
        .ascii-art {
            white-space: pre;
            font-size: clamp(0.45rem, 2.5vw, 0.8rem);
            line-height: 1.2;
            margin-bottom: 2rem;
            text-align: center;
            font-weight: bold;
            overflow-x: hidden;
            text-shadow: 0 0 5px rgba(0, 255, 65, 0.5);
        }
        
        .panel {
            border: 1px solid var(--dim);
            padding: 1.5rem 1rem;
            position: relative;
            margin-bottom: 1.5rem;
            background: rgba(0, 20, 0, 0.6);
            box-shadow: inset 0 0 15px rgba(0, 255, 65, 0.05);
        }
        
        @media (min-width: 480px) {
            .panel { padding: 2rem; }
        }
        
        .panel-title {
            position: absolute;
            top: -0.85rem;
            left: 1rem;
            background: var(--bg);
            padding: 0 0.5rem;
            color: var(--fg);
            font-weight: bold;
        }
        
        .tabs {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 2rem;
            border-bottom: 1px dashed var(--dim);
            padding-bottom: 1rem;
        }
        
        .tab-btn {
            background: none;
            border: none;
            color: var(--dim);
            font-family: inherit;
            font-size: 0.9rem;
            cursor: pointer;
            text-transform: uppercase;
            padding: 0.5rem;
            transition: color 0.2s;
            flex: 1;
            text-align: center;
        }
        
        @media (hover: hover) {
            .tab-btn:hover { color: var(--fg); }
        }
        
        .tab-btn.active {
            color: var(--fg);
            font-weight: bold;
            text-shadow: 0 0 5px rgba(0, 255, 65, 0.5);
        }
        
        .tab-btn.active::before { content: "[ "; color: var(--dim); font-weight: normal; }
        .tab-btn.active::after { content: " ]"; color: var(--dim); font-weight: normal; }
        
        label {
            display: block;
            margin-bottom: 0.5rem;
            color: var(--fg);
            font-size: 0.9rem;
        }
        label::before { content: "> "; color: var(--dim); }
        
        input[type="url"], input[type="file"], textarea {
            width: 100%;
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid var(--dim);
            color: var(--fg);
            padding: 0.8rem;
            font-family: inherit;
            font-size: 1rem;
            outline: none;
            margin-bottom: 1.5rem;
            transition: all 0.2s;
            border-radius: 0;
            -webkit-appearance: none;
        }
        
        input:focus, textarea:focus {
            border-color: var(--fg);
            background: var(--focus-bg);
            box-shadow: 0 0 8px rgba(0, 255, 65, 0.2);
        }
        
        textarea {
            resize: vertical;
            min-height: 120px;
        }
        
        input[type="file"]::file-selector-button {
            background: var(--dim);
            color: var(--bg);
            border: none;
            padding: 0.5rem 1rem;
            margin-right: 1rem;
            font-family: inherit;
            cursor: pointer;
            text-transform: uppercase;
            font-weight: bold;
            transition: background 0.2s;
        }
        
        @media (hover: hover) {
            input[type="file"]::file-selector-button:hover {
                background: var(--fg);
            }
        }
        
        .action-btn {
            width: 100%;
            background: transparent;
            color: var(--fg);
            border: 1px solid var(--fg);
            padding: 1rem;
            font-family: inherit;
            font-size: 1.1rem;
            font-weight: bold;
            cursor: pointer;
            text-transform: uppercase;
            transition: all 0.2s;
            margin-top: 0.5rem;
        }
        
        @media (hover: hover) {
            .action-btn:hover {
                background: var(--fg);
                color: var(--bg);
                box-shadow: 0 0 15px rgba(0, 255, 65, 0.4);
            }
        }
        
        .action-btn:active {
            background: var(--fg);
            color: var(--bg);
            transform: translateY(2px);
        }
        
        .opt-box {
            border: 1px dashed var(--dim);
            padding: 1rem;
            margin-bottom: 1.5rem;
            background: rgba(0, 50, 0, 0.1);
        }
        
        .opt-box label {
            color: var(--dim);
        }
        
        .opt-btn {
            background: transparent;
            color: var(--dim);
            border: 1px dashed var(--dim);
            padding: 0.6rem 1rem;
            font-size: 0.9rem;
            margin-bottom: 1rem;
            cursor: pointer;
            font-family: inherit;
            text-transform: uppercase;
            width: 100%;
            transition: all 0.2s;
        }
        
        @media (hover: hover) {
            .opt-btn:hover {
                color: var(--fg);
                border-color: var(--fg);
                background: var(--focus-bg);
            }
        }
        
        .opt-btn:active {
            background: var(--dim);
            color: var(--bg);
        }
        
        .loader {
            display: none;
            text-align: center;
            margin-top: 1.5rem;
            color: var(--fg);
            font-weight: bold;
        }
        
        .cursor-blink {
            display: inline-block;
            width: 8px;
            height: 1em;
            background-color: var(--fg);
            vertical-align: middle;
            animation: blink 1s step-end infinite;
            margin-left: 5px;
        }
        
        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0; }
        }
        
        #status-text {
            display: none;
            text-align: center;
            margin-top: 1rem;
            color: var(--dim);
            font-size: 0.9rem;
        }
        @media (max-width: 600px) {
            body {
                padding: 0.75rem 0.75rem max(0.75rem, env(safe-area-inset-bottom));
                line-height: 1.35;
            }
            .container { margin-top: 0; padding: 0; }
            .ascii-art {
                font-size: 0.6rem;
                margin-bottom: 1.25rem;
                line-height: 1;
            }
            .panel { padding: 0.75rem; margin-bottom: 0; }
            .panel-title { font-size: 0.8rem; top: -0.65rem; }
            .tabs { margin-bottom: 0.75rem; padding-bottom: 0.4rem; gap: 0.25rem; }
            .tab-btn { min-height: 44px; padding: 0.4rem 0.2rem; font-size: 0.8rem; }
            label { margin-bottom: 0.3rem; font-size: 0.8rem; }
            input[type="url"], input[type="file"], textarea {
                padding: 0.5rem;
                margin-bottom: 0.75rem;
                font-size: 1rem;
            }
            input[type="file"] { min-height: 44px; margin-bottom: 0; }
            input[type="file"]::file-selector-button {
                padding: 0.4rem 0.6rem;
                margin-right: 0.5rem;
            }
            #video-help, #screenshot-help {
                margin: 0.35rem 0 0.75rem;
                font-size: 0.75rem;
            }
            .opt-box { padding: 0.6rem; margin-bottom: 0.75rem; }
            .opt-btn { min-height: 44px; padding: 0.5rem; margin-bottom: 0; }
            textarea { min-height: 80px; }
            .action-btn { min-height: 44px; padding: 0.6rem; margin-top: 0; font-size: 0.95rem; }
            .loader, #status-text { margin-top: 0.75rem; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="ascii-art">
  ___ _____ ___ _      ___ ___ _  _ 
 | _ \ __| __| |    / __| __| \| |
 |   / _|| _|| |__ | (_ | _|| .` |
 |_|_\___|___|____| \___|___|_|\_|
        </div>
        
        <div class="panel">
            <span class="panel-title">SYSTEM.CONSOLE</span>
            <form id="genForm">
                <div class="tabs">
                    <button type="button" class="tab-btn active" id="btn-url" onclick="switchTab('url')">URL_FETCH</button>
                    <button type="button" class="tab-btn" id="btn-custom" onclick="switchTab('custom')">LOCAL_UPLOAD</button>
                </div>
                
                <div id="url-section">
                    <label for="url">TARGET_URL</label>
                    <input type="url" id="url" name="url" placeholder="https://www.instagram.com/..." required>
                </div>
                
                <div id="custom-section" style="display: none;">
                    <label for="video">VIDEO_PAYLOAD</label>
                    <input type="file" id="video" name="video" accept="video/*" aria-describedby="video-help" disabled>
                    <p id="video-help">Maximum video size: 100 MiB.</p>
                    
                    <div class="opt-box">
                        <label for="screenshot">MODULE: OCR_CAPTION (OPTIONAL)</label>
                        <input type="file" id="screenshot" accept="image/*" aria-describedby="screenshot-help" disabled>
                        <p id="screenshot-help">Maximum screenshot size: 10 MiB.</p>
                        <button type="button" id="btn-generate-caption" class="opt-btn" onclick="generateCaption()" disabled>EXECUTE_OCR</button>
                        <div class="loader" id="caption-loader" role="status">PROCESSING<span class="cursor-blink"></span></div>
                    </div>

                </div>

                <p id="ai-caption-status" style="display: none;">AI captions are disabled. Enter a caption below.</p>
                <label for="caption">CAPTION</label>
                <textarea id="caption" name="caption" maxlength="500" placeholder="Enter text... use {brackets} for highlight"></textarea>
                
                <button type="submit" id="submitBtn" class="action-btn">INITIATE_SEQUENCE</button>
                <div class="loader" id="loader">GENERATING_REEL<span class="cursor-blink"></span></div>
                <div id="status-text" role="status">[ Processing video stream. Please stand by... ]</div>
            </form>
        </div>
    </div>

    <script>
        const aiCaptionsEnabled = __AI_CAPTIONS_ENABLED__;
        let currentMode = 'url';
        let generating = false;
        let extractingCaption = false;

        function updateControls() {
            const busy = generating || extractingCaption;
            const urlMode = currentMode === 'url';
            document.getElementById('url').disabled = busy || !urlMode;
            document.getElementById('url').required = urlMode;
            document.getElementById('video').required = !urlMode;
            document.getElementById('video').disabled = busy || urlMode;
            document.getElementById('caption').required = !urlMode || !aiCaptionsEnabled;
            document.getElementById('caption').disabled = busy;
            for (const id of ['screenshot', 'btn-generate-caption']) {
                document.getElementById(id).disabled = busy || urlMode || !aiCaptionsEnabled;
            }
            document.getElementById('ai-caption-status').style.display = aiCaptionsEnabled ? 'none' : 'block';
            for (const id of ['btn-url', 'btn-custom', 'submitBtn']) {
                document.getElementById(id).disabled = busy;
            }
        }

        window.switchTab = function(mode) {
            if (generating || extractingCaption || !['url', 'custom'].includes(mode)) return;
            currentMode = mode;
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.classList.remove('active');
                btn.setAttribute('aria-pressed', String(btn.id === 'btn-' + mode));
            });
            document.getElementById('btn-' + mode).classList.add('active');
            document.getElementById('url-section').style.display = mode === 'url' ? 'block' : 'none';
            document.getElementById('custom-section').style.display = mode === 'custom' ? 'block' : 'none';
            updateControls();
        };

        async function responseError(response, fallback) {
            try {
                const text = await response.text();
                try {
                    const data = JSON.parse(text);
                    if (typeof data.detail === 'string') return data.detail;
                    if (Array.isArray(data.detail)) return data.detail.map(item => item.msg).join('; ');
                } catch {}
                if (text && !text.trimStart().startsWith('<')) return text;
            } catch {}
            return `${fallback} (HTTP ${response.status}).`;
        }

        async function generateCaption() {
            if (generating || extractingCaption || currentMode !== 'custom' || !aiCaptionsEnabled) return;
            const screenshotInput = document.getElementById('screenshot');
            const captionArea = document.getElementById('caption');
            const btn = document.getElementById('btn-generate-caption');
            const loader = document.getElementById('caption-loader');
            
            if (!screenshotInput.files[0]) {
                alert('ERROR: Missing screenshot payload.');
                return;
            }
            if (screenshotInput.files[0].size > 10 * 1024 * 1024) {
                alert('ERROR: Screenshot must be 10 MiB or smaller.');
                return;
            }
            
            extractingCaption = true;
            updateControls();
            btn.style.display = 'none';
            loader.style.display = 'block';
            
            try {
                const formData = new FormData();
                formData.append('screenshot', screenshotInput.files[0]);
                
                const response = await fetch('/api/extract-caption', {
                    method: 'POST',
                    body: formData
                });
                
                if (!response.ok) {
                    throw new Error(await responseError(response, 'Caption extraction failed'));
                }
                
                const data = await response.json();
                if (typeof data.caption !== 'string' || !data.caption.trim()) {
                    throw new Error('No caption was returned. Try a clearer screenshot or enter a caption.');
                }
                if (data.caption.length > 500) {
                    throw new Error('The extracted caption is too long. Enter a caption of up to 500 characters.');
                }
                captionArea.value = data.caption;
            } catch (err) {
                alert('OCR_FAULT: ' + err.message);
            } finally {
                extractingCaption = false;
                updateControls();
                btn.style.display = 'block';
                loader.style.display = 'none';
            }
        }

        document.getElementById('genForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            if (generating || extractingCaption) return;
            const btn = document.getElementById('submitBtn');
            const loader = document.getElementById('loader');
            const statusText = document.getElementById('status-text');
            if (currentMode === 'custom' && document.getElementById('video').files[0]?.size > 100 * 1024 * 1024) {
                alert('ERROR: Video must be 100 MiB or smaller.');
                return;
            }
            
            generating = true;
            updateControls();
            btn.style.display = 'none';
            loader.style.display = 'block';
            statusText.style.display = 'block';
            
            try {
                const formData = new FormData();
                if (currentMode === 'url') {
                    formData.append('url', document.getElementById('url').value);
                } else {
                    formData.append('video', document.getElementById('video').files[0]);
                }
                const captionVal = document.getElementById('caption').value;
                if (captionVal) formData.append('caption', captionVal);
                
                const response = await fetch('/api/generate', {
                    method: 'POST',
                    body: formData
                });
                
                if (!response.ok) {
                    throw new Error(await responseError(response, 'Reel generation failed'));
                }
                
                const blob = await response.blob();
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.style.display = 'none';
                a.href = downloadUrl;
                
                let counter = 1;
                try {
                    const storedCounter = Number(localStorage.getItem('bluntIndianCounter'));
                    if (Number.isSafeInteger(storedCounter) && storedCounter > 0) counter = storedCounter;
                } catch {}
                const paddedCounter = String(counter).padStart(5, '0');
                a.download = `BLUNT INDIAN V${paddedCounter}.mp4`;
                try {
                    document.body.appendChild(a);
                    a.click();
                    try {
                        localStorage.setItem('bluntIndianCounter', counter < Number.MAX_SAFE_INTEGER ? counter + 1 : 1);
                    } catch {}
                } finally {
                    a.remove();
                    // Give the browser time to begin saving before releasing the blob.
                    setTimeout(() => window.URL.revokeObjectURL(downloadUrl), 60000);
                }
                
            } catch (err) {
                alert('SYS_ERROR: ' + err.message);
            } finally {
                generating = false;
                updateControls();
                btn.style.display = 'block';
                loader.style.display = 'none';
                statusText.style.display = 'none';
            }
        });
        switchTab('url');
    </script>
</body>
</html>
"""

def cleanup_dir(path: str):
    shutil.rmtree(path, ignore_errors=True)


async def run_worker(function, *args):
    """Keep a cancelled request's worker alive until it releases its resources."""
    task = asyncio.create_task(run_in_threadpool(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Task.cancel() bypasses an AnyIO cancellation scope. Do not release the
        # job slot or delete working files while its thread is still running.
        with anyio.CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                task.exception()  # Retrieve any worker exception before re-raising cancellation.
        raise


class ReelFileResponse(FileResponse):
    def __init__(self, path, temp_dir):
        super().__init__(path, media_type="video/mp4", filename="output_reel.mp4",
                         headers={"Cache-Control": "no-store"})
        self.temp_dir = temp_dir

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await run_worker(cleanup_dir, self.temp_dir)


def save_upload(upload, destination, limit):
    """Copy from the multipart spool without loading the whole video into RAM."""
    upload.seek(0)
    size = 0
    with open(destination, "wb") as target:
        while chunk := upload.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise HTTPException(status_code=413, detail="The video exceeds the allowed size.")
            target.write(chunk)
    if size == 0:
        raise ValueError("Choose a nonempty video file.")


def render_job(temp_dir, url, caption, video):
    custom_video_path = None
    if video is not None:
        custom_video_path = os.path.join(temp_dir, "uploaded_video.mp4")
        save_upload(video.file, custom_video_path, MAX_VIDEO_BYTES)
    return process_reel(url=url, output_dir=temp_dir, custom_video_path=custom_video_path,
                        custom_caption=caption)


def caption_from_screenshot(screenshot):
    screenshot.file.seek(0, os.SEEK_END)
    size = screenshot.file.tell()
    if size > MAX_SCREENSHOT_BYTES:
        raise HTTPException(status_code=413, detail="The screenshot exceeds the allowed size.")
    screenshot.file.seek(0)
    try:
        with Image.open(screenshot.file) as source:
            if source.width * source.height > MAX_SCREENSHOT_PIXELS:
                raise ValueError("The screenshot is too large. Use an image below 20 megapixels.")
            # A detached image also keeps the uploaded file lifetime independent of OCR.
            image = source.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Choose a valid screenshot image.") from exc
    try:
        extracted_text = pytesseract.image_to_string(image, timeout=OCR_TIMEOUT).strip()
    except RuntimeError as exc:
        raise RuntimeError("Reading the screenshot timed out. Try a smaller image.") from exc
    finally:
        image.close()
    if not extracted_text:
        raise ValueError("No text could be read. Try a clearer screenshot or enter a caption.")
    return generate_caption(extracted_text[:12000])


@app.get("/", response_class=HTMLResponse)
async def get_frontend():
    ai_enabled = ai_captions_enabled()
    return html_content.replace("__AI_CAPTIONS_ENABLED__", "true" if ai_enabled else "false")


@app.get("/login")
async def legacy_login():
    return RedirectResponse("/", status_code=303)


@app.get("/api/health")
async def health():
    return JSONResponse({"ok": True},
                        headers={"Cache-Control": "no-store"})


@app.post("/api/generate")
async def generate_reel_endpoint(
    url: Optional[str] = Form(None),
    caption: Optional[str] = Form(None),
    video: Optional[UploadFile] = File(None),
):
    has_video = video is not None and bool(video.filename)
    url = url.strip() if url else None
    if bool(url) == has_video:
        raise HTTPException(status_code=422, detail="Provide either an Instagram URL or one video file.")
    try:
        if url:
            url = validate_instagram_url(url)
        if caption is not None:
            caption = validate_caption(caption)
        if has_video and not caption:
            raise ValueError("Add a caption or extract one from a screenshot before uploading.")
        if not caption and not ai_captions_enabled():
            raise ValueError("AI captions are disabled. Enter a caption before generating a reel.")
        if has_video and video.size is not None and video.size > MAX_VIDEO_BYTES:
            raise HTTPException(status_code=413, detail="The video exceeds the allowed size.")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    temp_dir = tempfile.mkdtemp(prefix="reel_gen_")
    # Wait for the worker to finish before cleaning its files if the request is cancelled.
    with anyio.CancelScope(shield=True):
        try:
            output_path = await run_worker(render_job, temp_dir, url, caption,
                                           video if has_video else None)
            return ReelFileResponse(output_path, temp_dir)
        except BaseException as exc:
            await run_worker(cleanup_dir, temp_dir)
            if isinstance(exc, HTTPException):
                raise
            if isinstance(exc, ValueError):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if isinstance(exc, RuntimeError):
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            if isinstance(exc, Exception):
                logger.exception("Reel generation failed")
                raise HTTPException(status_code=500, detail="Unable to generate the reel. Check the server log.") from exc
            raise


@app.post("/api/extract-caption")
async def extract_caption(screenshot: UploadFile = File(...)):
    if not ai_captions_enabled():
        raise HTTPException(status_code=503, detail="AI captions are disabled. Enter a caption manually.")
    with anyio.CancelScope(shield=True):
        try:
            caption = await run_worker(caption_from_screenshot, screenshot)
            return {"caption": caption}
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Screenshot caption generation failed")
            raise HTTPException(status_code=500, detail="Unable to read the screenshot. Check the server log.") from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7008)
