# Papersmith

An AI-powered PDF renamer that uses OpenAI's models (e.g., `gpt-4o`, `gpt-4.1`) via the `/v1/responses` API to intelligently rename PDF documents based on their content. Papersmith analyzes your PDFs by sending them directly to the API and generates descriptive filenames that include the document date, category, and title.

## How It Works

1.  Papersmith reads each PDF file specified by the glob pattern.
2.  The raw PDF data is base64 encoded.
3.  This encoded data is sent directly to the OpenAI `/v1/responses` API along with a prompt asking for document details.
4.  The AI extracts key information like dates, document categories, and suggested titles.
5.  A standardized filename is generated in the format: `YYYYMMDD-title-category.pdf`.
6.  The PDF is renamed according to this format.
7.  This process is idempotent, as Papersmith will not rename files that already match the expected format (`^\d{8}.*\.pdf$`).

## Installation

Ensure you have Rust installed ([rustup.rs](https://rustup.rs)).

```bash
cargo install papersmith # or cargo binstall papersmith
```

## Configuration

After installing `papersmith`, you need to set the following environment variables for the application to function correctly:

- `PAPERSMITH_OPENAI_API_KEY`: Your OpenAI API key. This is required.
- `PAPERSMITH_GLOB_PATTERN` (optional): A default glob pattern for PDF files (e.g., `"./my_pdfs/**/*.pdf"`). If this is not set and the command-line argument `--glob-pattern` (or `-g`) is not provided at runtime, the application will return an error.

You can set these variables in your shell's configuration file (e.g., `.bashrc`, `.zshrc`) or export them in the terminal session where you run `papersmith`.

## Usage

```bash
# Basic usage (processes PDFs based on PAPERSMITH_GLOB_PATTERN or an error if not set)
papersmith

# Process PDFs in a specific directory (overrides PAPERSMITH_GLOB_PATTERN if set)
papersmith --glob-pattern "./invoices/*.pdf"

# Preview changes without renaming files
papersmith --dry-run

# Specify a compatible OpenAI model (e.g., gpt-4o, gpt-4.1)
papersmith --model gpt-4o
```

### Command Line Options

- `-g, --glob-pattern <PATTERN>`: Glob pattern to specify which PDFs to process. If not provided, the `PAPERSMITH_GLOB_PATTERN` environment variable is used. If neither is set, it's an error.
- `-m, --model <MODEL>`: Choose the OpenAI model to use (default: "gpt-4o-mini", but ensure the chosen model is compatible with the `/v1/responses` endpoint for direct PDF processing, like `gpt-4o` or `gpt-4.1`).
- `-d, --dry-run`: Preview changes without renaming files.
- `-h, --help`: Display help information.
- `-V, --version`: Display version information.

For example:

- `Scanned Document 1.pdf` → `20240916-bunnings-invoice.pdf`
- `Document.pdf` → `20231225-unknown-document.pdf`

## Building

Run these commands in the project root directory:

```bash
# Debug build
cargo build

# Release build
cargo build --release
```

## License

This project is open source and available under the MIT License.
