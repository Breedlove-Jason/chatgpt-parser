# ChatGPT Parser

A powerful tool to search, extract, and export content from ChatGPT data exports. Features both a command-line interface (CLI) and a graphical user interface (GUI).

## Features

- **Parse ChatGPT Exports**: Works with ZIP files, extracted folders, or direct `conversations.json` files
- **Flexible Search**: Search by keywords or regex patterns across conversation titles and messages
- **Multiple Export Formats**: Export results as JSON, Markdown, or plain text
- **Code Extraction**: Automatically extract and save fenced code blocks from conversations
- **Date Filtering**: Filter messages by date range
- **GUI & CLI**: Choose between a user-friendly GUI or powerful command-line interface
- **Progress Tracking**: Visual progress bars during scanning (with optional tqdm integration)

## Installation

### Requirements
- Python 3.7+
- PySide6 (for GUI)
- tqdm (optional, for progress bars)

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd chatgpt-parser
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Command-Line Interface

#### Basic Search
```bash
python main.py export.zip search "your search query"
```

#### Regex Search
```bash
python main.py export.zip search "safe.*date" --regex
```

#### Case-Sensitive Search
```bash
python main.py export.zip search "MyClass" --case-sensitive
```

#### Advanced Search with Filtering
```bash
python main.py export.zip search "function" \
  --title-contains "Python" \
  --only-with-code \
  --start-date 2024-01-01 \
  --end-date 2024-12-31
```

#### Export Results
```bash
python main.py export.zip search "topic" \
  --export results.md \
  --format md
```

Supported formats: `json`, `md` (markdown), `txt`

#### Extract Code Blocks
```bash
python main.py export.zip search "code" \
  --extract-code \
  --code-dir ./recovered_code
```

#### Show Full Message
```bash
python main.py export.zip search "query" --show 1
```

### GUI

Launch the graphical interface:
```bash
python gui.py
```

The GUI provides:
- Visual file browser for selecting ChatGPT exports
- Interactive search with filters
- Results list with preview
- Real-time progress tracking
- Code extraction to local directory

## CLI Options

```
positional arguments:
  input                 Path to ChatGPT export ZIP, extracted folder, or conversations.json

search arguments:
  query                 Search query (plain text by default; use --regex for regex)
  --regex              Treat query as regex
  --case-sensitive     Case-sensitive matching
  --no-titles          Do not search conversation titles
  --no-messages        Do not search message bodies
  --title-contains     Filter conversations where title contains this (plain text)
  --only-with-code     Only return hits that contain fenced code blocks
  --start-date         Filter messages after this date (YYYY-MM-DD or ISO format)
  --end-date           Filter messages before this date (YYYY-MM-DD or ISO format)
  --preview            How many hits to preview in terminal (default: 10)
  --show               Print the full text of hit N to stdout
  --export             Export hits to a file
  --format             Export format: md, json, txt (default: md)
  --extract-code       Extract fenced code blocks into files
  --code-dir           Directory for extracted code (default: recovered_code)
```

## Input Format

The tool accepts three input types:

1. **ZIP File**: Standard ChatGPT export zip containing `conversations.json`
   ```
   export.zip
   └── conversations.json
   ```

2. **Extracted Folder**: ChatGPT export folder
   ```
   export/
   └── conversations.json
   ```

3. **Direct File**: Path to `conversations.json`
   ```
   /path/to/conversations.json
   ```

## Output Examples

### JSON Export
```json
[
  {
    "conversation_id": "abc123",
    "conversation_title": "Example Chat",
    "conversation_create_time": "2024-01-15T10:30:00+00:00",
    "message_id": "msg456",
    "author_role": "user",
    "message_time": "2024-01-15T10:31:00+00:00",
    "snippet": "This is a snippet of the message...",
    "full_text": "Full message text here...",
    "code_blocks": [
      {
        "language": "python",
        "code": "print('hello')"
      }
    ]
  }
]
```

### Markdown Export
Results are formatted with headers, metadata, full message text, and code blocks displayed with syntax highlighting.

### Text Export
Simple text format with conversation details and snippets.

## Examples

### Find all Python code snippets from 2024
```bash
python main.py my_export.zip search "def " \
  --regex \
  --only-with-code \
  --start-date 2024-01-01 \
  --end-date 2024-12-31 \
  --extract-code
```

### Search for security-related topics
```bash
python main.py export/ search "encryption|password|security" \
  --regex \
  --case-sensitive \
  --export security_results.md
```

### Filter by conversation and search
```bash
python main.py export.zip search "API" \
  --title-contains "REST" \
  --export api_docs.json \
  --format json
```

## Project Structure

```
chatgpt-parser/
├── main.py           # Core search engine and CLI
├── gui.py            # GUI application (PySide6)
├── style.qss         # Qt stylesheet for GUI
├── requirements.txt  # Python dependencies
└── README.md         # This file
```

## Performance

- **Scanning**: Typically scans large exports (10k+ conversations) in seconds
- **Progress Tracking**: Integrated tqdm for visual progress (optional)
- **Memory**: Streams conversations for efficient processing
- **Regex**: Supports complex regex patterns for advanced searches

## Limitations

- Requires a valid ChatGPT export format
- Code block extraction supports common languages (Python, JavaScript, SQL, etc.)
- Date filtering uses ISO 8601 format or YYYY-MM-DD

## Troubleshooting

### "Could not find conversations.json"
- Ensure your export file/folder contains `conversations.json`
- Try extracting the ZIP file manually and pointing to the folder

### GUI won't start
- Ensure PySide6 is installed: `pip install PySide6`
- Check Python version is 3.7+

### Regex errors
- Verify your regex pattern is valid Python regex syntax
- Use raw strings: `r"pattern"` to avoid escape issues

## Contributing

Feel free to submit issues and enhancement requests!

## License

MIT License - see LICENSE file for details

## Disclaimer

This tool is intended for personal use with your own ChatGPT exports. Ensure you have the rights to the data you're processing.

