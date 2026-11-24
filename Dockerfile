# ==============================================================================
# Multi-Stage Dockerfile dla Project Coach (FastAPI + Uvicorn)
# Architektura dwuprofilowa: runner-cpu oraz runner-gpu (CUDA Faster-Whisper)
# ==============================================================================

# ------------------------------------------------------------------------------
# Etap 1: Baza systemowa (wspólna dla obu profili)
# ------------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS base

# Standardowe parametry środowiskowe Pythona
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Instalacja zależności systemowych:
# - ffmpeg: bezstratne dekodowanie notatek głosowych OGG/Opus przed transkrypcją
# - curl: deterministyczny healthcheck kontenera
# - libsqlite3-0: natywna obsługa silnika relacyjnego SQLite
# - ca-certificates: bezpieczne połączenia HTTPS do Telegram API i Gemini API
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    libsqlite3-0 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalacja bazowych zależności Pythona
COPY requirements-base.txt /app/requirements-base.txt
RUN pip install --upgrade pip && \
    pip install -r /app/requirements-base.txt


# ------------------------------------------------------------------------------
# Etap 2: Profil CPU (lekki kontener do webhooków i chmurowych LLM Gemini)
# ------------------------------------------------------------------------------
FROM base AS runner-cpu

ENV KALISTENIKA_DIR=/kalistenika \
    WHISPER_DEVICE=cpu \
    FASTAPI_HOST=0.0.0.0 \
    FASTAPI_PORT=8000

# Skopiowanie kodu źródłowego serwera
COPY server/ /app/server/
WORKDIR /app/server

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

CMD ["uvicorn", "server_fastapi:app", "--host", "0.0.0.0", "--port", "8000"]


# ------------------------------------------------------------------------------
# Etap 3: Profil GPU (NVIDIA Container Toolkit + CUDA Faster-Whisper large-v3)
# ------------------------------------------------------------------------------
FROM base AS runner-gpu

# Instalacja zależności akceleracji sprzętowej CUDA i silnika CTranslate2
COPY requirements-gpu.txt /app/requirements-gpu.txt
RUN pip install -r /app/requirements-gpu.txt

# Dynamiczne dowiązanie współdzielonych bibliotek NVIDIA cu12 do ścieżki linkera
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.13/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.13/site-packages/nvidia/cudnn/lib:$LD_LIBRARY_PATH \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    KALISTENIKA_DIR=/kalistenika \
    WHISPER_DEVICE=cuda \
    FASTAPI_HOST=0.0.0.0 \
    FASTAPI_PORT=8000

# Skopiowanie kodu źródłowego serwera
COPY server/ /app/server/
WORKDIR /app/server

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

CMD ["uvicorn", "server_fastapi:app", "--host", "0.0.0.0", "--port", "8000"]
