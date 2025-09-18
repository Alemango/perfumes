# -*- coding: utf-8 -*-
"""
Genera index.json y facets/*.json a partir de meta.json por perfume
Estructura esperada:
  dataset/
    perfumes/<brand-slug>/<name-id>/
      meta.json
      image.jpg
Salidas:
  dataset/catalog/index.json
  dataset/facets/{notes.json, accords.json, brands.json, gender.json, times.json}

Opcional: subir todo el directorio dataset/ a Cloudflare R2 (S3 compatible)
ENV requeridas para upload:
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
"""

import os, json, re, argparse, sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple, Optional

# ---- Helpers --------------------------------------------------------------

def read_json(p: Path) -> Any:
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def write_json(p: Path, data: Any, pretty: bool = True):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        if pretty:
            json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

def to_slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s

def pct_to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    s = s.replace("%", "")
    try:
        return round(float(s), 4)
    except Exception:
        return None

def ensure_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]

# ---- Catalog builder ------------------------------------------------------

def gather_perfumes(root: Path) -> List[Tuple[str, Path]]:
    """
    Busca meta.json en dataset/perfumes/**/meta.json
    Retorna [(rel_dir, meta_path)]
    """
    perfumes_root = root / "perfumes"
    pairs = []
    if not perfumes_root.exists():
        return pairs
    for brand in sorted(p.name for p in perfumes_root.iterdir() if p.is_dir()):
        brand_dir = perfumes_root / brand
        for entry in sorted(p.name for p in brand_dir.iterdir() if p.is_dir()):
            meta_path = brand_dir / entry / "meta.json"
            if meta_path.exists():
                rel_dir = f"/perfumes/{brand}/{entry}"
                pairs.append((rel_dir, meta_path))
    return pairs

def build_items(pairs: List[Tuple[str, Path]], public_base_url: str) -> List[Dict[str, Any]]:
    items = []
    for rel_dir, meta_path in pairs:
        try:
            meta = read_json(meta_path)
        except Exception:
            continue

        pid   = str(meta.get("img_url") or "")
        name  = str(meta.get("name") or "")
        brand = str(meta.get("brand") or "")
        gender = meta.get("gender") or None

        # accords (top 10 en index; completos en meta.json)
        accords = ensure_list(meta.get("accords"))[:10]

        # notes normalizadas para el index (ligero)
        notes_obj = meta.get("notes") or {}
        notes = {
            "top":  ensure_list(notes_obj.get("top_notes")),
            "mid":  ensure_list(notes_obj.get("middle_notes")),
            "base": ensure_list(notes_obj.get("base_notes")),
        }

        # times -> floats (0..100)
        times_obj = meta.get("ideal_times") or {}
        times = {}
        for k in ["winter","spring","summer","fall","day","night"]:
            v = pct_to_float(times_obj.get(k))
            if v is not None:
                times[k] = v

        item = {
            "id": pid.split(".")[-2],
            "name": name,
            "brand": brand,
            "brand_slug": to_slug(brand),
            "gender": gender,
            "accords": accords,
            "notes": notes,      # si prefieres, quita esto del index para hacerlo aún más ligero
            "times": times,
            "image_url": f"{public_base_url}{rel_dir}/image.jpg",
            "meta_url":  f"{public_base_url}{rel_dir}/meta.json",
            "updated_at": meta.get("updated_at"),
        }
        items.append(item)
    return items

def build_facets(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[str]]]:
    """
    Retorna dict con varios facets invertidos: notes, accords, brands, gender, times
    Cada valor mapea a lista de IDs (strings)
    """
    f_notes: Dict[str, List[str]] = {}
    f_accords: Dict[str, List[str]] = {}
    f_brands: Dict[str, List[str]] = {}
    f_gender: Dict[str, List[str]] = {}
    f_times: Dict[str, Dict[str, List[str]]] = {k:{} for k in ["winter","spring","summer","fall","day","night"]}

    for it in items:
        pid = str(it["id"])
        # accords
        for a in ensure_list(it.get("accords")):
            k = a.strip().lower()
            if not k: continue
            f_accords.setdefault(k, []).append(pid)
        # notes (top, mid, base)
        notes = it.get("notes") or {}
        for tier_key in ["top","mid","base"]:
            for n in ensure_list(notes.get(tier_key)):
                k = n.strip()
                if not k: continue
                # facet unificado de notas (sin distinguir tier)
                f_notes.setdefault(k, []).append(pid)
        # brands
        b = (it.get("brand") or "").strip()
        if b:
            f_brands.setdefault(b, []).append(pid)
        # gender
        g = (it.get("gender") or "").strip()
        if g:
            f_gender.setdefault(g, []).append(pid)
        # times (bucket -> ids con pct>0)
        times = it.get("times") or {}
        for bucket, pct in times.items():
            try:
                v = float(pct)
            except Exception:
                v = 0.0
            if v > 0:
                f_times.setdefault(bucket, {}).setdefault(str(int(v)), [])  # opcional por percentiles exactos
                # también guardemos una lista simple (>=50, >=80) útil para filtros rápidos
    # además de mapas por valor exacto, exportemos umbrales comunes para times
    thresholds = [50, 70, 80, 90]
    f_times_thresh: Dict[str, Dict[str, List[str]]] = {k:{} for k in ["winter","spring","summer","fall","day","night"]}
    for it in items:
        pid = str(it["id"])
        times = it.get("times") or {}
        for bucket, pct in times.items():
            try:
                v = float(pct)
            except Exception:
                v = 0.0
            for th in thresholds:
                if v >= th:
                    f_times_thresh[bucket].setdefault(f">={th}", []).append(pid)

    return {
        "notes": f_notes,
        "accords": f_accords,
        "brands": f_brands,
        "gender": f_gender,
        "times": f_times_thresh  # exportamos los thresholds útiles
    }

def build_catalog(root_dir: str, public_base_url: str, compact: bool = True):
    root = Path(root_dir)
    pairs = gather_perfumes(root)
    items = build_items(pairs, public_base_url)

    catalog = {
        "version": 1,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "count": len(items),
        "items": items if not compact else items  # (si quisieras, podrías reducir aún más)
    }
    write_json(root / "catalog" / "index.json", catalog, pretty=True)

    facets = build_facets(items)
    facets_dir = root / "facets"
    write_json(facets_dir / "notes.json", facets["notes"], pretty=False)
    write_json(facets_dir / "accords.json", facets["accords"], pretty=False)
    write_json(facets_dir / "brands.json", facets["brands"], pretty=False)
    write_json(facets_dir / "gender.json", facets["gender"], pretty=False)
    write_json(facets_dir / "times.json", facets["times"], pretty=False)

    print(f"[OK] catalog/index.json y facets/* generados en {root_dir}")

# ---- CLI ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Construye catalog/index.json y facets/* desde meta.json por perfume")
    ap.add_argument("--root", default="dataset", help="Directorio raíz del dataset (def: dataset)")
    ap.add_argument("--base-url", required=True, help="Base pública (ej: https://img.tudominio.com)")
    ap.add_argument("--upload", action="store_true", help="Subir todo el dataset a R2 (usa ENV)")
    args = ap.parse_args()

    build_catalog(args.root, args.base_url, compact=True)

if __name__ == "__main__":
    main()
