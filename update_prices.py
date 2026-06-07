"""
Amega Imobiliare – Actualizare automată prețuri €/mp pe cartier Oradea
Rulează lunar via GitHub Actions. Scrapeaza storia.ro pentru medii de preț.
"""

import json
import time
import re
import sys
from datetime import date
from statistics import median

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Instalez dependinte...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4"])
    import requests
    from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ro-RO,ro;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xhtml;q=0.9,*/*;q=0.8",
}

# Mapare cartier -> slug storia.ro
STORIA_SLUGS = {
    "ultracentral": "ultracentral",
    "centru":       "centru",
    "nufarul":      "nufarul",
    "cantemir":     "cantemir",
    "grigorescu":   "grigorescu",
    "rogerius":     "rogerius",
    "decebal":      "decebal",
    "iosia":        "iosia",
    "velenta":      "velenta",
    "episcopia":    "episcopia-bihor",
    "seleus":       "seleus",
    "betfia":       None,  # nu apare pe storia, folosim fallback
}

# Prețuri fallback (folosite dacă scraping-ul nu returnează date suficiente)
FALLBACK_PRICES = {
    "ultracentral": 1700,
    "centru":       1500,
    "nufarul":      1250,
    "cantemir":     1200,
    "grigorescu":   1200,
    "rogerius":     1900,
    "decebal":      1100,
    "iosia":        1050,
    "velenta":      1000,
    "episcopia":    950,
    "seleus":       950,
    "betfia":       880,
}

PRICES_FILE = "prices.json"


def fetch_storia_prices(slug: str) -> list[float]:
    """Returnează lista de prețuri €/mp găsite pe storia.ro pentru un cartier."""
    url = (
        f"https://www.storia.ro/ro/rezultate/vanzare/apartament/bihor/oradea/{slug}"
        f"?distanceRadius=0&ownerTypeSingleSelect=ALL&by=DEFAULT&direction=DESC&viewType=listing"
    )
    prices_per_sqm = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  ⚠ storia.ro a returnat {resp.status_code} pentru {slug}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # Extrage cardurile de anunțuri
        listings = soup.find_all("article") or soup.find_all("li", attrs={"data-cy": True})

        for listing in listings:
            text = listing.get_text(" ", strip=True)

            # Caută prețul total (ex: "85 000 €" sau "85.000 €")
            price_match = re.search(r"([\d\s\.]+)\s*€", text)
            # Caută suprafața (ex: "55 m²" sau "55mp")
            sqm_match = re.search(r"(\d+)\s*m[²2p]", text, re.IGNORECASE)

            if price_match and sqm_match:
                try:
                    price = float(re.sub(r"[\s\.]", "", price_match.group(1)))
                    sqm = float(sqm_match.group(1))
                    if 15 < sqm < 300 and 10_000 < price < 2_000_000:
                        eur_sqm = price / sqm
                        if 500 < eur_sqm < 5000:
                            prices_per_sqm.append(eur_sqm)
                except (ValueError, ZeroDivisionError):
                    pass

        print(f"  ✓ {slug}: {len(prices_per_sqm)} anunțuri procesate")
    except Exception as e:
        print(f"  ✗ Eroare la {slug}: {e}")

    return prices_per_sqm


def compute_median_price(prices: list[float]) -> int | None:
    """Returnează mediana prețurilor, rotunjită la 50€."""
    if len(prices) < 3:
        return None
    med = median(prices)
    return int(round(med / 50) * 50)


def load_existing() -> dict:
    try:
        with open(PRICES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save(data: dict):
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ prices.json actualizat: {data['last_updated']}")


def main():
    print("🔄 Actualizare prețuri Amega Imobiliare...")
    existing = load_existing()

    # Construiește dicționarul existent {key: eur_sqm}
    old_prices = {}
    for item in existing.get("cartiere", []):
        old_prices[item["key"]] = item["eur_sqm"]

    new_cartiere = []
    labels = {
        "ultracentral": "Ultracentral",
        "centru":       "Centru",
        "nufarul":      "Nufărul",
        "cantemir":     "Cantemir",
        "grigorescu":   "Grigorescu",
        "rogerius":     "Rogerius",
        "decebal":      "Decebal",
        "iosia":        "Ioșia",
        "velenta":      "Velența",
        "episcopia":    "Episcopia Bihor",
        "seleus":       "Seleuș",
        "betfia":       "Betfia / Periferie",
    }

    for key, slug in STORIA_SLUGS.items():
        print(f"\n📍 {labels[key]}...")
        new_price = None

        if slug:
            time.sleep(2)  # respectă rate limiting
            raw_prices = fetch_storia_prices(slug)
            new_price = compute_median_price(raw_prices)

        if new_price:
            # Verificare sanity: max ±25% față de preț vechi sau fallback
            ref = old_prices.get(key) or FALLBACK_PRICES[key]
            if abs(new_price - ref) / ref > 0.25:
                print(f"  ⚠ Variație mare ({ref} → {new_price}), păstrez prețul vechi")
                new_price = ref
            else:
                print(f"  💰 {ref} → {new_price} €/mp")
        else:
            # Fallback: prețul precedent sau prețul hardcodat
            new_price = old_prices.get(key) or FALLBACK_PRICES[key]
            print(f"  ℹ Fallback: {new_price} €/mp")

        new_cartiere.append({
            "key":      key,
            "label":    labels[key],
            "eur_sqm":  new_price,
        })

    result = {
        "last_updated": str(date.today()),
        "note": "Preturi medii €/mp pentru apartamente in Oradea. Actualizat automat lunar.",
        "cartiere": new_cartiere,
    }
    save(result)


if __name__ == "__main__":
    main()
