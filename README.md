# papersmith

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
retry_scheduled
skip_failed_retry_limit
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

Failed OCR attempts are retried rather than suppressed permanently. The defaults are:

```env
MAX_PROCESS_ATTEMPTS=3
FAILED_RETRY_DELAY_SECONDS=300
OCR_MAX_PAGES=3
SURYA_TIMEOUT_SECONDS=1200
OLLAMA_TIMEOUT_SECONDS=1200
SURYA_RENDERED_FALLBACK_MAX_DIMENSION=1600
SURYA_DIRECT_OCR_MAX_PAGE_DIMENSION_POINTS=1600
SURYA_MEM_LIMIT=8g
SURYA_MEMSWAP_LIMIT=20g
```

`OCR_MAX_PAGES` limits OCR to the first N pages before naming. Set it to `0`
to OCR every page.

`SURYA_TIMEOUT_SECONDS` and `OLLAMA_TIMEOUT_SECONDS` control how long the
watcher waits for OCR and filename inference. The defaults are 20 minutes.

`SURYA_MEMSWAP_LIMIT` is Docker's total memory plus swap allowance for the
Surya container, not swap alone. Docker Desktop must also have enough memory
and swap enabled in its resource settings for this to help.

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
