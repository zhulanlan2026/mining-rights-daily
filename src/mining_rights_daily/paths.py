from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"
NEWS_PATH = DATA_DIR / "news" / "articles.json"
PRICE_PATH = DATA_DIR / "prices" / "series.json"
REPORTS_DIR = DATA_DIR / "reports"
SAMPLE_REPORT_PATH = REPORTS_DIR / "pilgangoora_ni43101_sample.pdf"

SAMPLE_REPORT_ID = "pilgangoora-ni43101-sample"
SAMPLE_REPORT_URL = f"catalog:{SAMPLE_REPORT_ID}"
