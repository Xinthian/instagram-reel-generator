import asyncio
import io
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI, File, UploadFile
from PIL import Image

import server
from app_security import RequestGuardMiddleware


def screenshot_bytes():
    output = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(output, "PNG")
    return output.getvalue()


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {"OPENROUTER_API_KEY": "review-dummy-key", "AI_CAPTIONS_ENABLED": "true"})
        self.env.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.env.stop()

    async def test_app_and_api_work_without_credentials(self):
        with patch.dict(os.environ, {"REEL_APP_PASSWORD": ""}):
            for path in ["/", "/docs", "/openapi.json"]:
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("www-authenticate", response.headers)
                self.assertNotIn("set-cookie", response.headers)
            response = await self.client.get("/api/health")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True})
            response = await self.client.post("/api/generate", data={})
            self.assertEqual(response.status_code, 422)
            with patch.object(server, "caption_from_screenshot", return_value="AI caption"):
                response = await self.client.post("/api/extract-caption",
                    files={"screenshot": ("text.png", screenshot_bytes(), "image/png")})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"caption": "AI caption"})

    async def test_old_login_bookmark_opens_app(self):
        response = await self.client.get("/login")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")

    async def test_forwarded_origin_is_allowed_without_login(self):
        response = await self.client.post("/api/generate", headers={
            "Host": "localhost:7008",
            "Origin": "https://reel-generator-7008.app.github.dev",
            "X-Forwarded-Host": "reel-generator-7008.app.github.dev",
        })
        self.assertEqual(response.status_code, 422)

    async def test_cross_site_submission_is_rejected(self):
        response = await self.client.post("/api/generate", headers={"Origin": "https://unrelated.example"})
        self.assertEqual(response.status_code, 403)
        # HTTPS forwarding is valid even if the reverse proxy talks HTTP locally.
        response = await self.client.post("/api/generate", headers={"Origin": "https://test"})
        self.assertEqual(response.status_code, 422)

    async def test_input_validation(self):
        for data in [{}, {"url": "http://localhost/private"}, {"url": "https://example.com/reel/abc"}]:
            response = await self.client.post("/api/generate", data=data)
            self.assertEqual(response.status_code, 422)
        response = await self.client.post("/api/generate",
                                          files={"video": ("clip.mp4", b"fake", "video/mp4")})
        self.assertEqual(response.status_code, 422)
        self.assertIn("caption", response.json()["detail"])

    async def test_upload_limit_before_parsing(self):
        response = await self.client.post("/api/generate", headers={"Content-Length": str(server.MAX_VIDEO_BYTES + 2**20 + 1)})
        self.assertEqual(response.status_code, 413)

    async def test_response_cleanup_and_streamed_upload(self):
        directories = []
        def render(**kwargs):
            directory = Path(kwargs["output_dir"])
            directories.append(directory)
            self.assertEqual(Path(kwargs["custom_video_path"]).read_bytes(), b"video payload")
            output = directory / "output.mp4"
            output.write_bytes(b"rendered payload")
            return str(output)
        with patch.object(server, "process_reel", side_effect=render):
            response = await self.client.post("/api/generate", data={"caption": "Review caption"},
                                              files={"video": ("clip.mp4", b"video payload", "video/mp4")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"rendered payload")
        self.assertTrue(all(not path.exists() for path in directories))

    async def test_failure_cleanup(self):
        directories = []
        def fail(**kwargs):
            directories.append(Path(kwargs["output_dir"]))
            raise RuntimeError("The download timed out.")
        with patch.object(server, "process_reel", side_effect=fail):
            response = await self.client.post("/api/generate",
                                              data={"url": "https://www.instagram.com/reel/abc/"})
        self.assertEqual(response.status_code, 502)
        self.assertTrue(all(not path.exists() for path in directories))

    async def test_render_does_not_block_health_and_limits_jobs(self):
        entered, release = threading.Event(), threading.Event()
        def render(**kwargs):
            entered.set()
            if not release.wait(4):
                raise AssertionError("Test failed to release worker")
            output = Path(kwargs["output_dir"]) / "out.mp4"
            output.write_bytes(b"video")
            return str(output)
        with patch.object(server, "process_reel", side_effect=render):
            pending = asyncio.create_task(self.client.post("/api/generate",
                                                          data={"url": "https://www.instagram.com/reel/abc/"}))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                response = await asyncio.wait_for(self.client.get("/api/health"), timeout=.5)
                self.assertEqual(response.status_code, 200)
                busy = await self.client.post("/api/generate",
                                               data={"url": "https://www.instagram.com/reel/abc/"})
                self.assertEqual(busy.status_code, 429)
                self.assertEqual(busy.headers["retry-after"], "2")
            finally:
                release.set()
                self.assertEqual((await pending).status_code, 200)

    async def test_cancellation_waits_for_worker_before_cleanup(self):
        entered, release = threading.Event(), threading.Event()
        directories = []
        def render(**kwargs):
            directory = Path(kwargs["output_dir"])
            directories.append(directory)
            entered.set()
            if not release.wait(4):
                raise AssertionError("Worker not released")
            output = directory / "out.mp4"
            output.write_bytes(b"video")
            return str(output)
        with patch.object(server, "process_reel", side_effect=render):
            pending = asyncio.create_task(self.client.post("/api/generate",
                data={"url": "https://www.instagram.com/reel/abc/"}))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                pending.cancel()
                await asyncio.sleep(.05)
                self.assertFalse(pending.done())
                self.assertTrue(directories[0].exists())
                busy = await self.client.post("/api/generate")
                self.assertEqual(busy.status_code, 429)
                pending.cancel()  # Repeated cancellation must not abandon the thread.
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
            self.assertFalse(directories[0].exists())

    async def test_failed_download_send_cleans_output(self):
        directory = Path(tempfile.mkdtemp(prefix="reel-response-test-"))
        path = directory / "out.mp4"
        path.write_bytes(b"video")
        response = server.ReelFileResponse(path, str(directory))
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            if message["type"] == "http.response.body":
                raise OSError("client disconnected")
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                 "http_version": "1.1", "method": "GET", "headers": []}
        with self.assertRaises(OSError):
            await response(scope, receive, send)
        self.assertFalse(directory.exists())

    async def test_ocr_no_text_is_error_without_ai_call(self):
        with patch.object(server.pytesseract, "image_to_string", return_value=""), \
             patch.object(server, "generate_caption") as ai:
            response = await self.client.post("/api/extract-caption",
                files={"screenshot": ("image.png", screenshot_bytes(), "image/png")})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("caption", response.json())
        ai.assert_not_called()

    async def test_ai_disabled_requires_manual_caption_before_processing(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}), \
             patch.object(server, "process_reel") as render, \
             patch.object(server, "caption_from_screenshot") as ocr:
            response = await self.client.post("/api/generate",
                data={"url": "https://www.instagram.com/reel/abc/"})
            self.assertEqual(response.status_code, 422)
            self.assertIn("AI captions are disabled", response.json()["detail"])
            response = await self.client.post("/api/extract-caption",
                files={"screenshot": ("image.png", screenshot_bytes(), "image/png")})
            self.assertEqual(response.status_code, 503)
            render.assert_not_called()
            ocr.assert_not_called()

    async def test_explicit_ai_opt_out_disables_ui_and_processing_with_key(self):
        with patch.dict(os.environ, {"AI_CAPTIONS_ENABLED": "false"}), \
             patch.object(server, "process_reel") as render, \
             patch.object(server, "caption_from_screenshot") as ocr:
            page = await self.client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("const aiCaptionsEnabled = false;", page.text)
            response = await self.client.post("/api/generate",
                data={"url": "https://www.instagram.com/reel/abc/"})
            self.assertEqual(response.status_code, 422)
            self.assertIn("AI captions are disabled", response.json()["detail"])
            response = await self.client.post("/api/extract-caption",
                files={"screenshot": ("image.png", screenshot_bytes(), "image/png")})
            self.assertEqual(response.status_code, 503)
            render.assert_not_called()
            ocr.assert_not_called()

    async def test_explicit_ai_opt_out_allows_manual_url_caption(self):
        def render(**kwargs):
            self.assertEqual(kwargs["custom_caption"], "Manual headline")
            output = Path(kwargs["output_dir"]) / "output.mp4"
            output.write_bytes(b"manual render")
            return str(output)
        with patch.dict(os.environ, {"AI_CAPTIONS_ENABLED": "false"}), \
             patch.object(server, "process_reel", side_effect=render):
            response = await self.client.post("/api/generate",
                data={"url": "https://www.instagram.com/reel/abc/", "caption": "Manual headline"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"manual render")

    async def test_ocr_uses_bounded_processing(self):
        with patch.object(server.pytesseract, "image_to_string", return_value="Read text") as ocr, \
             patch.object(server, "generate_caption", return_value="{A useful} headline"):
            response = await self.client.post("/api/extract-caption",
                files={"screenshot": ("image.png", screenshot_bytes(), "image/png")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["caption"], "{A useful} headline")
        self.assertEqual(ocr.call_args.kwargs["timeout"], server.OCR_TIMEOUT)

    async def test_invalid_image_is_validation_error(self):
        response = await self.client.post("/api/extract-caption",
            files={"screenshot": ("bad.png", b"not an image", "image/png")})
        self.assertEqual(response.status_code, 422)


class RequestLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_chunked_oversize_upload(self):
        app = FastAPI()
        app.add_middleware(RequestGuardMiddleware, max_video_bytes=32, max_screenshot_bytes=32)
        reached = []
        @app.post("/api/generate")
        async def receive_upload(video: UploadFile = File(...)):
            reached.append(True)
            return {"ok": True}
        async def chunks():
            yield b'--b\r\nContent-Disposition: form-data; name="video"; filename="x.mp4"\r\n\r\n'
            yield b"x" * (1024 * 1024 + 64)
            yield b"\r\n--b--\r\n"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/generate", headers={"Content-Type": "multipart/form-data; boundary=b"}, content=chunks())
            self.assertEqual(response.status_code, 413)
            self.assertFalse(reached)
            # An error must release the concurrency slot.
            good = await client.post("/api/generate", files={"video": ("x.mp4", b"ok")})
            self.assertEqual(good.status_code, 200)

    def test_save_upload_uses_bounded_reads(self):
        class Upload(io.BytesIO):
            def read(self, size=-1):
                if size < 0:
                    raise AssertionError("Unbounded read")
                return super().read(size)
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "upload.mp4"
            server.save_upload(Upload(b"hello"), destination, 10)
            self.assertEqual(destination.read_bytes(), b"hello")


if __name__ == "__main__":
    unittest.main()
