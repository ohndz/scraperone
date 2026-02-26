import csv
import json
import hashlib
import os
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE = "https://www.mercadolibre.com.ar/"
START = "https://listado.mercadolibre.com.ar/televisores#D[A:televisores]"



def save_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def save_json(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def run_ml_televisores(out_format="csv", limit_pages=0, headful=False, user_agent="scraperone/1.0"):
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
                print(f"[ml] Límite alcanzado: {limit_pages} páginas. Cortando.")
                break

            print(f"[ml] Abriendo: {url}")
            page.goto(url, timeout=60000)
            page.wait_for_selector(".poly-component__title", timeout=60000)

            html = page.content()
            soup = BeautifulSoup(html, "html.parser")

            for card in soup.select("li.ui-search-layout__item"):
                producto_el = card.select_one(".poly-component__title")
                vendedor_el = card.select_one(".poly-component__seller")
                precio_el = card.select_one(".andes-money-amount__fraction")

                producto = producto_el.get_text(strip=True) if producto_el else ""
                vendedor = vendedor_el.get_text(strip=True) if vendedor_el else ""
                precio = precio_el.get_text(strip=True) if precio_el else ""

                # Link del producto (string URL)
                link_el = card.select_one("a.poly-component__title")
                link = urljoin(page.url, link_el["href"]) if link_el and link_el.get("href") else ""

                # Tienda oficial
                is_official = card.select_one('[aria-label="Tienda oficial"]') is not None
                official_store = "Tienda oficial" if is_official else "No es tienda oficial"

                rows.append(
                    {
                        "Producto": producto,
                        "Vendedor": vendedor,
                        "Precio": precio,
                        "Link de producto": link,
                        "Tienda oficial": official_store,
                        "page": page_num,
                    }
                )

            # --- Paginación robusta usando Playwright (mejor que soup) ---
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1200)  # darle tiempo a que aparezca la paginación

            next_btn = page.locator("li.andes-pagination__button--next a.andes-pagination__link")

            if next_btn.count() == 0:
                print("[ml] No encontré botón Siguiente. Fin.")
                url = None
            else:
                # si está deshabilitado, terminamos
                next_li = page.locator("li.andes-pagination__button--next")
                li_class = next_li.get_attribute("class") or ""
                if "andes-pagination__button--disabled" in li_class:
                    print("[ml] Botón Siguiente deshabilitado. Fin.")
                    url = None
                else:
                    with page.expect_navigation():
                        next_btn.click()
                    page_num += 1
                    url = page.url
                    print(f"[ml] Próxima página (navegada): {url}")

        context.close()
        browser.close()

    if out_format == "json":
        save_json("output/ml_televisores.json", rows)
        print("✅ Guardado: output/ml_televisores_js.json")
    else:
        fields = ["Producto", "Vendedor", "Precio", "Link de producto", "Tienda oficial", "page"]
        save_csv("output/ml_televisores.csv", rows, fields)
        print("✅ Guardado: output/ml_televisores.csv")