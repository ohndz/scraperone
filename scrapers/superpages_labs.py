import csv
import json
import os
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
DEBUG = False
START = "https://superpagespr.com/es/business/search/puerto-rico/c/laboratorios-por-especialidad-%3E-clinicos"
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def save_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def save_json(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def normalize_email(email: str) -> str:
    return email.strip().strip(".,;:()[]{}<>\"'").lower()


def pick_best_email(emails: list[str]) -> str:
    if not emails:
        return ""
    seen = set()
    uniq = []
    for e in emails:
        e2 = normalize_email(e)
        if e2 and e2 not in seen:
            seen.add(e2)
            uniq.append(e2)

    priority = ["info@", "contact", "ventas@", "admin@", "administracion@", "hello@"]
    for p in priority:
        for e in uniq:
            if p in e:
                return e
    return uniq[0] if uniq else ""


def extract_email_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    mailtos = []
    for a in soup.select('a[href^="mailto:"]'):
        href = a.get("href", "")
        if href.lower().startswith("mailto:"):
            mailtos.append(href.split("mailto:", 1)[1].split("?", 1)[0])

    text = soup.get_text(" ", strip=True)
    regex_emails = EMAIL_RE.findall(text)

    return pick_best_email(mailtos + regex_emails)


def same_domain(url1: str, url2: str) -> bool:
    try:
        return urlparse(url1).netloc.lower() == urlparse(url2).netloc.lower()
    except Exception:
        return False


def find_contact_pages(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    keywords = ["contact", "contacto", "about", "acerca", "nosotros", "contáct", "contact-us"]
    found = []

    for a in soup.select("a[href]"):
        txt = (a.get_text(" ", strip=True) or "").lower()
        href = (a.get("href", "") or "").strip()
        if not href:
            continue
        if any(k in txt for k in keywords) or any(k in href.lower() for k in keywords):
            full = urljoin(base_url, href)
            found.append(full)

    out = []
    seen = set()
    for u in found:
        if not same_domain(u, base_url):
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= 3:
            break
    return out


def fetch_email_from_website(context, website_url: str) -> str:
    if not website_url:
        return ""

    base = website_url.rstrip("/")
    candidates = [
        base,
        base + "/",
        base + "/index",
        base + "/index.html",
        base + "/contacto",
        base + "/contact",
        base + "/contact-us",
        base + "/nosotros",
        base + "/about",
    ]

    seen = set()
    ordered = []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            ordered.append(u)

    page = context.new_page()
    try:
        for target in ordered:
            try:
                page.goto(target, timeout=45000, wait_until="domcontentloaded")
            except Exception:
                continue

            page.wait_for_timeout(1200)

            # scroll para forzar footer
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(900)
            except Exception:
                pass

            # si hay mailto, mejor
            try:
                page.wait_for_selector('a[href^="mailto:"]', timeout=3500)
            except Exception:
                pass

            html = page.content()
            email = extract_email_from_html(html)
            if email:
                return email

            for cu in find_contact_pages(html, target):
                try:
                    page.goto(cu, timeout=45000, wait_until="domcontentloaded")
                    page.wait_for_timeout(900)
                    try:
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(700)
                    except Exception:
                        pass

                    email2 = extract_email_from_html(page.content())
                    if email2:
                        return email2
                except Exception:
                    continue

        return ""
    finally:
        try:
            page.close()
        except Exception:
            pass


def safe_text(locator, timeout=1500) -> str:
    try:
        return " ".join(locator.inner_text(timeout=timeout).split())
    except Exception:
        return ""


def run_superpages_labs(out_format="csv", limit_pages=0, headful=False, user_agent="scraperone/1.0"):
    os.makedirs("output", exist_ok=True)

    rows = []
    seen_profile_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=(not headful))
        context = browser.new_context(user_agent=user_agent)
        page = context.new_page()

        url = START
        page_num = 1

        while True:
            if limit_pages > 0 and page_num > limit_pages:
                print(f"[superpages] Límite alcanzado: {limit_pages} páginas. Cortando.")
                break

            print(f"[superpages] Página {page_num}: {url}")
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)

            cards = page.locator("article.yp-result-listing-card")
            count = cards.count()
            print(f"[superpages] Cards detectadas: {count}")

            for i in range(count):
                card = cards.nth(i)

                # -------- profile_id (con fallback desde botón teléfono) --------
                profile_id = (card.get_attribute("data-profile-id") or "").strip()
                if not profile_id:
                    # fallback: sacar prefijo del id del botón
                    btn_id = (card.locator('button[data-component="telephone"]').first.get_attribute("id") or "")
                    profile_id = btn_id.split(".")[0] if btn_id else ""

                # DEBUG: solo para las primeras 5 cards
                #if i < 5:
                #    print(f"DEBUG card {i} profile_id:", profile_id)

                if profile_id and profile_id in seen_profile_ids:
                    continue
                if profile_id:
                    seen_profile_ids.add(profile_id)

                name = " ".join(((card.get_attribute("label") or "").strip()).split())
                if not name:
                    continue

                # Dirección exacta
                address = ""
                address_el = card.locator('h3[id$="result-card-address"]')
                if address_el.count() > 0:
                    address = safe_text(address_el.first)

                # Redes exactas
                facebook = ""
                instagram = ""
                fb_el = card.locator('a.social-media-icon[id^="facebook."]')
                if fb_el.count() > 0:
                    facebook = (fb_el.first.get_attribute("href") or "").strip()
                ig_el = card.locator('a.social-media-icon[id^="instagram."]')
                if ig_el.count() > 0:
                    instagram = (ig_el.first.get_attribute("href") or "").strip()

                # =========================
                # TELÉFONOS (robusto + debug)
                # =========================
                phone = ""
                try:
                    # Asegura que el botón esté visible antes de click
                    tel_btn = card.locator('button[aria-label="phone"][data-component="telephone"]').first
                    tel_btn.scroll_into_view_if_needed(timeout=1500)
                    tel_btn.click()
                    page.wait_for_timeout(350)

                    phones = []

                    # 1) Intento: buscar en el dropdown del mismo contenedor (NO por profile_id)
                    tel_box = card.locator('div[data-component="telephone"]').first
                    menu = tel_box.locator('div[role="menu"].yp-dropdown')

                    if menu.count() > 0:
                        try:
                            menu.first.wait_for(state="visible", timeout=2500)
                        except Exception:
                            pass

                        tel_links = menu.first.locator('a[href^="tel:"]')
                        for k in range(min(tel_links.count(), 10)):
                            link = tel_links.nth(k)
                            # número bonito en span (primer span)
                            num_span = link.locator("span").first
                            num_txt = safe_text(num_span) if num_span.count() else safe_text(link)
                            num_txt = num_txt.split("|")[0].strip()
                            if num_txt:
                                phones.append(num_txt)

                    # cerrar dropdown (para que no tape)
                    try:
                        tel_btn.click()
                        page.wait_for_timeout(120)
                    except Exception:
                        pass

                    # 2) Fallback: si sigue vacío, entrar al perfil del negocio y buscar tel allí
                    if not phones:
                        # abrir perfil: normalmente el nombre es clickeable (h2/h3/a)
                        profile_link = card.locator("a[href]").first
                        href = profile_link.get_attribute("href") if profile_link.count() else None

                        if href:
                            profile_url = urljoin(page.url, href)

                            prof = page.context.new_page()
                            try:
                                prof.goto(profile_url, timeout=45000, wait_until="domcontentloaded")
                                prof.wait_for_timeout(900)

                                # click al botón teléfono en el perfil (si existe)
                                prof_tel_btn = prof.locator(
                                    'button[aria-label="phone"][data-component="telephone"]').first
                                if prof_tel_btn.count():
                                    prof_tel_btn.scroll_into_view_if_needed(timeout=1500)
                                    prof_tel_btn.click()
                                    prof.wait_for_timeout(400)

                                # buscar cualquier tel: dentro de la página de perfil
                                prof_tel_links = prof.locator('a[href^="tel:"]')
                                for k in range(min(prof_tel_links.count(), 10)):
                                    txt = " ".join(prof_tel_links.nth(k).inner_text(timeout=1500).split())
                                    txt = txt.split("|")[0].strip()
                                    if txt:
                                        phones.append(txt)
                            finally:
                                try:
                                    prof.close()
                                except Exception:
                                    pass

                    # dedupe manteniendo orden
                    seen_p = set()
                    uniq = []
                    for pnum in phones:
                        if pnum not in seen_p:
                            seen_p.add(pnum)
                            uniq.append(pnum)

                    phone = " | ".join(uniq)

                except Exception:
                    phone = ""

                # =========================
                # WEBSITE (dropdown exacto)
                # =========================
                website = ""
                try:
                    web_box = card.locator('div[data-component="website"]')
                    web_btn = web_box.locator('button[aria-label="website"][data-component="website"]').first

                    if web_btn.count():
                        web_btn.scroll_into_view_if_needed(timeout=1500)
                        web_btn.click()
                        page.wait_for_timeout(300)

                        # 1) intento normal: menú dentro del web_box
                        menu = web_box.locator('div[role="menu"].yp-dropdown')
                        if menu.count() > 0:
                            try:
                                menu.first.wait_for(state="visible", timeout=2000)
                            except Exception:
                                pass

                            web_link = menu.first.locator('a[data-component="website"][href^="http"]')
                            if web_link.count() > 0:
                                website = (web_link.first.get_attribute("href") or "").strip()

                        # 2) fallback (Bethania): el link puede estar “portaleado” fuera del box
                        if not website and profile_id:
                            selector = f'a[id^="{profile_id}.website-link."][data-component="website"][href^="http"]'
                            try:
                                page.wait_for_selector(selector, timeout=3000)
                            except Exception:
                                pass

                            web_link2 = page.locator(selector)
                            if web_link2.count() > 0:
                                website = (web_link2.first.get_attribute("href") or "").strip()
                                

                        # cerrar dropdown
                        try:
                            web_btn.click()
                            page.wait_for_timeout(100)
                        except Exception:
                            pass

                except Exception:
                    website = ""

                # Email SOLO desde website real
                email = ""
                if website:
                    #if i < 3:
                    #    print(f"DEBUG website for '{name}': {website}")
                    email = fetch_email_from_website(context, website)

                rows.append({
                    "name": name,
                    "address": address,
                    "phone": phone,
                    "website": website,
                    "facebook": facebook,
                    "instagram": instagram,
                    "email": email,
                    "listing_page": page_num,
                })

            # Paginación real
            next_btn = page.locator("a#business\\.pagination\\.nextPage")
            if next_btn.count() == 0:
                print("[superpages] No hay botón next. Fin.")
                break

            cls = (next_btn.get_attribute("class") or "")
            if "p-disabled" in cls or "p-paginator-disabled" in cls:
                print("[superpages] Next deshabilitado. Fin.")
                break

            with page.expect_navigation():
                next_btn.click()

            url = page.url
            page_num += 1
            print("[superpages] Próxima página:", url)

        context.close()
        browser.close()

    if out_format == "json":
        save_json("output/superpages_labs.json", rows)
        print("✅ Guardado: output/superpages_labs.json")
    else:
        fields = ["name", "address", "phone", "website", "facebook", "instagram", "email", "listing_page"]
        save_csv("output/superpages_labs.csv", rows, fields)
        print("✅ Guardado: output/superpages_labs.csv")