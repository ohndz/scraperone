import csv
import json
import os
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"

BASE = "https://www.tripadvisor.com/"
START = "https://www.tripadvisor.com/Tourism-g294266-Argentina-Vacations.html"


def save_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def save_json(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def parse_rating_and_reviews(text):
    """
    Intenta sacar rating y review_count de textos tipo:
    '4.8 of 5 bubbles ( 24,423 )'
    Devuelve (rating, review_count) como strings.
    """
    rating = ""
    reviews = ""

    m_rating = re.search(r"(\d\.\d)\s+of\s+5", text)
    if m_rating:
        rating = m_rating.group(1)

    m_reviews = re.search(r"\(\s*([\d,]+)\s*\)", text)
    if m_reviews:
        reviews = m_reviews.group(1).replace(",", "")

    return rating, reviews


def run_tripadvisor(out_format="csv", limit_pages = 0, headful=False, user_agent=DEFAULT_UA):
    os.makedirs("output", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=(not headful))
        context = browser.new_context(user_agent=user_agent)
        page = context.new_page()

        page.goto(START, timeout=30000)

        # Espera a que cargue el contenido principal (si tarda, aumentamos timeout)
        page.wait_for_timeout(1500)

        html = page.content()
        context.close()
        browser.close()

    soup = BeautifulSoup(html, "html.parser")

    # --- A) Things to do (top atracciones) ---
    attractions = []
    # En el HTML se ven items con nombre + rating + (reviews) + categoría. :contentReference[oaicite:3]{index=3}
    # Como los selectores exactos pueden variar, tomamos una estrategia robusta:
    # buscamos links que parezcan "AttractionReview" y luego levantamos texto cercano.
    for a in soup.select("a[href*='AttractionReview']"):
        name = a.get_text(" ", strip=True)
        href = a.get("href", "")
        url = urljoin(BASE, href)

        # Tomamos el texto del contenedor cercano como “fallback”
        container_text = a.parent.get_text(" ", strip=True) if a.parent else ""
        rating, review_count = parse_rating_and_reviews(container_text)

        # categoría: a veces aparece al final del texto del item; si no, queda vacío
        category = ""
        # ejemplo: "... ( 24,423 ) Theaters"
        m_cat = re.search(r"\)\s*([A-Za-z &]+)$", container_text)
        if m_cat:
            category = m_cat.group(1).strip()

        if name:
            attractions.append({
                "name": name,
                "rating": rating,
                "review_count": review_count,
                "category": category,
                "url": url,
            })

    # Deduplicar por URL
    seen = set()
    attractions_unique = []
    for r in attractions:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        attractions_unique.append(r)

    # --- B) Best cities to visit ---
    cities = []
    # En la página aparecen ciudades como links (Buenos Aires, etc.). :contentReference[oaicite:4]{index=4}
    for a in soup.select("a[href*='Tourism-']"):
        city = a.get_text(" ", strip=True)
        href = a.get("href", "")
        url = urljoin(BASE, href)

        # filtro simple: evitar links del menú y basura
        if city and len(city) <= 40 and city.lower() not in ["argentina", "south america"]:
            cities.append({"city_name": city, "url": url})

    # Deduplicar ciudades por nombre+url
    seen_c = set()
    cities_unique = []
    for c in cities:
        key = (c["city_name"], c["url"])
        if key in seen_c:
            continue
        seen_c.add(key)
        cities_unique.append(c)

    # Guardar
    if out_format == "json":
        save_json("output/tripadvisor_argentina_attractions.json", attractions_unique[:50])
        save_json("output/tripadvisor_argentina_cities.json", cities_unique[:50])
        print("✅ Guardado: output/tripadvisor_argentina_attractions.json")
        print("✅ Guardado: output/tripadvisor_argentina_cities.json")
    else:
        save_csv(
            "output/tripadvisor_argentina_attractions.csv",
            attractions_unique[:50],
            ["name", "rating", "review_count", "category", "url"],
        )
        save_csv(
            "output/tripadvisor_argentina_cities.csv",
            cities_unique[:50],
            ["city_name", "url"],
        )
        print("✅ Guardado: output/tripadvisor_argentina_attractions.csv")
        print("✅ Guardado: output/tripadvisor_argentina_cities.csv")