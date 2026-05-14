# local-pdf-ocr-renamer

Docker-only local PDF OCR renamer.

The stack watches a local folder, OCRs PDFs with Surya, asks a Docker Ollama model for evidence-backed metadata, and renames files to:

```text
YYYYMMDD-title.pdf
```

No host-native Surya service, host-native Ollama service, GPU access, or cloud API is required. The tradeoff is speed: first startup, OCR, and inference are all slower inside Docker Desktop.

## Quick Start

By default, the stack watches:

```text
~/Library/Mobile Documents/com~apple~CloudDocs/docs
```

Create `.env` only if you want to override that folder:

```bash
cp .env.example .env
```

Start everything:

```bash
docker compose up --build
```

On first run, Compose builds the watcher and Surya images, starts Docker Ollama, pulls the configured model into a Docker volume, and then starts watching the configured folder.

The watcher does not create sidecar folders or state files in the watched directory. It either renames a PDF or leaves it untouched and writes structured JSON logs to stdout. Look for `renamed`, `needs_review`, and `process_failed` events in `docker compose logs -f watcher`.

## Configuration

Most users do not need any settings:

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `WATCH_DIR_HOST` | no | `~/Library/Mobile Documents/com~apple~CloudDocs/docs` | Absolute host folder mounted into Docker as `/watch` |
| `OLLAMA_MODEL` | no | `qwen3:4b` | Docker Ollama model used for naming |

`qwen3:4b` is the default because it fits typical Docker Desktop memory limits. Larger models may work if Docker has enough RAM.

## One-PDF Test Mode

Process one PDF and exit:

```bash
docker compose run --rm watcher --once /watch/example.pdf
```

Run the same path without renaming:

```bash
docker compose run --rm -e DRY_RUN=true watcher --once /watch/example.pdf
```

## Useful Commands

Check service status:

```bash
docker compose ps
docker compose run --rm watcher --healthcheck
```

Inspect logs:

```bash
docker compose logs -f watcher surya ollama
```

Pull or refresh the configured model:

```bash
docker compose run --rm ollama-pull
```

Use a different model for one command:

```bash
OLLAMA_MODEL=qwen3:1.7b docker compose up --build
```

## Project Layout

```text
Dockerfile              Multi-stage watcher and Surya images
docker-compose.yml      Docker-only runtime stack
watcher/                Folder polling, OCR orchestration, naming, renaming
surya_service/          Small FastAPI wrapper around surya_ocr
```

## Troubleshooting

If Docker cannot mount the watch folder, make sure `WATCH_DIR_HOST` is an absolute path and is allowed by Docker Desktop file sharing.

If Ollama fails to load a model, use a smaller model or increase Docker Desktop memory. The previous `qwen3:14b` default was too large for the tested Docker Desktop limit.

If Surya fails, inspect:

```bash
docker compose logs -f surya
```

First OCR after a fresh build can be slow while Surya downloads and warms model weights.
