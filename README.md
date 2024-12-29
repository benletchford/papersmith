# Papersmith

An AI-powered PDF renamer that uses OpenAI's `gpt-4o-mini` vision model (and others) to intelligently rename PDF documents based on their content. Papersmith analyzes your PDFs and generates descriptive filenames that include the document date, type, and title.

## How It Works

1. Papersmith converts the first few pages of each PDF to images (using `pdf2image` - requries Poppler)
2. These images are sent to OpenAI's vision model for analysis
3. The AI extracts key information like dates and document types
4. A standardized filename is generated in the format: `YYYYMMDD-title-category.pdf`
5. The PDF is renamed according to this format
6. This process is idempotent, as Papersmith will not rename files that already match the expected format

## Installation

### System Dependencies

Papersmith uses `pdf2image` which requires Poppler to be installed:

#### macOS

```bash
brew install poppler
```

#### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install poppler-utils
```

#### Windows

1. Download the latest Poppler release from [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases/)
2. Extract it to a location on your system (e.g., `C:\Program Files\poppler`)
3. Add the `bin` directory to your system's PATH environment variable. You may need to restart your computer after this step.

### Application Setup

1. Ensure you have Rust installed ([rustup.rs](https://rustup.rs))
2. Clone this repository
3. Create a `.env` file with your OpenAI API key:

```
OPENAI_API_KEY=your_api_key_here
```

## Usage

```bash
# Basic usage (processes all PDFs in test-data directory)
papersmith

# Process PDFs in a specific directory
papersmith --glob-pattern "./invoices/*.pdf"

# Preview changes without renaming files
papersmith --dry-run

# Specify GPT model and number of pages to analyze
papersmith --model gpt-4o-mini --n-pages 2
```

### Command Line Options

- `-g, --glob-pattern <PATTERN>`: Specify which PDFs to process (default: "./test-data/\*.pdf")
- `-m, --model <MODEL>`: Choose the GPT model to use (default: "gpt-4o-mini")
- `-n, --n-pages <NUMBER>`: Number of pages to analyze per document (default: 3)
- `-d, --dry-run`: Preview changes without renaming files
- `-h, --help`: Display help information
- `-V, --version`: Display version information

For example:

- `Scanned Document 1.pdf` → `20240916-bunnings-invoice.pdf`
- `Scanned Document 2.pdf` → `20241016-wagga-wagga-airport-invoice.pdf`
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
