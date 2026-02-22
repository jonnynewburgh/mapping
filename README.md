# basicCodes

Hi folks,

The notebook herein contains:

  [1] basic code to map addresses in R; and,
  [2] csv template to use to map the addresses; and,
  [3] a website crawler tool that uses Claude AI to extract data from websites.

---

## Website Crawler (`crawler.py`)

A Python tool that crawls websites and uses [Claude AI](https://www.anthropic.com) to extract structured data from each page. Results are saved as JSON or CSV.

### Requirements

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/)

### Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
```

### Usage

```
python crawler.py <url> --data "<what to extract>" [options]
```

| Option | Default | Description |
|---|---|---|
| `--data` | (required) | Plain-English description of what to extract |
| `--output` | `crawl_results.json` | Output file path |
| `--format` | `json` | Output format: `json` or `csv` |
| `--max-pages` | `10` | Maximum pages to visit |
| `--depth` | `2` | Maximum link depth from seed URL |
| `--delay` | `1.0` | Seconds to wait between requests |
| `--any-domain` | off | Follow links to other domains |
| `--url-pattern` | none | Only crawl URLs matching this regex |

### Examples

```bash
# Extract contact information
python crawler.py https://example.com --data "name, email, phone number"

# Extract addresses for use with mapping.R
python crawler.py https://example.com \
    --data "business name and street address" \
    --format csv --output addresses.csv

# Scrape product listings with a CSV output
python crawler.py https://shop.example.com \
    --data "product name, price, description" \
    --format csv --output products.csv --max-pages 30

# Deep crawl with polite rate limiting
python crawler.py https://example.com \
    --data "article title and author" \
    --max-pages 50 --depth 3 --delay 2
```

### Workflow with mapping.R

Use the crawler to collect addresses from a website, then feed the CSV straight into `mapping.R`:

```bash
python crawler.py https://example.com \
    --data "place name and full street address" \
    --format csv --output addresses.csv
```

Then open `mapping.R` and point `file.choose()` at the generated `addresses.csv`.

---

Cheers,
Jonny
