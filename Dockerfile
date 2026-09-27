FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home reel

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only runtime files enter the image. Cookies and configuration are runtime inputs.
COPY server.py app_security.py generate_reel.py instalinkopen.py font.ttf logo.png ./

USER reel
EXPOSE 7008

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import json, urllib.request; r = urllib.request.urlopen('http://127.0.0.1:7008/api/health', timeout=3); assert r.status == 200 and json.load(r).get('ok') is True"

CMD ["python", "server.py"]
