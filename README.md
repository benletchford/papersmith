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

### Application Setup

1.  Ensure you have Rust installed ([rustup.rs](https://rustup.rs)).
2.  Clone this repository.
3.  Create a `.env` file in the project root with your OpenAI API key:

    ```env
    PAPERSMITH_OPENAI_API_KEY=your_api_key_here
    ```

4.  You can also set a default glob pattern for PDF files in the `.env` file:
    ```env
    PAPERSMITH_GLOB_PATTERN="./my_pdfs/**/*.pdf"
    ```
    If `PAPERSMITH_GLOB_PATTERN` is not set or the command-line argument `--glob-pattern` is not provided, the application will an error.

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

- `-g, --glob-pattern <PATTERN>`: Glob pattern to specify which PDFs to process. If not provided, `PAPERSMITH_GLOB_PATTERN` from the `.env` file is used. If neither is set, it's an error.
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
