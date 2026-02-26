import csv
import json
import hashlib
import os
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://quotes.toscrape.com/"


def make_id(text, author):
    h = hashlib.sha1(f"{text}|{author}".encode("utf-8")).hexdigest()
    return h[:12]


def save_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def save_json(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def fetch_with_retries(url, user_agent, attempts=3, timeout=20):
    """
    Descarga HTML con reintentos simples.
    Usa User-Agent configurable.
    """
    headers = {"User-Agent": user_agent}
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            print(f"  -> GET intento {attempt}/{attempts}")
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            last_error = e
            sleep_seconds = 2 ** (attempt - 1)
            print(f"  !! Falló: {e}. Reintentando en {sleep_seconds}s...")
            time.sleep(sleep_seconds)

    raise RuntimeError(f"No se pudo descargar {url}") from last_error


def run_quotes(out_format="csv", limit_pages=0, headful=False, user_agent="scraperone/1.0"):
    """
    headful NO se usa acá, pero lo aceptamos para que main sea simple.
    """
    os.makedirs("output", exist_ok=True)

    url = BASE
    page = 1
    seen = set()
    rows = []

    while url:
        if limit_pages > 0 and page > limit_pages:
            print(f"[quotes] Límite alcanzado: {limit_pages} páginas. Cortando.")
            break

        print(f"[quotes] Descargando: {url}")

        html = fetch_with_retries(url, user_agent=user_agent, attempts=3, timeout=20)
        soup = BeautifulSoup(html, "html.parser")

        for q in soup.select(".quote"):
            text = q.select_one(".text").get_text(strip=True)
            author = q.select_one(".author").get_text(strip=True)
            tags = [a.get_text(strip=True) for a in q.select(".tags a.tag")]
            author_rel = q.select_one("a[href*='/author/']")["href"]

            quote_id = make_id(text, author)
            if quote_id in seen:
                continue
            seen.add(quote_id)

            rows.append(
                {
                    "quote_id": quote_id,
                    "text": text,
                    "author_name": author,
                    "author_url": urljoin(BASE, author_rel),
                    "tags": "|".join(tags),
                    "page": page,
                }
            )

        next_a = soup.select_one("li.next a")
        url = urljoin(BASE, next_a["href"]) if next_a else None
        page += 1

        time.sleep(1)

    if out_format == "json":
        save_json("output/quotes.json", rows)
        print("✅ Guardado: output/quotes.json")
    else:
        fields = ["quote_id", "text", "author_name", "author_url", "tags", "page"]
        save_csv("output/quotes.csv", rows, fields)
        print("✅ Guardado: output/quotes.csv")