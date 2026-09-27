#!/usr/bin/env python3
"""Create private local configuration without overwriting existing credentials."""
import os
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent.parent
    target = root / ".env"
    content = (root / ".env.example").read_text()
    content = content.replace("REEL_UID=\n", f"REEL_UID={os.getuid()}\n", 1)
    content = content.replace("REEL_GID=\n", f"REEL_GID={os.getgid()}\n", 1)
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(".env already exists; left unchanged. Edit it to update configuration.")
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)
    print("Created private .env configuration. Set OPENROUTER_API_KEY locally to enable AI captions.")


if __name__ == "__main__":
    main()
