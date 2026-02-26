import csv
import json
import hashlib
import os
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = "https://quotes.toscrape.com/"
START = urljoin(BASE, "js/")


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


def run_quotes_js(out_format="csv", limit_pages=0, headful=False, user_agent="scraperone/1.0"):
    os.makedirs("output", exist_ok=True)

    seen = set()
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=(not headful))

        # NUEVO: setear User-Agent en el contexto/navegador
        context = browser.new_context(user_agent=user_agent)
        page = context.new_page()

        url = START
        page_num = 1

        while url:
            if limit_pages > 0 and page_num > limit_pages:
                print(f"[quotes_js] Límite alcanzado: {limit_pages} páginas. Cortando.")
                break

            print(f"[quotes_js] Abriendo: {url}")
            page.goto(url, timeout=20000)
            page.wait_for_selector(".quote", timeout=20000)

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            for q in soup.select(".quote"):
                text_el = q.select_one(".text")
                author_el = q.select_one(".author")

                text = text_el.get_text(strip=True) if text_el else ""
                author = author_el.get_text(strip=True) if author_el else ""

                tags = [a.get_text(strip=True) for a in q.select(".tags a.tag")]

                author_a = q.select_one("a[href*='/author/']")
                author_rel = author_a["href"] if author_a else ""
                author_url = urljoin(BASE, author_rel) if author_rel else ""

                quote_id = make_id(text, author)
                if quote_id in seen:
                    continue
                seen.add(quote_id)

                rows.append(
                    {
                        "quote_id": quote_id,
                        "text": text,
                        "author_name": author,
                        "author_url": author_url,
                        "tags": "|".join(tags),
                        "page": page_num,
                    }
                )

            next_a = soup.select_one("li.next a")
            url = urljoin(BASE, next_a["href"]) if next_a else None
            page_num += 1

        context.close()
        browser.close()

    if out_format == "json":
        save_json("output/quotes_js.json", rows)
        print("✅ Guardado: output/quotes_js.json")
    else:
        fields = ["quote_id", "text", "author_name", "author_url", "tags", "page"]
        save_csv("output/quotes_js.csv", rows, fields)
        print("✅ Guardado: output/quotes_js.csv")