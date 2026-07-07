#!/usr/bin/env python3
"""Pipeline de ofertas: Sheets → Gemini → site JSON → Telegram."""

import argparse
import io
import sys

# Force UTF-8 output on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
OFERTAS_JSON = REPO_ROOT / "site" / "src" / "data" / "ofertas.json"
PROMPT_FILE = Path(__file__).parent / "prompt_gemini.txt"

# ── Environment ───────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
AFFILIATE_TAG = os.environ.get("AFFILIATE_TAG", "SEUTAG-20")
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://ofertas.vercel.app").rstrip("/")
GEMINI_MODEL = "gemini-2.0-flash"

# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_amazon_link(url: str) -> tuple[str | None, str | None]:
    """Extracts (asin, titulo) from a full Amazon product URL."""
    asin_match = re.search(r"/dp/([A-Z0-9]{10})", url) or re.search(
        r"/gp/product/([A-Z0-9]{10})", url
    )
    if not asin_match:
        return None, None
    asin = asin_match.group(1)

    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split("/") if p]
    titulo = None
    for i, part in enumerate(path_parts):
        if part in ("dp", "gp") and i > 0:
            candidate = unquote(path_parts[i - 1])
            # Must look like a name: has 3+ letters and at least one hyphen
            if re.search(r"[a-zA-Z]{3,}", candidate) and "-" in candidate:
                titulo = candidate.replace("-", " ").strip().title()
            break

    return asin, titulo


def normalizar_preco(valor) -> str:
    """Normalizes any price format to Brazilian display: 1.649,00"""
    if isinstance(valor, (int, float)):
        num = float(valor)
    else:
        s = str(valor).strip().replace(" ", "")
        if not s:
            return "0,00"
        # BR format: dot = thousands sep, comma = decimal sep → convert to float
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        try:
            num = float(s)
        except ValueError:
            return str(valor).strip()
    # f"{:,.2f}" → EN "1,649.00" → swap to BR "1.649,00"
    return f"{num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def make_slug(titulo: str, asin: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", titulo.lower()).strip("-")
    return f"{base}-{asin[-4:].lower()}"


# ── Gemini ────────────────────────────────────────────────────────────────────

def call_gemini(titulo: str, preco: str, obs: str | None) -> dict | None:
    """Calls Gemini and returns parsed JSON dict, or None on any failure."""
    if not GEMINI_API_KEY:
        return None
    try:
        import requests as req

        prompt_template = PROMPT_FILE.read_text(encoding="utf-8")
        user_content = (
            prompt_template
            + f"\n\nDados:\n- Título: {titulo}\n- Preço: R$ {preco}\n- Obs: {obs or ''}"
        )
        payload = {
            "contents": [{"parts": [{"text": user_content}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 600},
        }
        resp = req.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as exc:
        print(f"[Gemini] falhou ({exc}) — usando fallback", file=sys.stderr)
        return None


def fallback_post(titulo: str, preco: str, obs: str | None, url_pagina: str) -> dict:
    """Generates post and description from a fixed template (no LLM)."""
    obs_line = f"\n✅ {obs}" if obs else ""
    post = (
        f"🔥 Oferta verificada!\n"
        f"*{titulo}* por *R$ {preco}*{obs_line}\n"
        f"➡️ Ver oferta: {url_pagina}\n"
        f"🔗 link de afiliado · #publi"
    )
    descricao = (
        f"{titulo} disponível na Amazon Brasil por R$ {preco}. "
        f"Confira o preço atualizado na página da oferta."
    )
    return {"post_whatsapp": post, "descricao_pagina": descricao}


# ── Site JSON ─────────────────────────────────────────────────────────────────

def publish_to_site(oferta: dict, dry_run: bool) -> None:
    ofertas = json.loads(OFERTAS_JSON.read_text(encoding="utf-8"))
    ofertas = [o for o in ofertas if o["slug"] != oferta["slug"]]  # dedupe on re-run
    ofertas.insert(0, oferta)  # newest first
    if dry_run:
        print(
            f"\n[dry-run] Entrada que seria adicionada ao ofertas.json:\n"
            + json.dumps(oferta, ensure_ascii=False, indent=2)
        )
        return
    OFERTAS_JSON.write_text(json.dumps(ofertas, ensure_ascii=False, indent=2), encoding="utf-8")


def git_commit_push(slug: str, dry_run: bool) -> None:
    if dry_run:
        print("[dry-run] pulando commit/push")
        return
    subprocess.run(["git", "config", "user.email", "bot@ofertas-pipeline"], check=True, cwd=REPO_ROOT)
    subprocess.run(["git", "config", "user.name", "ofertas-bot"], check=True, cwd=REPO_ROOT)
    subprocess.run(["git", "add", str(OFERTAS_JSON)], check=True, cwd=REPO_ROOT)
    subprocess.run(["git", "commit", "-m", f"oferta: {slug}"], check=True, cwd=REPO_ROOT)
    subprocess.run(["git", "push"], check=True, cwd=REPO_ROOT)


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(post: str, imagem_url: str | None, dry_run: bool) -> None:
    if dry_run:
        print(f"\n[dry-run] Mensagem do Telegram:\n{post}")
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] tokens não configurados, pulando", file=sys.stderr)
        return
    import requests as req

    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    if imagem_url:
        req.post(
            f"{base}/sendPhoto",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "photo": imagem_url,
                "caption": post,
                "parse_mode": "Markdown",
            },
            timeout=15,
        ).raise_for_status()
    else:
        req.post(
            f"{base}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": post,
                "parse_mode": "Markdown",
            },
            timeout=15,
        ).raise_for_status()


# ── Row processor ─────────────────────────────────────────────────────────────

def process_row(row: dict, row_index: int, sheet, dry_run: bool) -> None:
    link = str(row.get("link", "")).strip()
    preco = normalizar_preco(row.get("preco", ""))
    imagem_url = str(row.get("imagem_url", "")).strip() or None
    obs = str(row.get("obs", "")).strip() or None

    # 3a. Parse link
    asin, titulo = parse_amazon_link(link)
    if not asin:
        msg = "erro: link sem ASIN válido"
        print(f"[linha {row_index}] {msg}")
        if not dry_run:
            sheet.update_cell(row_index, 5, msg)
        return
    if not titulo:
        msg = "erro: link sem nome do produto — cole o link completo da barra do navegador"
        print(f"[linha {row_index}] {msg}")
        if not dry_run:
            sheet.update_cell(row_index, 5, msg)
        return

    # 3b. Affiliate link
    link_afiliado = f"https://www.amazon.com.br/dp/{asin}?tag={AFFILIATE_TAG}"
    slug = make_slug(titulo, asin)
    url_pagina = f"{SITE_BASE_URL}/oferta/{slug}"

    # 3c. Gemini with mandatory fallback
    gemini_result = call_gemini(titulo, preco, obs)
    if gemini_result:
        post_whatsapp = gemini_result.get("post_whatsapp", "")
        descricao = gemini_result.get("descricao_pagina", "")
    else:
        fb = fallback_post(titulo, preco, obs, url_pagina)
        post_whatsapp = fb["post_whatsapp"]
        descricao = fb["descricao_pagina"]

    # Substitute placeholder that the prompt leaves for Python to fill
    post_whatsapp = post_whatsapp.replace("{url_pagina}", url_pagina)

    # 3d. Publish to site + commit
    oferta_entry = {
        "slug": slug,
        "titulo": titulo,
        "preco": preco,
        "imagem_url": imagem_url,
        "descricao": descricao,
        "obs": obs,
        "link_afiliado": link_afiliado,
        "data": datetime.now(timezone.utc).isoformat(),
    }
    publish_to_site(oferta_entry, dry_run)
    git_commit_push(slug, dry_run)

    # 3e. Telegram
    send_telegram(post_whatsapp, imagem_url, dry_run)

    # 3f. Update sheet
    if not dry_run:
        sheet.update_cell(row_index, 5, "publicado")
        sheet.update_cell(row_index, 6, post_whatsapp)
        sheet.update_cell(row_index, 7, url_pagina)
    else:
        print(f"[dry-run] Planilha linha {row_index}: status=publicado | url_pagina={url_pagina}")


# ── Sheets connection ─────────────────────────────────────────────────────────

def get_sheet():
    import gspread
    from google.oauth2.service_account import Credentials

    sheet_id = os.environ["SHEET_ID"]
    sa_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    creds = Credentials.from_service_account_info(
        json.loads(sa_json),
        scopes=[
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds).open_by_key(sheet_id).sheet1


# ── Test mode (no credentials required) ──────────────────────────────────────

TEST_ROWS = [
    {
        "link": "https://www.amazon.com.br/Echo-Dot-5a-Geracao-Com-Alexa/dp/B09B8VVHJB/ref=sr_1_1",
        "preco": "299,00",
        "imagem_url": "https://m.media-amazon.com/images/I/71bxvnSdFFL._AC_SL1000_.jpg",
        "obs": "menor preço em 3 meses (Keepa)",
        "status": "",
    },
    {
        "link": "https://www.amazon.com.br/dp/B09TMNWWZF",  # no title slug — deve gerar erro
        "preco": "479,05",
        "imagem_url": "",
        "obs": "",
        "status": "",
    },
]


def run_test(dry_run: bool) -> None:
    print("=== MODO TESTE (sem credenciais) ===\n")
    for i, row in enumerate(TEST_ROWS):
        print(f"--- Linha de teste {i + 1} ---")
        try:
            process_row(row, i + 2, sheet=None, dry_run=dry_run)
        except Exception as exc:
            print(f"[linha {i + 2}] erro inesperado: {exc}", file=sys.stderr)
        print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline de ofertas Amazon")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem publicar nem escrever")
    parser.add_argument("--test", action="store_true", help="Usa linhas de exemplo sem precisar de credenciais")
    parser.add_argument("--link", help="Processa um link avulso em dry-run (não precisa de credenciais)")
    parser.add_argument("--preco", default="0,00", help="Preço para usar com --link (ex: 299,00)")
    parser.add_argument("--obs", default="", help="Observação opcional para usar com --link")
    parser.add_argument("--imagem", default="", help="URL de imagem opcional para usar com --link")
    args = parser.parse_args()

    if args.test:
        run_test(dry_run=True)
        return

    if args.link:
        row = {
            "link": args.link,
            "preco": args.preco,
            "imagem_url": args.imagem,
            "obs": args.obs,
            "status": "",
        }
        print("=== DRY-RUN com link avulso ===\n")
        process_row(row, 2, sheet=None, dry_run=True)
        return

    sheet = get_sheet()
    records = sheet.get_all_records()
    pending = [
        (i + 2, row)
        for i, row in enumerate(records)
        if row.get("status", "").strip().lower() in ("", "novo")
    ]

    if not pending:
        print("Nenhuma linha pendente.")
        return

    print(f"{len(pending)} linha(s) para processar.")
    for row_index, row in pending:
        try:
            process_row(row, row_index, sheet, args.dry_run)
        except Exception as exc:
            msg = f"erro: {exc}"
            print(f"[linha {row_index}] {msg}", file=sys.stderr)
            if not args.dry_run:
                try:
                    sheet.update_cell(row_index, 5, msg[:200])
                except Exception:
                    pass


if __name__ == "__main__":
    main()
