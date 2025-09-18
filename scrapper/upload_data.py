# -*- coding: utf-8 -*-
"""
Sube imágenes a Firebase Storage e inserta/actualiza metadata en Firestore.

Prerrequisitos:
  pip install firebase-admin google-cloud-firestore google-cloud-storage python-slugify
  export GOOGLE_APPLICATION_CREDENTIALS=/ruta/a/tu/firebase-admin.json

Uso:
  python upload_to_firebase.py \
    --root dataset \
    --bucket tu-proyecto.appspot.com \
    --collection perfumes \
    --project_id tu-proyecto

Notas:
- El docId en Firestore será meta["id"] si existe, si no se genera a partir de brand+name.
- En el doc se guarda imagePath (ruta en Storage). En la app, usa getDownloadURL(imagePath).
"""

import os, re, json, argparse
from pathlib import Path
from typing import Dict, Any, Optional

import firebase_admin
from firebase_admin import credentials, firestore, storage as fb_storage
from slugify import slugify

# ---------- Helpers ----------

def pct_to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip().replace("%","")
    try:
        return round(float(s), 4)
    except Exception:
        return None

def ensure_list(x):
    if x is None: return []
    if isinstance(x, list): return x
    return [x]

def normalize_record(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte tu meta JSON al shape plano para Firestore."""
    out: Dict[str, Any] = {}
    out["id"]     = str(meta.get("id") or "").strip() or None
    out["name"]   = str(meta.get("name") or "").strip()
    out["brand"]  = str(meta.get("brand") or "").strip()
    out["gender"] = (meta.get("gender") or "").strip() or None
    out["accords"] = [str(a).strip() for a in ensure_list(meta.get("accords")) if str(a).strip()]

    # notes -> arrays separados (más fácil de consultar con array-contains)
    notes = meta.get("notes") or {}
    out["notes_top"]  = [str(n).strip() for n in ensure_list(notes.get("top_notes")) if str(n).strip()]
    out["notes_mid"]  = [str(n).strip() for n in ensure_list(notes.get("middle_notes")) if str(n).strip()]
    out["notes_base"] = [str(n).strip() for n in ensure_list(notes.get("base_notes")) if str(n).strip()]

    # times -> números (0..100)
    times = meta.get("ideal_times") or {}
    out["times"] = {}
    for k in ["winter","spring","summer","fall","day","night"]:
        v = pct_to_float(times.get(k))
        if v is not None:
            out["times"][k] = v

    # otros campos opcionales
    out["image_url"] = meta.get("img_url")  # opcional, original de origen
    return out

def gen_doc_id(name: str, brand: str) -> str:
    base = f"{brand}::{name}".strip().lower()
    # id legible
    return slugify(base)[:140] or "perfume"

def upload_image_if_exists(local_img: Path, bucket_name: str, dest_path: str) -> Optional[str]:
    if not local_img.exists():
        return None
    bucket = fb_storage.bucket(bucket_name)
    blob = bucket.blob(dest_path)
    # headers útiles de cache
    blob.cache_control = "public, max-age=31536000, immutable"
    # content-type básico
    if str(local_img).lower().endswith(".png"):
        blob.content_type = "image/png"
    elif str(local_img).lower().endswith(".webp"):
        blob.content_type = "image/webp"
    else:
        blob.content_type = "image/jpeg"
    blob.upload_from_filename(str(local_img))
    return dest_path  # guardamos la ruta como imagePath

def walk_perfumes(root: Path):
    perfumes_root = root / "perfumes"
    if not perfumes_root.exists():
        return
    for brand_dir in perfumes_root.iterdir():
        if not brand_dir.is_dir(): continue
        for entry in brand_dir.iterdir():
            if not entry.is_dir(): continue
            meta_path = entry / "meta.json"
            if not meta_path.exists(): continue
            yield brand_dir.name, entry.name, meta_path, (entry / "image.jpg")

def main(args):
    # Inicializa Firebase Admin
    if not firebase_admin._apps:
        if args.credentials:
            cred = credentials.Certificate(args.credentials)
            firebase_admin.initialize_app(cred, {
                'storageBucket': args.bucket,
                'projectId': args.project_id
            })
        else:
            # Usará GOOGLE_APPLICATION_CREDENTIALS si está seteado
            firebase_admin.initialize_app(options={
                'storageBucket': args.bucket,
                'projectId': args.project_id
            })

    db = firestore.client()
    bucket = fb_storage.bucket(args.bucket)

    root = Path(args.root)
    count = 0
    for brand_slug, name_id, meta_path, image_path in walk_perfumes(root):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        rec  = normalize_record(meta)

        # docId: usa meta["id"] si hay; si no, genera uno legible
        doc_id = rec.get("id") or gen_doc_id(rec["name"], rec["brand"])

        # sube imagen (si existe localmente) a una ruta estable en Storage
        dest_img_path = f"perfumes/{brand_slug}/{name_id}/image.jpg"
        imagePath = upload_image_if_exists(image_path, args.bucket, dest_img_path)

        # data para Firestore
        data = {
            "name": rec["name"],
            "brand": rec["brand"],
            "gender": rec.get("gender"),
            "accords": rec.get("accords", []),
            "notes_top": rec.get("notes_top", []),
            "notes_mid": rec.get("notes_mid", []),
            "notes_base": rec.get("notes_base", []),
            "times": rec.get("times", {}),
            "imagePath": imagePath,            # ruta en Storage (usa getDownloadURL en el cliente)
            "sourceImageUrl": rec.get("image_url"), # opcional
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }

        # upsert
        db.collection(args.collection).document(doc_id).set(data, merge=True)
        count += 1
        print(f"[OK] {doc_id} -> Firestore (+ imagen: {'sí' if imagePath else 'no'})")

    print(f"\nListo. Subidos/actualizados: {count} documentos en '{args.collection}' (bucket: {args.bucket}).")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="dataset", help="Directorio raíz del dataset local")
    ap.add_argument("--bucket", required=True, help="Nombre del bucket de Storage (p.ej. tu-proyecto.appspot.com)")
    ap.add_argument("--collection", default="perfumes", help="Colección de Firestore destino")
    ap.add_argument("--project_id", required=True, help="ID del proyecto Firebase/GC (p.ej. tu-proyecto)")
    ap.add_argument("--credentials", default=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
                    help="Ruta al JSON de service account (o usa env GOOGLE_APPLICATION_CREDENTIALS)")
    args = ap.parse_args()
    main(args)

