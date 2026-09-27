"""Media regressions; real FFmpeg tests skip when the tools are unavailable."""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests
from PIL import Image

import generate_reel as media


class CaptionTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"AI_CAPTIONS_ENABLED": "true", "OPENROUTER_MODEL": "openrouter/free"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_manual_caption_validation(self):
        self.assertEqual(media.validate_caption("  {A headline}\nwith context  "), "{A headline} with context")
        for caption in ["", "   ", "{}", "x" * 501]:
            with self.subTest(caption_length=len(caption)), self.assertRaises(ValueError):
                media.validate_caption(caption)

    def test_api_requires_configured_key(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}), patch.object(media.requests, "post") as post:
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
                media.generate_caption("News text")
            post.assert_not_called()

    def test_explicit_ai_opt_out_prevents_provider_request_with_key(self):
        for setting in ["false", "0", "no", "off", " FALSE ", "Off"]:
            with self.subTest(setting=setting), patch.dict(os.environ, {
                "OPENROUTER_API_KEY": "fake-key", "AI_CAPTIONS_ENABLED": setting
            }), patch.object(media.requests, "post") as post:
                self.assertFalse(media.ai_captions_enabled())
                with self.assertRaisesRegex(RuntimeError, "AI captions are disabled"):
                    media.generate_caption("News text")
                post.assert_not_called()

    def test_ai_defaults_to_key_availability(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "fake-key"}):
            os.environ.pop("AI_CAPTIONS_ENABLED", None)
            self.assertTrue(media.ai_captions_enabled())
            os.environ["OPENROUTER_API_KEY"] = " "
            self.assertFalse(media.ai_captions_enabled())

    def test_api_has_timeouts_and_validates_result(self):
        response = Mock()
        response.json.return_value = {"choices": [{"message": {"content": '**{A headline}**\nwith context'}}]}
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "fake-key"}), patch.object(media.requests, "post", return_value=response) as post:
            self.assertEqual(media.generate_caption("News text"), "{A headline} with context")
            self.assertEqual(post.call_args.kwargs["timeout"], (10, 60))
            response.json.return_value = {"choices": []}
            with self.assertRaisesRegex(RuntimeError, "invalid headline"):
                media.generate_caption("News text")

    def test_caption_routes_only_to_zero_price_providers(self):
        response = Mock()
        response.json.return_value = {"choices": [{"message": {"content": "{A headline} with context"}}]}
        for model in [None, "", "openrouter/free", "nvidia/nemotron-3-ultra-550b-a55b:free"]:
            with self.subTest(model=model), patch.dict(os.environ, {"OPENROUTER_API_KEY": "fake-key"}), patch.object(media.requests, "post", return_value=response) as post:
                if model is None:
                    os.environ.pop("OPENROUTER_MODEL", None)
                else:
                    os.environ["OPENROUTER_MODEL"] = model
                self.assertEqual(media.generate_caption("News text"), "{A headline} with context")
                payload = post.call_args.kwargs["json"]
                self.assertEqual(payload["model"], model or "openrouter/free")
                self.assertEqual(payload["provider"]["max_price"], {
                    "prompt": 0, "completion": 0, "request": 0, "image": 0,
                })
                self.assertNotIn("models", payload)
                self.assertGreater(payload["max_tokens"], 200)
                self.assertTrue(payload["reasoning"]["exclude"])
                if model == "nvidia/nemotron-3-ultra-550b-a55b:free":
                    self.assertFalse(payload["reasoning"]["enabled"])

    def test_paid_models_and_automatic_paid_router_fail_before_network(self):
        for model in ["openai/gpt-5", "openrouter/auto", "openrouter/auto:free", "openrouter/auto:free,openai/gpt-5", "nvidia/nemotron:free:online"]:
            with self.subTest(model=model), patch.dict(os.environ, {
                "OPENROUTER_API_KEY": "fake-key", "OPENROUTER_MODEL": model,
            }), patch.object(media.requests, "post") as post:
                with self.assertRaisesRegex(RuntimeError, "Only free AI models"):
                    media.generate_caption("News text")
                post.assert_not_called()

    def test_empty_reasoning_and_truncated_answers_never_become_captions(self):
        for content, finish in [("", "length"), ("{A partial headline}", "length"), (None, "stop")]:
            response = Mock()
            response.json.return_value = {"choices": [{
                "message": {"content": content, "reasoning": "private reasoning"},
                "finish_reason": finish,
            }]}
            with self.subTest(content=content, finish=finish), patch.dict(os.environ, {"OPENROUTER_API_KEY": "fake-key"}), patch.object(media.requests, "post", return_value=response) as post:
                with self.assertRaisesRegex(RuntimeError, "invalid headline"):
                    media.generate_caption("News text")
                self.assertEqual(post.call_count, 1)

    def test_provider_errors_are_actionable_and_never_trigger_paid_fallback(self):
        for status, expected in [(401, "key is invalid"), (402, "No paid model"), (429, "free AI limit"), (503, "unavailable")]:
            response = requests.Response()
            response.status_code = status
            response._content = b"private-provider-detail fake-key"
            response.url = "https://openrouter.ai/api/v1/chat/completions"
            with self.subTest(status=status), patch.dict(os.environ, {"OPENROUTER_API_KEY": "fake-key"}), patch.object(media.requests, "post", return_value=response) as post:
                with self.assertRaisesRegex(RuntimeError, expected) as raised:
                    media.generate_caption("News text")
                self.assertNotIn("private-provider-detail", str(raised.exception))
                self.assertNotIn("fake-key", str(raised.exception))
                self.assertEqual(post.call_count, 1)

    def test_api_failures_do_not_expose_provider_details(self):
        for failure in [requests.Timeout("private-detail"), requests.HTTPError("private-detail")]:
            with self.subTest(failure=type(failure).__name__), patch.dict(os.environ, {"OPENROUTER_API_KEY": "fake-key"}), patch.object(media.requests, "post", side_effect=failure):
                with self.assertRaises(RuntimeError) as raised:
                    media.generate_caption("News text")
                self.assertNotIn("private-detail", str(raised.exception))
                self.assertNotIn("fake-key", str(raised.exception))

    def test_long_captions_and_oversized_words_fit_without_losing_text(self):
        for caption in ["{Breaking News} A short headline", "word " * 100, "W" * 500]:
            caption = media.validate_caption(caption)
            with self.subTest(length=len(caption)):
                font, lines, padding, height, gap = media._caption_layout(caption)
                self.assertLessEqual(1320 + len(lines) * (height + gap) - gap, 1860)
                for line in lines:
                    width = sum(font.getlength(text) + (2 * padding + 6 if highlighted else 15) for text, highlighted in line)
                    self.assertLessEqual(width, 932)
                rendered = "".join(text.replace(" ", "") for line in lines for text, _ in line)
                expected = caption.replace("{", "").replace("}", "").replace(" ", "")
                self.assertEqual(rendered, expected)
                with tempfile.TemporaryDirectory() as output_dir:
                    media.create_css_overlay(caption, output_dir)
                    with Image.open(Path(output_dir, "overlay.png")) as overlay:
                        self.assertEqual(overlay.size, (1080, 1920))
                        self.assertEqual(overlay.getpixel((0, 0)), (0, 0, 0, 0))
                        self.assertEqual(overlay.getpixel((0, 1919)), (0, 0, 0, 255))
                        self.assertEqual(overlay.getpixel((78, 1320))[:3], (255, 245, 0))

    def test_uploaded_video_requires_real_caption(self):
        with tempfile.TemporaryDirectory() as output_dir, patch.object(media, "generate_caption") as generate:
            with self.assertRaisesRegex(ValueError, "caption"):
                media.process_reel(None, output_dir, custom_video_path="video.mp4")
            generate.assert_not_called()


class DownloadTests(unittest.TestCase):
    def test_url_validation_rejects_other_hosts_and_options(self):
        for url in [None, "--exec=bad", "http://instagram.com/reel/abc/", "https://example.com/reel/abc/", "https://instagram.com.evil.example/reel/abc", "https://user:pass@instagram.com/reel/abc", "https://instagram.com:444/reel/abc", "https://instagram.com/profile/"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                media.validate_instagram_url(url)
        self.assertEqual(media.validate_instagram_url("https://instagram.com/reel/abc/?igsh=tracking"), "https://www.instagram.com/reel/abc/")

    def test_cookie_directories_ignored_and_options_terminated(self):
        with tempfile.TemporaryDirectory() as output_dir:
            Path(output_dir, "input_video.mp4").write_bytes(b"download")
            with patch.dict(os.environ, {"COOKIES_PATH": output_dir}), patch.object(media, "_run") as run:
                media.download_video("https://instagram.com/reel/abc/", output_dir)
                command = run.call_args.args[0]
                self.assertNotIn("--cookies", command)
                self.assertIn("--no-playlist", command)
                self.assertIn(f"duration <=? {media.MAX_VIDEO_SECONDS:g}", command)
                self.assertEqual(command[-2], "--")
                self.assertGreater(run.call_args.kwargs["timeout"], 0)
            cookies = Path(output_dir, "cookies.txt")
            cookies.write_text("not-real-cookies")
            cookies.chmod(0o400)
            copied_paths = []

            def inspect_cookie_copy(command, **kwargs):
                copied = Path(command[command.index("--cookies") + 1])
                copied_paths.append(copied)
                self.assertNotEqual(copied, cookies)
                self.assertTrue(copied.is_relative_to(output_dir))
                self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o600)
                self.assertEqual(copied.read_text(), "not-real-cookies")
                copied.write_text("updated-cookie-jar")

            with patch.dict(os.environ, {"COOKIES_PATH": str(cookies)}), patch.object(media, "_run", side_effect=inspect_cookie_copy) as run:
                media.download_video("https://instagram.com/reel/abc/", output_dir)
                self.assertIn("--cookies", run.call_args.args[0])
            self.assertEqual(cookies.read_text(), "not-real-cookies")
            self.assertEqual(stat.S_IMODE(cookies.stat().st_mode), 0o400)
            self.assertFalse(copied_paths[0].exists())

    def test_skipped_download_explains_the_limit_that_rejected_it(self):
        cases = [
            ("[download] clip does not pass filter (duration <=? 180), skipping ..", "180 seconds"),
            ("[download] File is larger than max-filesize (200 bytes > 100 bytes). Aborting.", "MiB"),
            ("[download] finished without a media file", "no video file"),
        ]
        for stdout, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as output_dir:
                with patch.object(media, "_run", return_value=Mock(stdout=stdout, stderr="")):
                    with self.assertRaisesRegex(ValueError, expected):
                        media.download_video("https://instagram.com/reel/abc/", output_dir)

    def test_process_error_output_is_sanitized(self):
        command = [sys.executable, "-c", "import sys; print('secret', file=sys.stderr); sys.exit(1)"]
        with self.assertRaisesRegex(RuntimeError, "Download failed") as raised:
            media._run(command, timeout=5, failure="Download failed")
        self.assertNotIn("secret", str(raised.exception))

    @unittest.skipUnless(os.name == "posix", "Process groups require POSIX")
    def test_deadline_terminates_spawned_children(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory, "child.pid")
            script = (
                "import pathlib,subprocess,sys,time; "
                "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)"
            )
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                media._run([sys.executable, "-c", script, str(pid_file)], timeout=1, failure="Download failed")
            pid = int(pid_file.read_text())
            status = Path(f"/proc/{pid}/stat")
            if status.exists():
                # An orphan may briefly remain as a zombie until init reaps it.
                self.assertEqual(status.read_text().split()[2], "Z")


class VideoLimitTests(unittest.TestCase):
    def test_file_size_checked_before_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "video.mp4")
            source.write_bytes(b"1234")
            with patch.object(media, "MAX_VIDEO_BYTES", 3), patch.object(media, "_run") as probe:
                with self.assertRaisesRegex(ValueError, "MiB"):
                    media.validate_video(source)
                probe.assert_not_called()

    def test_duration_and_resolution_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "video.mp4")
            source.write_bytes(b"video")
            for duration, width, height, error in [(181, 320, 568, "seconds"), (1, 8000, 8000, "4K"), (0, 320, 568, "duration")]:
                metadata = {"format": {"duration": str(duration)}, "streams": [{"codec_type": "video", "width": width, "height": height}]}
                with self.subTest(duration=duration, width=width), patch.object(media, "_run", return_value=Mock(stdout=json.dumps(metadata))):
                    with self.assertRaisesRegex(ValueError, error):
                        media.validate_video(source)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools are unavailable")
class FFmpegSmokeTests(unittest.TestCase):
    def test_silent_and_pcm_audio_uploads_render_playable_mp4(self):
        for with_audio in [False, True]:
            with self.subTest(with_audio=with_audio), tempfile.TemporaryDirectory() as directory:
                source = Path(directory, "source.mov")
                command = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x568:r=4:d=0.5"]
                if with_audio:
                    command.extend(["-f", "lavfi", "-i", "sine=frequency=440:duration=0.5", "-c:a", "pcm_s16le"])
                command.extend(["-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(source)])
                subprocess.run(command, check=True, capture_output=True, timeout=20)
                output = media.process_reel(None, str(Path(directory, "output")), custom_video_path=str(source), custom_caption="{A real headline} with useful context")
                result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", output], capture_output=True, text=True, check=True, timeout=20)
                streams = json.loads(result.stdout)["streams"]
                video = next(s for s in streams if s["codec_type"] == "video")
                self.assertEqual((video["width"], video["height"]), (1080, 1920))
                self.assertEqual(video["codec_name"], "h264")
                self.assertEqual(video["pix_fmt"], "yuv420p")
                audio = [s for s in streams if s["codec_type"] == "audio"]
                self.assertEqual(len(audio), int(with_audio))
                if with_audio:
                    self.assertEqual(audio[0]["codec_name"], "aac")


if __name__ == "__main__":
    unittest.main()
