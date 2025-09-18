# -*- coding: utf-8 -*-
# Guarda el HTML de UNA página con Selenium (Chrome).
# Uso:
#   pip install selenium undetected-chromedriver
#   python save_html_selenium.py "https://www.fragrantica.com/perfume/Lattafa-Perfumes/Khamrah-75805.html" sample.html
# Opcional:
#   HEADLESS=1 python save_html_selenium.py <url> <out.html>

# Python 3.9.6
# Solo funciona con fragrantica.com no con .es

import os, time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bs4 import BeautifulSoup
import re
import json
import shutil

import mimetypes, requests

def to_slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s

def build_driver():
    headless = (os.getenv("HEADLESS", "0") == "1")
    opts = uc.ChromeOptions()
    opts.page_load_strategy = "eager"
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1300,900")
    if headless:
        opts.add_argument("--headless=new")
    # use_subprocess=True es un fix común para el error "NoSuchWindowException: target window already closed"
    # que puede ocurrir si el proceso del navegador se cierra inesperadamente al inicio.
    drv = uc.Chrome(options=opts, use_subprocess=True)
    drv.set_page_load_timeout(40)
    return drv

def accept_cookies(driver):
    for xp in [
        "//button[contains(.,'Accept')]",
        "//button[contains(.,'Agree')]",
        "//button[contains(.,'Aceptar')]",
        "//button[contains(.,'Allow all')]",
    ]:
        btns = driver.find_elements(By.XPATH, xp)
        if btns:
            try:
                btns[0].click()
                break
            except Exception:
                pass

def scroll_to_bottom(driver, max_steps=6, pause=0.8):
    last_h = 0
    for _ in range(max_steps):
        h = driver.execute_script("return document.body.scrollHeight")
        driver.execute_script("window.scrollTo(0, arguments[0]);", h)
        time.sleep(pause)
        if h == last_h:
            break
        last_h = h

def save_html(url: str, out_path: str):
    driver = build_driver()
    try:
        driver.get(url)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        time.sleep(1.0)
        accept_cookies(driver)
        # opcional: baja al fondo para que cargue contenido lazy
        scroll_to_bottom(driver)
        html = driver.page_source
        # Asegurarse de que el directorio de salida exista
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[OK] Guardado {len(html)} caracteres en {out_path}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

def parser_html(html_path: str, out_path: str, url: str):
    if not os.path.exists(html_path):
        print(f"[ERROR] El archivo HTML no existe: {html_path}")
        return
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")   # o "html.parser" si no tienes lxml

    div_base = soup.select_one(
    "body > div#app > div.off-canvas-wrapper.grid-container > div#main-content > div.grid-x.grid-margin-x > div.small-12.medium-12.large-9.cell > div.grid-x.bg-white.grid-padding-x.grid-padding-y"
    )

    # Nombre
    name = div_base.select_one(
    "div#toptop > h1.text-center.medium-text-left"
    )

    # Marca
    brand = div_base.select_one(
    "div.cell.small-12 > div.grid-x.grid-margin-x.grid-margin-y > div.cell.small-6.text-center > p > a > span"
    )

    # Acordes
    main_accords = div_base.select(
    "div.cell.small-12 > div.grid-x.grid-margin-x.grid-margin-y > div.cell.small-6.text-center > div.grid-x"
    )
    main_accords = main_accords[1]
    main_accords = main_accords.select("div.cell.accord-box")

    # Tiempos/Ocasiones
    ideal_times = {}
    time = div_base.select(
        "div.cell.small-12"
    )
    time = time[1]
    time = time.select(
        "div.grid-x.grid-margin-x.grid-margin-y"
    )
    time = time[3]
    time = time.select(
        "div.cell.small-6"
    )
    time = time[1].select_one(
        "div"
    )
    time = time.select(
        "[index]"
    )
    for t in time:
        t_name = t.select_one(
            "div.show-for-medium"
        )
        t_name = t_name.select_one("span").text
        t_percentage = t.select_one(
            "div.voting-small-chart-size > div > div"
        )
        t_percentage = t_percentage.get("style","")
        m = re.search(r"width\s*:\s*([^;]+)", t_percentage, re.I)
        width = m.group(1).strip() if m else None
        ideal_times[t_name] = width

    # Notas
    notes_number = div_base.select(
        "div.cell.small-12 > div#pyramid.grid-x.grid-padding-y > div.cell > div > div"
    )

    elements = [str(tag.name) for tag in notes_number[1].find_all(True, recursive=True)]
    indices_h4 = [indice for indice, elemento in enumerate(elements) if elemento == 'h4']

    """top_notes_number = elements[indices_h4[0]:indices_h4[1]].count("span")
    middle_notes_number = elements[indices_h4[1]:indices_h4[2]].count("span")
    base_notes_number = elements[indices_h4[2]:].count("span")"""

    try:
        top_notes_number = elements[indices_h4[0]:indices_h4[1]].count("span")
        middle_notes_number = elements[indices_h4[1]:indices_h4[2]].count("span")
        base_notes_number = elements[indices_h4[2]:].count("span")
    except:
        indices_a = [indice for indice, elemento in enumerate(elements) if elemento == 'a']
        top_notes_number = len(indices_a)
        middle_notes_number = 0
        base_notes_number = 0

    total_notes = []
    notes = div_base.select(
        "div.cell.small-12 > div#pyramid.grid-x.grid-padding-y > div.cell > div > div > div > div > div > div"
    )
    for note in notes:
        if note.text != "":
            total_notes.append(note.text)
    notes_final = {
        "top_notes": total_notes[:top_notes_number],
        "middle_notes": total_notes[top_notes_number:top_notes_number + middle_notes_number] if middle_notes_number != 0 else [],
        "base_notes": total_notes[-base_notes_number:] if base_notes_number != 0 else []
    }

    # Diccionario Final
    parfum_features = {
        "name": name.text.split(" for ")[0],
        "brand": brand.text,
        "gender": name.text.split(" for ")[1],
        "accords": [accord.text for accord in main_accords],
        "ideal_times": ideal_times,
        "notes": notes_final,
        "img_url": f"https://fimgs.net/mdimg/perfume-thumbs/375x500.{url.split('/')[-1].split('-')[-1][:-5]}.jpg"
    }

    # Escritura de datos:
    with open(out_path, "w") as archivo:
        json.dump(parfum_features, archivo)

def download_image(url, out_dir="images", filename=None,
                   referer="https://www.fragrantica.com/"):
    os.makedirs(out_dir, exist_ok=True)
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": referer, 
    }
    with requests.get(url, headers=headers, stream=True, timeout=20) as r:
        r.raise_for_status()
        name = filename or url.split("/")[-1].split("?")[0]
        ctype = (r.headers.get("Content-Type") or "").split(";")[0]
        ext = mimetypes.guess_extension(ctype) or ".jpg"
        if "." not in os.path.basename(name):
            name += ext
        path = os.path.join(out_dir, name)
        with open(path, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
    return path

urls_nicho = [
"https://www.fragrantica.com/perfume/Le-Labo/The-Matcha-26-69731.html",
"https://www.fragrantica.com/perfume/Le-Labo/Santal-33-12201.html",
"https://www.fragrantica.com/perfume/Louis-Vuitton/Rose-des-Vents-40495.html",
"https://www.fragrantica.com/perfume/Louis-Vuitton/L-Immensite-49751.html",
"https://www.fragrantica.com/perfume/Louis-Vuitton/Pacific-Chill-81423.html",
"https://www.fragrantica.com/perfume/Louis-Vuitton/Imagination-67370.html",
"https://www.fragrantica.com/perfume/Louis-Vuitton/Attrape-Reves-51016.html",
"https://www.fragrantica.com/perfume/Louis-Vuitton/Ombre-Nomade-49755.html",
"https://www.fragrantica.com/perfume/Parfums-de-Marly/Delina-43871.html",
"https://www.fragrantica.com/perfume/Tom-Ford/Ombre-Leather-2018-50239.html",
"https://www.fragrantica.com/perfume/Tom-Ford/Black-Orchid-1018.html",
"https://www.fragrantica.com/perfume/Tom-Ford/Lost-Cherry-51411.html",
"https://www.fragrantica.com/perfume/By-Kilian/Black-Phantom-43632.html",
"https://www.fragrantica.com/perfume/Xerjoff/Erba-Pura-55157.html"
]

if __name__ == "__main__":
    # url_master = "https://www.fragrantica.com/perfume/Creed/Carmina-84206.html"
    for url_master in urls_nicho:

        # 1. Extraer el ID del perfume de la URL para usarlo como identificador único.
        perfume_name_id = url_master.split("/")[-1].replace(".html", "")

        # 2. Crear un directorio temporal para los archivos intermedios.
        temp_dir = os.path.join("data", "temp", perfume_name_id)
        os.makedirs(temp_dir, exist_ok=True)

        # 3. Definir rutas para los archivos temporales de HTML y JSON.
        temp_html_path = os.path.join(temp_dir, f"{perfume_name_id}.html")
        temp_json_path = os.path.join(temp_dir, f"{perfume_name_id}.json")

        # 4. Guardar y parsear el HTML para crear un JSON temporal.
        save_html(url_master, temp_html_path)
        parser_html(temp_html_path, temp_json_path, url_master)

        # 5. Leer el JSON temporal para obtener la marca y otros datos.
        if not os.path.exists(temp_json_path):
            print(f"[ERROR] El parser no pudo crear el archivo JSON: {temp_json_path}")
            shutil.rmtree(os.path.dirname(temp_dir)) # Limpiar directorio padre 'temp' si está vacío
            exit()

        with open(temp_json_path, "r", encoding="utf-8") as f:
            perfume_data = json.load(f)

        if not perfume_data or not perfume_data.get("brand"):
            print(f"[ERROR] No se pudo leer la marca del JSON para {url_master}")
            shutil.rmtree(os.path.dirname(temp_dir))
            exit()

        # 6. Crear el slug de la marca y la estructura de directorios final.
        brand_slug = to_slug(perfume_data["brand"])
        final_output_dir = os.path.join("dataset", "perfumes", brand_slug, perfume_name_id)
        os.makedirs(final_output_dir, exist_ok=True)

        # 7. Mover y renombrar el archivo JSON a meta.json.
        final_json_path = os.path.join(final_output_dir, "meta.json")
        shutil.move(temp_json_path, final_json_path)
        print(f"[OK] Guardado meta.json en {final_json_path}")

        # 8. Descargar la imagen como image.jpg en el directorio final.
        image_path = download_image(
            url=perfume_data["img_url"],
            out_dir=final_output_dir,
            filename="image.jpg",
            referer=url_master
        )
        print(f"[OK] Guardada imagen en {image_path}")

        # 9. Limpiar el directorio temporal.
        shutil.rmtree(temp_dir)
        print(f"[OK] Limpiado directorio temporal {temp_dir}")
