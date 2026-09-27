"""Authenticated HTTP workflows using real local media tools and no network APIs."""

import asyncio
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import httpx
from PIL import Image, ImageDraw, ImageFont

import server


class WorkflowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.environment = patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "",
        })
        self.environment.start()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://integration.test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self.environment.stop()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools are unavailable")
    async def test_silent_upload_with_manual_caption_returns_playable_mp4(self):
        with tempfile.TemporaryDirectory(prefix="reel-http-test-") as directory:
            source = Path(directory, "silent.mp4")
            await asyncio.to_thread(
                subprocess.run,
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                 "color=c=blue:s=320x568:r=4:d=0.5", "-c:v", "libx264",
                 "-threads", "1", "-pix_fmt", "yuv420p", str(source)],
                check=True, capture_output=True, timeout=20,
            )
            response = await self.client.post(
                "/api/generate",
                data={"caption": "{Students Win Science Award} After Their Latest Discovery"},
                files={"video": ("silent.mp4", source.read_bytes(), "video/mp4")},
            )
            self.assertEqual(response.status_code, 200, response.text if response.status_code != 200 else "")
            self.assertEqual(response.headers["content-type"], "video/mp4")
            self.assertIn("attachment", response.headers["content-disposition"])
            self.assertEqual(response.headers["cache-control"], "no-store")
            output = Path(directory, "rendered.mp4")
            output.write_bytes(response.content)
            probe = await asyncio.to_thread(
                subprocess.run,
                ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)],
                check=True, capture_output=True, text=True, timeout=20,
            )
            streams = json.loads(probe.stdout)["streams"]
            video = next(stream for stream in streams if stream["codec_type"] == "video")
            self.assertEqual((video["width"], video["height"]), (1080, 1920))
            self.assertEqual(video["codec_name"], "h264")
            self.assertEqual(video["pix_fmt"], "yuv420p")
            self.assertFalse(any(stream["codec_type"] == "audio" for stream in streams))

    @unittest.skipUnless(shutil.which("tesseract"), "Tesseract is unavailable")
    async def test_screenshot_runs_real_ocr_and_sends_extracted_text_to_caption_service(self):
        font_path = Path(server.__file__).parent / "font.ttf"
        font = ImageFont.truetype(str(font_path), 48)
        screenshot = Image.new("RGB", (1800, 350), "white")
        draw = ImageDraw.Draw(screenshot)
        draw.text((70, 70), "LOCAL STUDENTS WIN SCIENCE AWARD", fill="black", font=font)
        draw.text((70, 170), "Research team celebrates a new discovery", fill="black", font=font)
        encoded = io.BytesIO()
        screenshot.save(encoded, "PNG")
        screenshot.close()
        expected_caption = "{Local Students Win} Science Award"
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "integration-dummy-key", "AI_CAPTIONS_ENABLED": "true"}), \
             patch.object(server, "generate_caption", return_value=expected_caption) as generate:
            response = await self.client.post(
                "/api/extract-caption",
                files={"screenshot": ("headline.png", encoded.getvalue(), "image/png")},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"caption": expected_caption})
        generate.assert_called_once()
        extracted_text = " ".join(generate.call_args.args[0].upper().split())
        self.assertIn("LOCAL STUDENTS WIN SCIENCE AWARD", extracted_text)
        self.assertIn("RESEARCH TEAM CELEBRATES A NEW DISCOVERY", extracted_text)


if __name__ == "__main__":
    unittest.main()
