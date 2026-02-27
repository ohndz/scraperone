import argparse

from scrapers.quotes import run_quotes
from scrapers.quotes_js import run_quotes_js
from scrapers.tripadvisor  import run_tripadvisor
from scrapers.ml_televisores import run_ml_televisores
from scrapers.superpages_labs import run_superpages_labs
from scrapers.superpages_psicologos import run_superpages_psicologos

SCRAPERS = {
    "quotes": run_quotes,
    "quotes_js": run_quotes_js,
    "tripadvisor": run_tripadvisor,
    "superpages_labs": run_superpages_labs,
    "superpages_psicologos": run_superpages_psicologos,
    "ml_televisores":run_ml_televisores
    # "books": run_books,
}

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"


def main():
    p = argparse.ArgumentParser(description="scraperone - proyecto simple de web scraping")
    p.add_argument("--scraper", required=True, choices=SCRAPERS.keys())
    p.add_argument("--format", default="csv", choices=["csv", "json"])
    p.add_argument("--limit", type=int, default=0, help="Máximo de páginas (0 = todas)")
    p.add_argument("--headful", action="store_true", help="Ver navegador (solo Playwright)")

    # NUEVO: User-Agent configurable
    p.add_argument("--user-agent", default=DEFAULT_UA, help="User-Agent para requests y Playwright")

    args = p.parse_args()

    # Llamamos a la función elegida, pasándole parámetros comunes
    SCRAPERS[args.scraper](
        out_format=args.format,
        limit_pages=args.limit,
        headful=args.headful,
        user_agent=args.user_agent,
    )


if __name__ == "__main__":
    main()