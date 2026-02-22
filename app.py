from flask import Flask, render_template, request, jsonify
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

TIMEOUT = 10


def search_datagov(query, limit=10):
    """Search data.gov using the CKAN API."""
    datasets = []
    try:
        resp = requests.get(
            "https://catalog.data.gov/api/3/action/package_search",
            params={"q": query, "rows": limit},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("result", {}).get("results", []):
            resources = item.get("resources", [])
            formats = list(
                {r.get("format", "").upper() for r in resources if r.get("format")}
            )
            download_url = next((r.get("url") for r in resources if r.get("url")), None)
            org = item.get("organization") or {}
            datasets.append(
                {
                    "title": item.get("title", ""),
                    "description": (item.get("notes") or "")[:300],
                    "source": "data.gov",
                    "source_url": f"https://catalog.data.gov/dataset/{item.get('name', '')}",
                    "download_url": download_url,
                    "formats": formats[:4],
                    "organization": org.get("title", ""),
                    "tags": [t["name"] for t in item.get("tags", [])[:5]],
                }
            )
    except Exception as e:
        print(f"data.gov error: {e}")
    return datasets


def search_worldbank(query, limit=10):
    """Search World Bank Open Data indicators."""
    datasets = []
    try:
        resp = requests.get(
            "https://api.worldbank.org/v2/indicator",
            params={"format": "json", "per_page": limit, "q": query, "source": 2},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if len(data) >= 2 and data[1]:
            for item in data[1]:
                indicator_id = item.get("id", "")
                topics = item.get("topics") or []
                topic_name = topics[0].get("value", "") if topics else ""
                datasets.append(
                    {
                        "title": item.get("name", ""),
                        "description": (item.get("sourceNote") or "")[:300],
                        "source": "World Bank",
                        "source_url": f"https://data.worldbank.org/indicator/{indicator_id}",
                        "download_url": (
                            f"https://api.worldbank.org/v2/country/all/indicator/"
                            f"{indicator_id}?format=json&per_page=1000"
                        ),
                        "formats": ["JSON", "XML", "CSV"],
                        "organization": (item.get("sourceOrganization") or "")[:100],
                        "tags": [topic_name] if topic_name else [],
                    }
                )
    except Exception as e:
        print(f"World Bank error: {e}")
    return datasets


def search_socrata(query, limit=10):
    """Search Socrata open data portals (hundreds of city/state/federal portals)."""
    datasets = []
    try:
        resp = requests.get(
            "https://api.us.socrata.com/api/catalog/v1",
            params={"q": query, "limit": limit, "only": "datasets"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("results", []):
            resource = item.get("resource", {})
            metadata = item.get("metadata", {})
            link = item.get("link", "")
            domain = metadata.get("domain", "")
            tags = (resource.get("tags") or [])[:5]
            source_url = (
                f"https://{domain}{link}"
                if domain and link.startswith("/")
                else link
            )
            download_url = (
                f"https://{domain}/resource/{resource.get('id', '')}.csv"
                if domain
                else None
            )
            datasets.append(
                {
                    "title": resource.get("name", ""),
                    "description": (resource.get("description") or "")[:300],
                    "source": domain or "Socrata",
                    "source_url": source_url,
                    "download_url": download_url,
                    "formats": ["CSV", "JSON", "GeoJSON"],
                    "organization": "",
                    "tags": tags,
                }
            )
    except Exception as e:
        print(f"Socrata error: {e}")
    return datasets


def search_huggingface(query, limit=10):
    """Search Hugging Face Datasets Hub."""
    datasets = []
    try:
        resp = requests.get(
            "https://huggingface.co/api/datasets",
            params={"search": query, "limit": limit, "full": "true"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json()
        for item in items[:limit]:
            dataset_id = item.get("id", "")
            # Filter out metadata tags, keep topical ones
            raw_tags = item.get("tags") or []
            SKIP_PREFIXES = (
                "task_categories:", "license:", "size_categories:",
                "language:", "task_ids:", "multilinguality:", "source_datasets:",
                "pretty_name:", "annotations_creators:", "language_creators:",
            )
            tags = [t for t in raw_tags if not any(t.startswith(p) for p in SKIP_PREFIXES)][:5]
            description = (
                (item.get("cardData") or {}).get("pretty_name")
                or item.get("description")
                or ""
            )[:300]
            datasets.append(
                {
                    "title": dataset_id,
                    "description": description,
                    "source": "Hugging Face",
                    "source_url": f"https://huggingface.co/datasets/{dataset_id}",
                    "download_url": None,
                    "formats": ["Parquet", "CSV", "JSON"],
                    "organization": dataset_id.split("/")[0] if "/" in dataset_id else "",
                    "tags": tags,
                }
            )
    except Exception as e:
        print(f"Hugging Face error: {e}")
    return datasets


SOURCE_MAP = {
    "datagov": search_datagov,
    "worldbank": search_worldbank,
    "socrata": search_socrata,
    "huggingface": search_huggingface,
}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search")
def api_search():
    query = request.args.get("q", "").strip()
    sources = request.args.getlist("sources") or ["datagov", "worldbank", "socrata"]

    if not query:
        return jsonify({"results": [], "error": "No query provided"})

    all_results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(SOURCE_MAP[src], query): src
            for src in sources
            if src in SOURCE_MAP
        }
        for future in as_completed(futures):
            try:
                all_results.extend(future.result())
            except Exception as e:
                print(f"Search error: {e}")

    return jsonify({"results": all_results, "count": len(all_results)})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
