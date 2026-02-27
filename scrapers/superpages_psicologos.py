import csv
import json
import os
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


START = "https://superpagespr.com/es/business/search/puerto-rico/c/sicologos-por-especialidad-%3E-clinicos"
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
            found.append(urljoin(base_url, href))

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
    """Busca email en home + /index + contacto, con scroll al footer."""
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
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(900)
            except Exception:
                pass

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


def run_superpages_psicologos(out_format="csv", limit_pages=0, headful=False, user_agent="scraperone/1.0"):
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
                print(f"[superpages_psicologos] Límite alcanzado: {limit_pages} páginas. Cortando.")
                break

            print(f"[superpages_psicologos] Página {page_num}: {url}")
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)

            # Esperar a que aparezcan tarjetas (Angular)
            try:
                page.wait_for_selector("article.yp-result-listing-card", timeout=20000)
            except Exception:
                # Si no hay cards, guardamos debug y terminamos
                page.screenshot(path="output/debug_psicologos_no_cards.png", full_page=True)
                with open("output/debug_psicologos_no_cards.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                print("[superpages_psicologos] No aparecieron cards. Revisá output/debug_psicologos_no_cards.*")
                break

            cards = page.locator("article.yp-result-listing-card")
            count = cards.count()
            print(f"[superpages_psicologos] Cards detectadas: {count}")

            for i in range(count):
                card = cards.nth(i)

                # profile_id
                profile_id = (card.get_attribute("data-profile-id") or "").strip()
                if not profile_id:
                    btn_id = (card.locator('button[data-component="telephone"]').first.get_attribute("id") or "")
                    profile_id = btn_id.split(".")[0] if btn_id else ""

                if profile_id and profile_id in seen_profile_ids:
                    continue
                if profile_id:
                    seen_profile_ids.add(profile_id)

                name = " ".join(((card.get_attribute("label") or "").strip()).split())
                if not name:
                    continue

                # address exacta
                address = ""
                address_el = card.locator('h3[id$="result-card-address"]')
                if address_el.count() > 0:
                    address = safe_text(address_el.first)

                # redes exactas
                facebook = ""
                instagram = ""
                fb_el = card.locator('a.social-media-icon[id^="facebook."]')
                if fb_el.count() > 0:
                    facebook = (fb_el.first.get_attribute("href") or "").strip()
                ig_el = card.locator('a.social-media-icon[id^="instagram."]')
                if ig_el.count() > 0:
                    instagram = (ig_el.first.get_attribute("href") or "").strip()

                # =========================
                # TELÉFONOS (dropdown + fallback perfil)
                # =========================
                phone = ""
                try:
                    tel_btn = card.locator('button[aria-label="phone"][data-component="telephone"]').first
                    if tel_btn.count():
                        tel_btn.scroll_into_view_if_needed(timeout=1500)
                        tel_btn.click(force=True)
                        page.wait_for_timeout(350)

                        phones = []

                        # intento en card
                        tel_links_card = card.locator('a[href^="tel:"]')
                        for k in range(min(tel_links_card.count(), 10)):
                            txt = safe_text(tel_links_card.nth(k))
                            txt = txt.split("|")[0].strip()
                            if txt:
                                phones.append(txt)

                        # fallback: abrir perfil si vacío
                        if not phones:
                            profile_link = card.locator("a[href]").first
                            href = profile_link.get_attribute("href") if profile_link.count() else None
                            if href:
                                profile_url = urljoin(page.url, href)
                                prof = page.context.new_page()
                                try:
                                    prof.goto(profile_url, timeout=45000, wait_until="domcontentloaded")
                                    prof.wait_for_timeout(900)
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

                        # dedupe
                        seen_p = set()
                        uniq = []
                        for pnum in phones:
                            if pnum not in seen_p:
                                seen_p.add(pnum)
                                uniq.append(pnum)
                        phone = " | ".join(uniq)

                        # cerrar dropdown
                        try:
                            tel_btn.click(force=True)
                            page.wait_for_timeout(120)
                        except Exception:
                            pass

                except Exception:
                    phone = ""

                # =========================
                # WEBSITE (definitivo: card -> dropdown -> page)
                # =========================
                website = ""
                try:
                    # 1) link directo en card por id
                    if profile_id:
                        a = card.locator(f'a[id^="{profile_id}.website-link."][data-component="website"]').first
                        if a.count():
                            href = (a.get_attribute("href") or "").strip()
                            if href.startswith("http"):
                                website = href
                            else:
                                link_id = a.get_attribute("id") or ""
                                if ".website-link." in link_id:
                                    website = link_id.split(".website-link.", 1)[1].strip()

                    # 2) dropdown dentro del box
                    if not website:
                        web_box = card.locator('div[data-component="website"]').first
                        web_btn = web_box.locator('button[aria-label="website"][data-component="website"]').first
                        if web_btn.count():
                            web_btn.scroll_into_view_if_needed(timeout=1500)
                            web_btn.click(force=True)
                            page.wait_for_timeout(350)

                            menu = web_box.locator('div[role="menu"].yp-dropdown')
                            if menu.count():
                                try:
                                    menu.first.wait_for(state="visible", timeout=2500)
                                except Exception:
                                    pass
                                web_link = menu.first.locator('a[data-component="website"][href^="http"]').first
                                if web_link.count():
                                    website = (web_link.get_attribute("href") or "").strip()

                            try:
                                web_btn.click(force=True)
                                page.wait_for_timeout(120)
                            except Exception:
                                pass

                    # 3) fallback en toda la página
                    if not website and profile_id:
                        a2 = page.locator(f'a[id^="{profile_id}.website-link."][data-component="website"]').first
                        if a2.count():
                            href = (a2.get_attribute("href") or "").strip()
                            if href.startswith("http"):
                                website = href
                            else:
                                link_id = a2.get_attribute("id") or ""
                                if ".website-link." in link_id:
                                    website = link_id.split(".website-link.", 1)[1].strip()

                except Exception:
                    website = ""

                # Email SOLO desde website real
                email = ""
                if website:
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

            # paginación
            next_btn = page.locator("a#business\\.pagination\\.nextPage")
            if next_btn.count() == 0:
                print("[superpages_psicologos] No hay botón next. Fin.")
                break

            cls = (next_btn.get_attribute("class") or "")
            if "p-disabled" in cls or "p-paginator-disabled" in cls:
                print("[superpages_psicologos] Next deshabilitado. Fin.")
                break

            with page.expect_navigation():
                next_btn.click()

            url = page.url
            page_num += 1
            print("[superpages_psicologos] Próxima página:", url)

        context.close()
        browser.close()

    # Guardar
    if out_format == "json":
        save_json("output/superpages_psicologos.json", rows)
        print("✅ Guardado: output/superpages_psicologos.json")
    else:
        fields = ["name", "address", "phone", "website", "facebook", "instagram", "email", "listing_page"]
        save_csv("output/superpages_psicologos.csv", rows, fields)
        print("✅ Guardado: output/superpages_psicologos.csv")