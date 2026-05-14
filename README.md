# docker-pdf-autonamer

Docker-only PDF autonamer.

It watches a folder, OCRs PDFs with Surya, asks Docker Ollama for a filename, and renames PDFs to:

```text
YYYYMMDD-title.pdf
```

It does not create sidecar folders in the watched directory. If a PDF cannot be renamed confidently, it is left in place and the reason is logged to stdout.

## Run

Default watched folder:

```text
~/Library/Mobile Documents/com~apple~CloudDocs/docs
```

Start the stack:

```bash
docker compose up --build
```

Watch logs:

```bash
docker compose logs -f watcher
```

Useful watcher events:

```text
renamed
needs_review
process_failed
```

## Options

No config is required for the default setup.

To watch a different folder, create `.env`:

```bash
cp .env.example .env
```

Then set:

```env
WATCH_DIR_HOST=/absolute/path/to/pdfs
```

The default model is `qwen3:4b`, which fits typical Docker Desktop memory limits. To use another model:

```env
OLLAMA_MODEL=qwen3:1.7b
```

## One File

Process one PDF mounted inside Docker at `/watch`:

```bash
docker compose run --rm watcher --once /watch/example.pdf
```

Dry run:

```bash
docker compose run --rm -e DRY_RUN=true watcher --once /watch/example.pdf
```

## Notes

Everything runs in Docker: watcher, OCR, and Ollama. This is tidy but slower than host-native GPU/MPS OCR or inference.
