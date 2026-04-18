# TikScale Thumbnail Generator — production image for Render
# Base: Python 3.12 slim (Debian) — MediaPipe + OpenCV native wheels ship here.
FROM python:3.12-slim

# System deps required by:
#   - OpenCV (libgl1, libglib2.0-0)
#   - MediaPipe (mesa/xvfb shim not needed at runtime, but libstdc++ is)
#   - ffmpeg (used by video-editing features)
#   - yt-dlp (just needs Python, no system dep)
#   - requests/urllib3 (needs certificates)
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libgles2 \
        libegl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so they cache between code changes
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn

# Copy application source
COPY . .

# Download the MediaPipe face landmarker model at build time (not in git).
# The file is ~5 MB and Google hosts it on their CDN.
RUN mkdir -p models && \
    curl -fsSL -o models/face_landmarker.task \
      https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task

# Render mounts a persistent disk at /app/.tmp (configured in render.yaml).
# The app creates subdirs lazily so nothing more to do at build time.

# Render injects the PORT env var — bind gunicorn to it.
ENV PORT=10000
EXPOSE 10000

# Single worker, 4 threads. Thumbnail generation uses subprocesses + semaphores,
# not gunicorn workers, so one web worker is enough and avoids duplicate state.
# 600s timeout — generations can take 1-3 min.
CMD ["sh", "-c", "gunicorn --workers 1 --threads 4 --timeout 600 --bind 0.0.0.0:${PORT} app:app"]
