
# ——— Librerías estándar de Python ———
import os
import io
import re
import json
import base64
import logging
import random
import string
import requests
import asyncio
import difflib
import unicodedata
import subprocess
import time
from datetime import datetime, timedelta
from collections import defaultdict
from types import SimpleNamespace
from oauth2client.service_account import ServiceAccountCredentials
# ——— Librerías externas ———
import numpy as np               # ←  déjalo si realmente lo usas
import torch
import nest_asyncio
from PIL import Image
from dotenv import load_dotenv
from transformers import CLIPModel, CLIPProcessor
from torchvision import transforms
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
import gspread
from google.oauth2 import service_account     # ← alias de antes

# ——— Google Cloud & Drive ———
from google.cloud import vision
from google.oauth2.service_account import Credentials   # forma única
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# ——— Telegram ———
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InputMediaPhoto,
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
# ─── Imports y logging ───────────────────────────────────────────────────
import os, io, logging
from fastapi import FastAPI
from googleapiclient.http import MediaIoBaseDownload

logging.basicConfig(level=logging.INFO,
                    format="%(levelname)s: %(message)s")

# ─── Instancia de FastAPI ────────────────────────────────────────────────
api = FastAPI(title="AYA Bot – WhatsApp")
logging.basicConfig(level=logging.DEBUG)

estado_usuario = {}
usuarios_saludo_enviado = set()

# 🔧 Normalizador global de texto (acentos, signos, mayúsculas)
def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("utf-8")
    texto = re.sub(r"[^\w\s]", "", texto)  # elimina signos de puntuación
    return texto.upper().strip()

# ... sigue con procesar_wa(), venom_webhook, etc.

# ─── (Ejemplo) servicio de Drive  ────────────────────────────────────────
def get_drive_service():
    """
    Devuelve un objeto service autenticado para la API de Drive.
    Ajusta según tu implementación real.
    """
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        "service_account.json",
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
 
    return build("drive", "v3", credentials=creds)

def registrar_o_actualizar_lead(data: dict) -> bool:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials

    try:
        logging.info("[LEADS] ⇢ Intentando registrar o actualizar lead...")
        logging.info(f"[LEADS] Datos recibidos:\n{json.dumps(data, indent=2, ensure_ascii=False)}")

        creds_dict = json.loads(os.getenv("GOOGLE_CREDS_JSON"))
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        sheet = client.open("PEDIDOS").worksheet("LEADS")
        telefono = data.get("Teléfono", "").strip()
        fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not telefono:
            logging.warning("[LEADS] ⚠️ Teléfono vacío. No se puede registrar.")
            return False

        registros = sheet.col_values(1)  # Columna A: Teléfono
        logging.info(f"[LEADS] 🔍 Total de registros existentes: {len(registros)}")

        fila_data = [
            telefono,
            data.get("Fecha Registro", fecha),
            data.get("Nombre", ""),
            data.get("Producto", ""),
            data.get("Color", ""),
            data.get("Talla", ""),
            data.get("Correo", ""),
            data.get("Fase", ""),
            data.get("Último Mensaje", ""),
            data.get("Estado", "")
        ]

        if telefono in registros:
            fila_index = registros.index(telefono) + 1
            sheet.update(f"A{fila_index}:J{fila_index}", [fila_data])
            logging.info(f"[LEADS] 🔁 Lead actualizado (fila {fila_index})")
        else:
            sheet.append_row(fila_data)
            logging.info("[LEADS] ✅ Lead registrado por primera vez")

        return True

    except Exception as e:
        logging.exception("[LEADS] ❌ Error registrando o actualizando lead")
        return False

RUTA_MEMORIA_USUARIOS = "/tmp/memoria_usuarios.json"

# 🧠 Cargar memoria persistente
def cargar_memoria_usuario(cid: str) -> dict:
    if os.path.exists(RUTA_MEMORIA_USUARIOS):
        try:
            with open(RUTA_MEMORIA_USUARIOS, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get(cid, {})
        except Exception as e:
            logging.warning(f"⚠️ Error leyendo memoria de usuario: {e}")
    return {}

# 🧠 Guardar clave/valor en memoria persistente
def guardar_memoria_usuario(cid: str, key: str, valor: str):
    os.makedirs("/tmp", exist_ok=True)
    data = {}
    if os.path.exists(RUTA_MEMORIA_USUARIOS):
        try:
            with open(RUTA_MEMORIA_USUARIOS, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logging.warning(f"⚠️ Error leyendo memoria para escribir: {e}")
            data = {}

    if cid not in data:
        data[cid] = {}

    data[cid][key] = valor

    try:
        with open(RUTA_MEMORIA_USUARIOS, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"💾 Memoria actualizada para {cid}: {key} = {valor}")
    except Exception as e:
        logging.error(f"❌ Error escribiendo memoria: {e}")

# 📥 Cargar CIUDADES_DISPONIBLES desde archivo (global)
try:
    with open("/var/data/ciudades/ciudades.json", "r", encoding="utf-8") as f:
        CIUDADES_DISPONIBLES = json.load(f)
    logging.info(f"✅ Se cargaron {len(CIUDADES_DISPONIBLES)} ciudades desde ciudades.json")
except Exception as e:
    logging.warning(f"⚠️ Error al cargar ciudades.json: {e}")
    CIUDADES_DISPONIBLES = []
def guardar_memoria_ciudad_temporal(cid, ciudad):
    ruta_tmp = "/tmp/memoria_ciudades_temp.json"
    try:
        if os.path.exists(ruta_tmp):
            with open(ruta_tmp, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}

        data[cid] = ciudad

        with open(ruta_tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logging.info(f"🧠 Ciudad '{ciudad}' guardada en /tmp para {cid}")
    except Exception as e:
        logging.error(f"❌ Error guardando ciudad temporal: {e}")

# 📍 Recuperar ciudad del cliente desde múltiples fuentes
def get_ciudad_cliente(cid: str, est: dict) -> str:
    """
    Retorna la ciudad del cliente buscando en:
    1. Memoria temporal (/tmp)
    2. Memoria persistente (/tmp/memoria_usuarios.json)
    3. Estado actual en RAM
    """
    try:
        ruta_tmp = "/tmp/memoria_ciudades_temp.json"
        if os.path.exists(ruta_tmp):
            with open(ruta_tmp, "r", encoding="utf-8") as f:
                data_tmp = json.load(f)
            ciudad_tmp = data_tmp.get(cid)
            if ciudad_tmp:
                return ciudad_tmp
    except Exception as e:
        logging.warning(f"⚠️ Error leyendo /tmp ciudad temporal: {e}")

    memoria = cargar_memoria_usuario(cid)
    if memoria.get("ciudad"):
        return memoria["ciudad"]

    return est.get("ciudad")


def descargar_imagen_lengueta():
    """
    Descarga la imagen de ejemplo de lengüeta desde Google Drive.
    Guarda el archivo como /var/data/extra/lengueta_ejemplo.jpg
    """
    try:
        print(">>> descargar_imagen_lengueta() – iniciando")
        service = get_drive_service()
        os.makedirs("/var/data/extra", exist_ok=True)

        archivo = service.files().list(
            q="'1GF3rdTM0t81KRIb6xbQ1uNV4uC4A7LvE' in parents and name = 'lengueta_ejemplo.jpg' and trashed = false",
            fields="files(id, name)",
            pageSize=1
        ).execute().get("files", [])

        if not archivo:
            logging.warning("⚠️ No se encontró 'lengueta_ejemplo.jpg'")
            return

        file_id = archivo[0]["id"]
        destino = "/var/data/extra/lengueta_ejemplo.jpg"

        if os.path.exists(destino):
            logging.info("📦 Imagen de lengüeta ya existe. Omitiendo descarga.")
            return

        logging.info("⬇️ Descargando imagen de lengüeta")
        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        with open(destino, "wb") as f:
            f.write(buffer.getvalue())

        logging.info(f"✅ Imagen guardada en: {destino}")

    except Exception as e:
        logging.error(f"❌ Error descargando imagen de lengüeta: {e}")
def descargar_metodos_pago_drive():
    """
    Descarga la imagen 'metodosdepago.jpeg' desde Google Drive.
    Guarda el archivo como /var/data/extra/metodosdepago.jpeg
    """
    try:
        print(">>> descargar_metodos_pago_drive() – iniciando")
        service = get_drive_service()
        carpeta_id = "1GF3rdTM0t81KRIb6xbQ1uNV4uC4A7LvE"  # misma carpeta que lengüeta
        destino = "/var/data/extra/metodosdepago.jpeg"

        os.makedirs("/var/data/extra", exist_ok=True)

        archivo = service.files().list(
            q=f"'{carpeta_id}' in parents and name = 'metodosdepago.jpeg' and trashed = false",
            fields="files(id, name)",
            pageSize=1
        ).execute().get("files", [])

        if not archivo:
            logging.warning("⚠️ No se encontró 'metodosdepago.jpeg'")
            return

        file_id = archivo[0]["id"]

        if os.path.exists(destino):
            logging.info("📦 Imagen de métodos de pago ya existe. Omitiendo descarga.")
            return

        logging.info("⬇️ Descargando imagen de métodos de pago")
        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        with open(destino, "wb") as f:
            f.write(buffer.getvalue())

        logging.info(f"✅ Imagen guardada en: {destino}")

    except Exception as e:
        logging.error(f"❌ Error descargando 'metodosdepago.jpeg': {e}")

CARPETA_AUDIOS_DRIVE = "1-Htyzy4f8NgjkLJRv5hGZHdTXpRvz5mA"  # Carpeta raíz de “Audios”

def descargar_audios_bienvenida_drive() -> None:
    """
    Descarga audios desde las subcarpetas en Drive:
        BIENVENIDA, CONFIANZA, CONTRAENTREGA, PRECIO, REALIZAR COMPRA,
        CAROS, COSIDOS, CAUCHO → a /var/data/audios/<subcarpeta>

    Siempre vuelve a descargar y sobrescribe.
    Archivos menores a 1 KB se descartan.
    """
    try:
        print(">>> descargar_audios_bienvenida_drive() – iniciando")
        service = get_drive_service()

        carpetas_locales: Dict[str, str] = {
            "BIENVENIDA":        "/var/data/audios/bienvenida",
            "CONFIANZA":         "/var/data/audios/confianza",
            "CONTRAENTREGA":     "/var/data/audios/contraentrega",
            "PRECIO":            "/var/data/audios/precio",
            "REALIZAR COMPRA":   "/var/data/audios/realizar_compra",
            "CAROS":             "/var/data/audios/caros",
            "COSIDOS":           "/var/data/audios/cosidos",
            "CAUCHO":            "/var/data/audios/caucho"
        }

        # Crear carpetas locales si no existen
        for ruta in carpetas_locales.values():
            os.makedirs(ruta, exist_ok=True)

        # Limpiar completamente todas las carpetas locales
        for ruta in carpetas_locales.values():
            for f in os.listdir(ruta):
                p = os.path.join(ruta, f)
                if os.path.isfile(p):
                    os.remove(p)

        # Recorrer cada subcarpeta de Drive
        for nombre_drive, ruta_destino in carpetas_locales.items():
            logging.info(f"📂 Descargando audios de '{nombre_drive}' …")

            sub = service.files().list(
                q=(
                    f"'{CARPETA_AUDIOS_DRIVE}' in parents and "
                    f"name = '{nombre_drive}' and "
                    f"mimeType = 'application/vnd.google-apps.folder' and trashed = false"
                ),
                fields="files(id,name)", pageSize=1
            ).execute().get("files", [])

            if not sub:
                logging.warning(f"❌ No existe la carpeta '{nombre_drive}' en Drive.")
                continue

            sub_id = sub[0]["id"]

            audios = service.files().list(
                q=f"'{sub_id}' in parents and mimeType contains 'audio/' and trashed = false",
                fields="files(id,name)"
            ).execute().get("files", [])

            if not audios:
                logging.warning(f"⚠️ La carpeta '{nombre_drive}' está vacía.")
                continue

            for audio in audios:
                destino = os.path.join(ruta_destino, audio["name"])
                request = service.files().get_media(fileId=audio["id"])

                buffer = io.BytesIO()
                dl = MediaIoBaseDownload(buffer, request)
                done = False
                while not done:
                    _, done = dl.next_chunk()

                if buffer.getbuffer().nbytes < 1024:
                    logging.error(f"❌ Archivo '{audio['name']}' descargado vacío — omitido.")
                    continue

                with open(destino, "wb") as f:
                    f.write(buffer.getvalue())

                logging.info(f"✅ Guardado: {destino}")

        print(">>> descargar_audios_bienvenida_drive() – finalizado")

    except Exception as e:
        print(">>> EXCEPCIÓN en descargar_audios_bienvenida_drive:", e)
        logging.error(f"❌ Error al descargar audios: {e}")

# ─── Descarga de todos los videos de confianza desde Drive ─────────────────────────────
CARPETA_VIDEO_CONFIANZA_DRIVE = "1uX0FXruTXLr2c5SHAc6thlIUMucN1hAA"  # Carpeta 'Video de confianza'

def descargar_video_confianza():
    """
    Descarga todos los archivos .mp4 desde la carpeta 'Video de confianza' en Google Drive.
    Guarda los archivos en /var/data/videos/ sin sobrescribir si ya existen.
    """
    try:
        print(">>> descargar_video_confianza() – iniciando")
        service = get_drive_service()
        os.makedirs("/var/data/videos", exist_ok=True)

        logging.info("📂 [Video Confianza] Iniciando descarga desde Drive…")
        logging.info(f"🆔 Carpeta Drive: {CARPETA_VIDEO_CONFIANZA_DRIVE}")

        # Buscar todos los archivos .mp4 en la carpeta
        archivos = service.files().list(
            q=f"'{CARPETA_VIDEO_CONFIANZA_DRIVE}' in parents and mimeType='video/mp4' and trashed = false",
            fields="files(id, name)",
            pageSize=20
        ).execute().get("files", [])

        if not archivos:
            logging.warning("⚠️ No se encontró ningún video .mp4 en la carpeta de confianza.")
            return

        for archivo in archivos:
            nombre_archivo = archivo["name"]
            ruta_destino = os.path.join("/var/data/videos", nombre_archivo)

            if os.path.exists(ruta_destino):
                logging.info(f"📦 Ya existe: {nombre_archivo} — se omite descarga.")
                continue

            logging.info(f"⬇️ Descargando video: {nombre_archivo}")
            request = service.files().get_media(fileId=archivo["id"])
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)

            done = False
            while not done:
                _, done = downloader.next_chunk()

            with open(ruta_destino, "wb") as f:
                f.write(buffer.getvalue())

            logging.info(f"✅ Video guardado: {ruta_destino}")

        print(">>> descargar_video_confianza() – finalizado")

    except Exception as e:
        print(">>> EXCEPCIÓN en descargar_video_confianza:", e)
        logging.error(f"❌ Error descargando videos de confianza: {e}")


# ─── Carpeta general de Drive donde está el modelos.json ─────────────────────
CARPETA_DRIVE_GENERAL = "1cwq8Nfk603JtP0zpXbNh5qjU7bFwnb8n"  # Carpeta 'Memoria General'

def descargar_memoria_ciudades():
    """
    Descarga el archivo modelos.json desde la carpeta general en Drive.
    Siempre reemplaza el archivo local en /var/data/modelos/modelos.json
    """
    try:
        print(">>> descargar_memoria_modelos() – iniciando")
        service = get_drive_service()
        os.makedirs("/var/data/modelos", exist_ok=True)

        logging.info("📂 [Memoria Modelos] Iniciando descarga desde Drive…")
        logging.info(f"🆔 Carpeta Drive: {CARPETA_DRIVE_GENERAL}")

        archivos = service.files().list(
            q=f"'{CARPETA_DRIVE_GENERAL}' in parents and name = 'modelos.json' and trashed = false",
            fields="files(id, name)",
            pageSize=1
        ).execute().get("files", [])

        if not archivos:
            logging.warning("⚠️ No se encontró 'modelos.json' en la carpeta.")
            return

        archivo = archivos[0]
        ruta_destino = "/var/data/modelos/modelos.json"

        # Siempre descargar y reemplazar
        logging.info(f"⬇️ Descargando y sobrescribiendo: {archivo['name']}")
        request = service.files().get_media(fileId=archivo["id"])
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        with open(ruta_destino, "wb") as f:
            f.write(buffer.getvalue())

        logging.info(f"✅ Archivo guardado: {ruta_destino}")
        print(">>> descargar_memoria_modelos() – finalizado")

    except Exception as e:
        print(">>> EXCEPCIÓN en descargar_memoria_modelos:", e)
        logging.error(f"❌ Error descargando 'modelos.json': {e}")


def descargar_stickers_drive():
    """
    Descarga stickers desde subcarpetas de 'Stickers' en Google Drive.
    Cada subcarpeta (ej: 'Sticker bienvenida') se guarda como prefijo del nombre del archivo.
    Ejemplo: 'Sticker bienvenida/sticker1.webp' → /var/data/stickers/sticker_bienvenida_sticker1.webp
    """
    try:
        print(">>> descargar_stickers_drive() – iniciando")
        service = get_drive_service()
        os.makedirs("/var/data/stickers", exist_ok=True)

        logging.info("📂 [Stickers] Descargando desde subcarpetas temáticas…")
        logging.info(f"🆔 Carpeta raíz: {CARPETA_STICKERS_DRIVE}")

        # Buscar subcarpetas dentro de la carpeta 'Stickers'
        subcarpetas = service.files().list(
            q=f"'{CARPETA_STICKERS_DRIVE}' in parents and mimeType='application/vnd.google-apps.folder' and trashed = false",
            fields="files(id, name)"
        ).execute().get("files", [])

        for sub in subcarpetas:
            nombre_subcarpeta = sub["name"].lower().replace(" ", "_")  # Ej: 'Envio Gratis' → 'envio_gratis'
            id_subcarpeta = sub["id"]

            logging.info(f"🔎 Buscando en subcarpeta: {nombre_subcarpeta}")

            archivos = service.files().list(
                q=f"'{id_subcarpeta}' in parents and mimeType='image/webp' and trashed = false",
                fields="files(id, name)"
            ).execute().get("files", [])

            for archivo in archivos:
                nombre_archivo_original = archivo["name"]
                nombre_archivo_local = f"{nombre_subcarpeta}_{nombre_archivo_original}"
                ruta_destino = os.path.join("/var/data/stickers", nombre_archivo_local)

                if os.path.exists(ruta_destino):
                    logging.info(f"📦 Ya existe: {nombre_archivo_local} — omitiendo descarga.")
                    continue

                logging.info(f"⬇️ Descargando sticker: {nombre_archivo_local}")
                request = service.files().get_media(fileId=archivo["id"])
                buffer = io.BytesIO()
                downloader = MediaIoBaseDownload(buffer, request)

                done = False
                while not done:
                    _, done = downloader.next_chunk()

                with open(ruta_destino, "wb") as f:
                    f.write(buffer.getvalue())

                logging.info(f"✅ Guardado: {ruta_destino}")

        logging.info("🎉 Stickers descargados con éxito.")
        print(">>> descargar_stickers_drive() – finalizado")

    except Exception as e:
        print(">>> EXCEPCIÓN en descargar_stickers_drive:", e)
        logging.error(f"❌ Error al descargar stickers: {e}")



# ─── Descarga de imágenes de catálogo desde Drive ───────────────────────
CARPETA_CATALOGO_DRIVE = "1_liZvzlyNj2P8koFU4fgFp5X8icUh_ZA"  # Carpeta principal

def descargar_imagenes_catalogo():
    """
    Descarga una imagen por subcarpeta de la carpeta 'Envio de Imagenes Catalogo'.
    Guarda las imágenes en /var/data/modelos_video/. No repite si ya existen.
    """
    try:
        print(">>> descargar_imagenes_catalogo() – iniciando")
        service = get_drive_service()
        os.makedirs("/var/data/modelos_video", exist_ok=True)

        logging.info("📂 [Modelos Catálogo] Descargando imágenes desde Drive…")
        logging.info(f"🆔 Carpeta raíz: {CARPETA_CATALOGO_DRIVE}")

        # Obtener todas las subcarpetas (cada modelo-color)
        subcarpetas = service.files().list(
            q=f"'{CARPETA_CATALOGO_DRIVE}' in parents and mimeType='application/vnd.google-apps.folder' and trashed = false",
            fields="files(id, name)"
        ).execute().get("files", [])

        for carpeta in subcarpetas:
            nombre_carpeta = carpeta["name"]
            id_carpeta = carpeta["id"]

            logging.info(f"🔎 Buscando imagen en subcarpeta: {nombre_carpeta}")

            # Buscar una imagen dentro de la subcarpeta
            archivos = service.files().list(
                q=f"'{id_carpeta}' in parents and mimeType contains 'image/' and trashed = false",
                fields="files(id, name)",
                pageSize=1
            ).execute().get("files", [])

            if not archivos:
                logging.warning(f"⚠️ Sin imágenes en {nombre_carpeta}")
                continue

            imagen = archivos[0]
            nombre_archivo = f"{nombre_carpeta}.jpg"
            ruta_destino = os.path.join("/var/data/modelos_video", nombre_archivo)

            if os.path.exists(ruta_destino):
                logging.info(f"📦 Ya existe: {nombre_archivo} — omitiendo descarga.")
                continue

            logging.info(f"⬇️ Descargando imagen: {nombre_archivo}")
            request = service.files().get_media(fileId=imagen["id"])
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)

            done = False
            while not done:
                _, done = downloader.next_chunk()

            with open(ruta_destino, "wb") as f:
                f.write(buffer.getvalue())

            logging.info(f"✅ Imagen guardada: {ruta_destino}")

        logging.info("🎉 Descarga de imágenes de catálogo completada.")
        print(">>> descargar_imagenes_catalogo() – finalizado")

    except Exception as e:
        print(">>> EXCEPCIÓN en descargar_imagenes_catalogo:", e)
        logging.error(f"❌ Error descargando imágenes de catálogo: {e}")

# ─── Descarga de videos desde Drive ──────────────────────────────────────
CARPETA_VIDEOS_DRIVE = "1bFJAuuW8JYWDMT74bGqQC6qBynZ_olBU"   # ⬅️ tu carpeta

def descargar_videos_drive():
    """
    Descarga todos los .mp4 de la carpeta de Drive a /var/data/videos.
    Solo baja los que aún no existan. Deja trazas en logs y prints.
    """
    try:
        print(">>> descargar_videos_drive() – iniciando")
        service = get_drive_service()
        os.makedirs("/var/data/videos", exist_ok=True)

        logging.info("📂 [Videos] Iniciando descarga desde Drive…")
        logging.info(f"🆔 Carpeta Drive: {CARPETA_VIDEOS_DRIVE}")

        resultados = service.files().list(
            q=f"'{CARPETA_VIDEOS_DRIVE}' in parents and mimeType='video/mp4'",
            fields="files(id, name, mimeType)"
        ).execute()

        archivos = resultados.get("files", [])
        logging.info(f"🔎 {len(archivos)} archivo(s) .mp4 encontrados en la carpeta.")
        print(">>> Encontrados en Drive:", [f['name'] for f in archivos])

        for archivo in archivos:
            nombre = archivo["name"]
            id_video = archivo["id"]
            ruta_destino = os.path.join("/var/data/videos", nombre)

            if os.path.exists(ruta_destino):
                logging.info(f"📦 Ya existe: {nombre} — se omite descarga.")
                continue

            logging.info(f"⬇️ Descargando {nombre}…")
            request = service.files().get_media(fileId=id_video)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)

            done = False
            while not done:
                _, done = downloader.next_chunk()

            with open(ruta_destino, "wb") as f:
                f.write(buffer.getvalue())

            logging.info(f"✅ Guardado en {ruta_destino}")

        logging.info("🎉 Descarga de videos completada.")
        print(">>> descargar_videos_drive() – finalizado")

    except Exception as e:
        print(">>> EXCEPCIÓN en descargar_videos_drive:", e)
        logging.error(f"❌ Error descargando videos desde Drive: {e}")

# ─── Hook de arranque de FastAPI ─────────────────────────────────────────
@api.on_event("startup")
async def startup_download_videos():
    descargar_videos_drive()

# ─── Resto de tu código (rutas, responder(), etc.) ───────────────────────
# …

# 🧠 Anti-duplicados por mensaje ID
ultimo_msg = {}

# ID del archivo clientes.json en Google Drive
CLIENTES_JSON_FILE_ID = "13euT2mtVwO4qWjhiWNAo-0DZFPTmjy0X"
DURACION_MEMORIA_DIAS = 30

def get_drive_service():
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds)

def descargar_memoria_clientes():
    service = get_drive_service()
    request = service.files().get_media(fileId=CLIENTES_JSON_FILE_ID)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()

    fh.seek(0)
    try:
        memoria = json.load(fh)
    except json.JSONDecodeError:
        memoria = {}

    return memoria

def subir_memoria_clientes(memoria_dict):
    service = get_drive_service()

    # 🔁 Primero escribe el JSON como texto
    str_io = io.StringIO()
    json.dump(memoria_dict, str_io, ensure_ascii=False, indent=4)
    str_io.seek(0)

    # 🔁 Luego lo conviertes a bytes
    byte_io = io.BytesIO(str_io.read().encode("utf-8"))
    byte_io.seek(0)

    media_body = MediaIoBaseUpload(byte_io, mimetype='application/json', resumable=True)

    service.files().update(
        fileId=CLIENTES_JSON_FILE_ID,
        media_body=media_body
    ).execute()


def limpiar_memoria_vencida(memoria):
    ahora = datetime.now()
    nueva_memoria = {}
    for numero, datos in memoria.items():
        fecha = datetime.fromisoformat(datos.get("fecha", "2000-01-01"))
        if ahora - fecha <= timedelta(days=DURACION_MEMORIA_DIAS):
            nueva_memoria[numero] = datos
    return nueva_memoria

def actualizar_cliente(numero, nuevos_datos):
    memoria = descargar_memoria_clientes()
    memoria = limpiar_memoria_vencida(memoria)
    cliente = memoria.get(numero, {})
    cliente.update(nuevos_datos)
    cliente["fecha"] = datetime.now().isoformat()
    memoria[numero] = cliente
    subir_memoria_clientes(memoria)

def obtener_datos_cliente(numero):
    memoria = descargar_memoria_clientes()
    memoria = limpiar_memoria_vencida(memoria)
    return memoria.get(numero)

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def generar_audio_openai(texto: str,
                               nombre_archivo: str = "respuesta.mp3",
                               voice: str = "nova") -> str | None:
    try:
        logging.debug("🔧 generar_audio_openai() inicia…")
        os.makedirs("temp", exist_ok=True)
        ruta = os.path.join("temp", nombre_archivo)

        # 1️⃣  Solicitud TTS
        resp = await client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=texto
        )

        # 2️⃣  Obtener los bytes según el método disponible
        if hasattr(resp, "aread"):                       # SDK async v1
            audio_bytes = await resp.aread()
        elif callable(getattr(resp, "read", None)):      # SDK sync v1 (pero obj devuelto aquí)
            audio_bytes = resp.read()
        else:                                            # Fallback
            audio_bytes = resp  # asume bytes directos

        # 3️⃣  Guardar
        with open(ruta, "wb") as f:
            f.write(audio_bytes)

        logging.info(f"✅ Audio guardado: {ruta}")
        return ruta

    except Exception as e:
        logging.error(f"❌ Error generando audio: {e}")
        return None


async def detectar_ciudad(texto: str, client) -> str:
    """
    Usa GPT-4o para detectar si hay una ciudad de Colombia en el mensaje.
    Devuelve el nombre de la ciudad si la hay, o una cadena vacía si no.
    """
    prompt = (
        f"El usuario dijo: '{texto}'. ¿Está mencionando alguna ciudad de Colombia relacionada con envío?"
        " Si sí, responde solo con el nombre de la ciudad (como 'Medellín', 'Pereira', etc.). "
        "Si no, responde únicamente con: 'ninguna'."
    )

    try:
        respuesta = await client.chat.completions.create(
            model="gpt-4o",  # ✅ modelo mini actual
            messages=[
                {"role": "system", "content": "Responde solo con el nombre de la ciudad o 'ninguna'."},
                {"role": "user", "content": prompt}
            ]
        )
        ciudad = respuesta.choices[0].message.content.strip()
        return ciudad if ciudad.lower() != "ninguna" else ""

    except Exception as e:
        logging.error(f"❌ Error en detectar_ciudad(): {e}")
        return ""




# CLIP: cargar modelo una sola vez
clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
clip_model.eval()
clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

# Inicializa dotenv
load_dotenv()

# FastAPI instance
api = FastAPI()

from fastapi.responses import JSONResponse

@api.get("/ver_embeddings")
async def ver_embeddings():
    try:
        with open("var/data/embeddings.json", "r") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {"error": "Estructura inválida en embeddings.json"}

        resumen = {
            nombre: len(v) if isinstance(v, list) else 0
            for nombre, v in data.items()
        }

        return {
            "total_modelos": len(resumen),
            "modelos": resumen  # ejemplo: {"DS_277_NEGRO": 4, "SUPER_BLANCO": 3}
        }

    except Exception as e:
        logging.error(f"[EMBEDDINGS] Error al leer embeddings.json: {e}")
        return {"error": str(e)}

# ✅ Desde el mismo JSON base
creds_info = json.loads(os.environ["GOOGLE_CREDS_JSON"])

# DRIVE → requiere scope explícito
drive_creds = service_account.Credentials.from_service_account_info(
    creds_info,
    scopes=["https://www.googleapis.com/auth/drive.readonly"]
)

# VISION → no requiere scope personalizado
vision_creds = service_account.Credentials.from_service_account_info(creds_info)

# Servicios
drive_service = build("drive", "v3", credentials=drive_creds)
vision_client = vision.ImageAnnotatorClient(credentials=vision_creds)
# 🖼️ Convertir base64 a imagen PIL
def decodificar_imagen_base64(base64_str: str) -> Image.Image:
    data = base64.b64decode(base64_str + "===")
    return Image.open(io.BytesIO(data)).convert("RGB")

# 🧠 Embedding de imagen con CLIP (local, sin OpenAI)
def generar_embedding_imagen(img: Image.Image) -> np.ndarray:
    inputs = clip_processor(images=img, return_tensors="pt")
    with torch.no_grad():
        vec = clip_model.get_image_features(**inputs)[0]
    return vec.cpu().numpy()  # → ndarray de shape (512,)
import torch
import torch.nn.functional as F

# 🔍 Comparar embedding de la imagen con los embeddings precargados
def comparar_embeddings_clip(embedding_cliente: np.ndarray, embeddings_dict: dict):
    import torch.nn.functional as F
    embedding_cliente = torch.tensor(embedding_cliente)
    embedding_cliente = F.normalize(embedding_cliente, dim=-1)

    mejores = []

    for nombre_modelo, lista_vecs in embeddings_dict.items():
        try:
            max_sim = 0.0
            for vec in lista_vecs:
                emb_modelo = torch.tensor(vec)
                emb_modelo = F.normalize(emb_modelo, dim=-1)
                sim = torch.dot(embedding_cliente, emb_modelo).item()
                if sim > max_sim:
                    max_sim = sim
            mejores.append((nombre_modelo, max_sim))
        except Exception as e:
            print(f"[ERROR EMBEDDING] {nombre_modelo}: {e}")

    if not mejores:
        return None, 0.0

    mejores.sort(key=lambda x: x[1], reverse=True)
    mejor_modelo, mejor_score = mejores[0]

    return mejor_modelo, mejor_score

# ————————————————————————————————————————————————————————————————
# 🔍 Comparar imagen del cliente con base de modelos


# ──────────────────────────────────────────────────────────
# 🔧  Helper: normaliza y verifica que el vector tenga 512 dim
def _a_unit(vec) -> np.ndarray:
    arr = np.asarray(vec, dtype=float).reshape(-1)
    if arr.size != 512:
        raise ValueError(f"Vector tamaño {arr.size} ≠ 512")
    n = np.linalg.norm(arr)
    if n == 0:
        raise ValueError("Vector con norma 0")
    return arr / n

# ──────────────────────────────────────────────────────────
# 🔍  Detectar modelo con CLIP
async def identificar_modelo_desde_imagen(base64_img: str) -> str:
    logging.debug("🧠 [CLIP] Iniciando identificación de modelo...")

    try:
        # 1️⃣ Cargar y sanitizar embeddings
        base = cargar_embeddings_desde_cache()
        embeddings: dict[str, list[list[float]]] = {}
        corruptos = []

        for modelo, vecs in base.items():
            if isinstance(vecs, list):
                if len(vecs) == 512 and all(isinstance(x, (int, float)) for x in vecs):
                    embeddings[modelo] = [vecs]
                else:
                    limpios = [v for v in vecs if isinstance(v, list) and len(v) == 512]
                    if limpios:
                        embeddings[modelo] = limpios
                    else:
                        corruptos.append((modelo, "sin_vectores_validos"))
            else:
                corruptos.append((modelo, "no_lista"))

        if corruptos:
            logging.warning(f"[CLIP] ⚠️ Embeddings corruptos filtrados: {corruptos[:5]} (total {len(corruptos)})")
        logging.info(f"[CLIP] ✅ Embeddings listos: {len(embeddings)} modelos válidos")

        # 2️⃣ Procesar imagen del cliente
        img_pil = decodificar_imagen_base64(base64_img)

        # 🧪 INFO para verificar si la imagen está comprimida
        logging.info(f"[IMG] Formato: {img_pil.format}")
        logging.info(f"[IMG] Tamaño: {img_pil.size} px")
        logging.info(f"[IMG] Modo de color: {img_pil.mode}")
        logging.info(f"[IMG] Bytes base64 recibidos: {len(base64_img)}")
        logging.info(f"[IMG] Tamaño estimado en bytes: {(len(base64_img) * 3) // 4} bytes aprox")

        emb_cliente = _a_unit(generar_embedding_imagen(img_pil))

        # 3️⃣ Buscar la mejor coincidencia
        mejor_sim, mejor_modelo = 0.0, None
        for modelo, lista in embeddings.items():
            logging.debug(f"[CLIP] Comparando contra modelo: {modelo}")
            for idx, emb_ref in enumerate(lista):
                try:
                    arr_ref = _a_unit(emb_ref)
                    if arr_ref.shape != (512,):
                        logging.warning(f"[CLIP] ⚠️ Shape inválido en {modelo}[{idx}]: {arr_ref.shape}")
                        continue

                    sim = float((emb_cliente * arr_ref).sum())
                    logging.debug(f"[CLIP] Similitud con {modelo}[{idx}]: {sim:.4f}")

                    if sim > mejor_sim:
                        mejor_sim, mejor_modelo = sim, modelo
                        logging.info(f"[CLIP] 🆕 Mejor modelo hasta ahora: {modelo} (sim={sim:.4f})")

                except Exception as err:
                    logging.warning(f"[CLIP] ⚠️ Error comparando con {modelo}: {err}")
                    continue

        logging.info(f"🎯 [CLIP] Coincidencia final: {mejor_modelo} (sim={mejor_sim:.4f})")

        if mejor_modelo and mejor_sim >= 0.85:
            return f"✅ La imagen coincide con *{mejor_modelo}*"
        else:
            return "❌ No pude identificar claramente el modelo. ¿Puedes enviar otra foto?"

    except Exception as e:
        logging.exception(f"[CLIP] ❌ Error general:")
        return "⚠️ Ocurrió un problema analizando la imagen."



DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]



    # ───────────────────────────────────────

def convertir_palabras_a_numero(texto):  
    mapa = {
        "cero": "0", "uno": "1", "una": "1", "dos": "2", "tres": "3", "cuatro": "4",
        "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9",
        "diez": "10", "once": "11", "doce": "12", "trece": "13", "catorce": "14",
        "quince": "15", "dieciséis": "16", "diecisiete": "17", "dieciocho": "18", "diecinueve": "19",
        "veinte": "20", "treinta": "30", "cuarenta": "40", "cincuenta": "50",
        "sesenta": "60", "setenta": "70", "ochenta": "80", "noventa": "90"
    }

    texto = texto.lower().replace("y", " ")  # ejemplo: "treinta y nueve" → "treinta nueve"
    partes = texto.split()
    numero = ""

    for palabra in partes:
        if palabra in mapa:
            numero += mapa[palabra]
        elif palabra.isdigit():
            numero += palabra

    return numero if numero else None

import difflib
import re
import unicodedata

def normalize(texto: str) -> str:
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode("utf-8")
    texto = re.sub(r'[^\w\s]', '', texto)  # quita signos de puntuación
    return texto

def menciona_catalogo(texto: str) -> bool:
    texto = normalize(texto)

    # Frases que deberían activar el catálogo
    claves_exactas = [
        "catalogo", "ver catalogo", "mostrar catalogo", "quiero ver",
        "ver productos", "mostrar productos", "ver lo que tienes",
        "ver tenis", "muestrame", "envieme fotos",
        "que estilos tiene", "no tengo imagenes", "tienes imagenes",
        "mandame el catalogo", "quiero ver modelos", "ver referencias",
        "quiero referencias", "muestrame los modelos", "que modelos tienes",
        "que modelos hay", "envielas", "mandame fotos", "mandame imagenes",
        "envielas usted", "quiero ver imagenes", "tenis que tienes",
        "que hay", "quiero ver los pares", "muestra los tenis",
        "cuales modelos tienes", "mande fotos", "muestrame los pares",
        "ver opciones", "tienes fotos", "ver modelos disponibles",
        "fotos de los modelos", "tienes mas fotos", "mostrar opciones",
        "tienes modelos", "muestrame opciones"
    ]

    # Variantes mal escritas o con errores frecuentes
    claves_con_errores = [
        "catlogo", "katalogo", "catalogoo", "ver katalago", "mostar catalogo",
        "ber catalogo", "quiero bber", "mandame katalago", "quero ver modelos",
        "quiero bel modelos", "kiero bel", "mandame modeloss", "ver referensias",
        "enseñame loq tienes", "fotos modelos", "mandar catalogo", "ver modeloss",
        "tenes imagenes", "imagenes de modelos", "enviar fotos", "mostrar pares"
    ]

    todas = claves_exactas + claves_con_errores

    # Coincidencia exacta en substrings normalizados
    for fr in todas:
        if fr in texto:
            return True

    # Coincidencias similares (difusas)
    for frase in todas:
        similares = difflib.get_close_matches(texto, [frase], n=1, cutoff=0.82)
        if similares:
            return True

    return False



# ——— VARIABLES DE ENTORNO ——————————————————————————————————————————————
OPENAI_API_KEY        = os.environ["OPENAI_API_KEY"]
NOMBRE_NEGOCIO        = os.environ.get("NOMBRE_NEGOCIO", "X100🔥👟")
URL_SHEETS_INVENTARIO = os.environ["URL_SHEETS_INVENTARIO"]
URL_SHEETS_PEDIDOS    = os.environ["URL_SHEETS_PEDIDOS"]
EMAIL_DEVOLUCIONES    = os.environ["EMAIL_DEVOLUCIONES"]
EMAIL_JEFE            = os.environ["EMAIL_JEFE"]
SMTP_SERVER           = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT             = int(os.environ.get("SMTP_PORT", 587))
EMAIL_REMITENTE       = os.environ.get("EMAIL_REMITENTE")
EMAIL_PASSWORD        = os.environ.get("EMAIL_PASSWORD")
import unicodedata
import re

def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("utf-8")
    return texto.upper()

def clasificar_saludo(texto: str) -> str:
    texto = normalizar(texto)

    # 🛒 Detectar intención de compra
    if any(p in texto for p in [
        "REALIZAR UNA COMPRA", "COMO REALIZO UNA COMPRA", "HACER UNA COMPRA", 
        "ORDENAR", "QUIERO COMPRAR", "QUIERO UNO", "LO QUIERO"
    ]):
        return "comprar"

    # 💰 Detectar si habla de precio (con o sin signo de interrogación)
    if any(p in texto for p in ["PRECIO", "CUANTO VALE", "VALE", "VALEN", "CUESTA", "COSTO", "COST"]):
        return "precio"

    return "general"

async def enviar_welcome_venom(cid: str, tipo: str = "general"):
    try:
        if tipo == "precio":
            audio_path = "/var/data/audios/precio/precio.mp3"
        elif tipo == "comprar":
            audio_path = "/var/data/audios/realizar_compra/compra.mp3"
        else:
            audio_path = "/var/data/audios/bienvenida/bienvenida1.mp3"

        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"❌ No se encontró el archivo: {audio_path}")

        with open(audio_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
            b64_final = f"data:audio/mpeg;base64,{b64}"

        return {
            "type": "multi",
            "messages": [
                {
                    "type": "audio",
                    "base64": b64_final,
                    "mimetype": "audio/mpeg",
                    "filename": os.path.basename(audio_path),
                    "text": "🎧 Escucha este audio de bienvenida."
                },
                {
                    "type": "text",
                    "text": (
                        "👇🏻 *AQUÍ ESTÁ EL CATÁLOGO* 🆕\n"
                        "Sigue este enlace para ver la última colección 👟 X💯:\n"
                        "https://wa.me/c/573007607245"
                    ),
                    "parse_mode": "Markdown"
                },
                {
                    "type": "text",
                    "text": (
                        "🙋‍♂️ Hola, dime tu *nombre* y desde qué *ciudad* nos escribes 🏙️✍️ "
                        "para darte una asesoría más personalizada 💬😊"
                    ),
                    "parse_mode": "Markdown"
                }
            ]
        }

    except Exception as e:
        logging.error(f"❌ Error al preparar audio bienvenida: {e}")
        return {
            "type": "text",
            "text": "❌ No logré enviarte el audio de bienvenida. Intenta más tarde."
        }






CATALOG_LINK = "https://wa.me/c/573007607245"

def fase_valida(fase: str) -> bool:
    fases_validas = [
        "esperando_color",
        "esperando_talla",
        "esperando_nombre",
        "esperando_telefono",
        "esperando_correo",
        "esperando_direccion",
        "esperando_comprobante",
        "imagen_detectada",
        "resumen_compra"
    ]
    return fase in fases_validas


def enviar_correo(dest, subj, body):
    logging.info(f"[EMAIL STUB] To: {dest}\nSubject: {subj}\n{body}")

def enviar_correo_con_adjunto(dest, subj, body, adj):
    logging.info(f"[EMAIL STUB] To: {dest}\nSubject: {subj}\n{body}\n[Adj: {adj}]")


from datetime import datetime, timedelta

# Variables de caché
_carpetas_cache = None
_ultima_actualizacion = None

def listar_carpetas_drive():
    """
    Lista los nombres de carpetas en Google Drive dentro de una carpeta raíz.
    Usa caché para evitar llamadas innecesarias durante 10 minutos.
    """
    global _carpetas_cache, _ultima_actualizacion
    ahora = datetime.utcnow()

    if _carpetas_cache is not None and _ultima_actualizacion is not None:
        if (ahora - _ultima_actualizacion) < timedelta(minutes=10):
            return _carpetas_cache  # Devuelve caché si aún es válida

    # Si no hay cache o expiró, recargar desde Drive
    from googleapiclient.discovery import build
    import os, json
    from google.oauth2 import service_account

    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_info(
        json.loads(os.getenv("GOOGLE_CREDS_JSON")), scopes=SCOPES
    )

    service = build('drive', 'v3', credentials=creds)
    folder_id = '1OXHjSG82RO9KGkNIZIRVusFpFhZlujQE'

    carpetas = []
    page_token = None
    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            spaces='drive',
            fields='nextPageToken, files(id, name)',
            pageToken=page_token
        ).execute()

        for file in response.get('files', []):
            carpetas.append(file['name'])

        page_token = response.get('nextPageToken', None)
        if page_token is None:
            break

    # Guardar resultado en caché
    _carpetas_cache = carpetas
    _ultima_actualizacion = ahora

    return carpetas


def detectar_modelo_color(texto: str, carpetas_drive: list) -> dict:
    """
    Detecta modelo y color desde texto OCR comparando con nombres de carpetas.
    Ejemplo carpeta: DS_305_VERDE LIMON
    """
    import re
    import unicodedata

    # Normaliza texto
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("utf-8").upper()
    texto = texto.replace("-", " ").replace("_", " ")

    for carpeta in carpetas_drive:
        nombre = carpeta.upper().replace("_", " ")  # Ej: DS 305 VERDE LIMON
        partes = nombre.split()

        if len(partes) >= 3 and partes[0] == "DS":
            modelo = partes[1]
            color = " ".join(partes[2:])

            # Requiere que el modelo esté presente exacto
            if f"DS {modelo}" in texto or f"DS{modelo}" in texto:
                # Color con coincidencia suave
                color_encontrado = any(pal in texto for pal in color.split())
                if color_encontrado:
                    return {
                        "modelo": modelo,
                        "color": color,
                        "marca": "DS",
                        "type": "text",
                        "text": f"✅ Perfecto, tomaremos *DS {modelo}* color *{color}*.\n📸 Para confirmar la talla exacta, envíame una foto de la *lengüeta interna* de tus tenis actuales 👟."
                    }

    return None



def extraer_texto_comprobante(path: str) -> str:
    try:
        logging.info(f"[OCR] 🚀 Iniciando OCR con Google Vision para: {path}")

        # 1️⃣ Cargar credenciales
        creds_raw = os.environ.get("GOOGLE_CREDS_JSON")
        if not creds_raw:
            logging.error("[OCR] ❌ GOOGLE_CREDS_JSON no está definido en las variables de entorno.")
            return ""

        credentials = service_account.Credentials.from_service_account_info(json.loads(creds_raw))
        logging.info("[OCR] ✅ Credenciales cargadas correctamente")

        # 2️⃣ Crear cliente
        client = vision.ImageAnnotatorClient(credentials=credentials)

        # 3️⃣ Leer imagen
        with io.open(path, "rb") as image_file:
            content = image_file.read()
        if not content:
            logging.error("[OCR] ❌ La imagen está vacía.")
            return ""

        # 🔍 NUEVO: Detalle técnico de la imagen recibida
        try:
            img = Image.open(path)
            logging.info(f"[OCR] 🖼️ Imagen cargada: {path}")
            logging.info(f"[OCR] 🔍 Formato: {img.format}")
            logging.info(f"[OCR] 📐 Tamaño: {img.size}")
            logging.info(f"[OCR] 🎨 Modo de color: {img.mode}")
        except Exception as e:
            logging.error(f"[OCR] ❌ No pude abrir la imagen con PIL para inspección: {e}")

        # 4️⃣ Enviar a Google Vision
        image = vision.Image(content=content)
        logging.info("[OCR] 📤 Enviando imagen a Google Vision API (text_detection)...")
        response = client.text_detection(image=image)
        logging.info("[OCR] 📥 Respuesta recibida de Vision API")

        # 5️⃣ Validar errores de respuesta
        if response.error.message:
            logging.error(f"[OCR ERROR] ❌ Error de Vision API: {response.error.message}")
            return ""

        # 6️⃣ Extraer texto
        texts = response.text_annotations
        if not texts:
            logging.warning("[OCR] ⚠️ No se detectó texto (lista vacía).")
            return ""

        texto = texts[0].description.strip()
        if not texto:
            logging.warning("[OCR] ⚠️ Se recibió texto vacío.")
            return ""

        # 7️⃣ Mostrar texto línea por línea
        logging.info("[OCR] ✅ Texto extraído correctamente. Mostrando líneas:")
        for i, linea in enumerate(texto.splitlines()):
            logging.info(f"[OCR LINEA {i}] → {repr(linea)}")

        logging.info(f"[OCR] 🟢 Éxito: Se extrajo texto con {len(texto.split())} palabras y {len(texto)} caracteres.")
        return texto

    except Exception as e:
        logging.exception("[OCR] ❌ Excepción crítica ejecutando OCR")
        return ""

def es_comprobante_valido(texto: str) -> bool:
    logging.info("[OCR DEBUG] 🔎 Iniciando validación del texto extraído")

    # Mostrar texto crudo completo
    logging.info("[OCR DEBUG] Texto crudo completo:\n" + texto)

    # Mostrar línea por línea con representación exacta
    for i, linea in enumerate(texto.splitlines()):
        logging.info(f"[OCR DEBUG] Línea {i}: {repr(linea)}")

    # Normalizar texto
    texto_normalizado = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("utf-8")
    texto_normalizado = texto_normalizado.lower()
    texto_normalizado = re.sub(r"[^\w\s]", "", texto_normalizado)

    logging.info("[OCR DEBUG] Texto normalizado:\n" + texto_normalizado)

    # Palabras clave aceptadas
    claves = [
        "pago exitoso",
        "transferencia exitosa",
        "comprobante",
        "Datos de la transferencia",
        "pago aprobado",
        "transferencia realizada"
    ]

    for clave in claves:
        if clave in texto_normalizado:
            logging.info(f"[OCR DEBUG] ✅ Coincidencia encontrada: '{clave}'")
            return True

    logging.warning("[OCR DEBUG] ❌ No se encontró ninguna clave válida en el texto extraído.")
    return False

# ——— UTILIDADES DE INVENTARIO —————————————————————————————————————————
estado_usuario: dict[int, dict] = {}
inventario_cache = None

def menciona_imagen(texto: str) -> bool:
    texto = normalize(texto)
    claves = [
        "foto", "imagen", "pantallazo", "screenshot", "captura",
        "tengo una foto", "te paso la imagen", "imagen del modelo",
        "screen", "de instagram", "vi en insta", "historia de insta",
        "la tengo guardada", "foto del tenis", "foto del zapato"
    ]
    return any(palabra in texto for palabra in claves)

def normalize(text) -> str:
    s = "" if text is None else str(text)
    t = unicodedata.normalize('NFKD', s.strip().lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch))

CONVERSION_TALLAS = {
    "usa": {
        "6": "38", "6.5": "38.5", "7": "39", "7.5": "39.5",
        "8": "40", "8.5": "40.5", "9": "41", "9.5": "41.5",
        "10": "42", "10.5": "43", "11": "44", "11.5": "44.5",
        "12": "45", "12.5": "45.5", "13": "46"
    },
    "euro": {
        "38": "38", "38.5": "38.5", "39": "39", "39.5": "39.5",
        "40": "40", "40.5": "40.5", "41": "41", "41.5": "41.5",
        "42": "42", "43": "43", "44": "44", "44.5": "44.5",
        "45": "45", "45.5": "45.5", "46": "46"
    },
    "colombia": {
        "38": "38", "38.5": "38.5", "39": "39", "39.5": "39.5",
        "40": "40", "40.5": "40.5", "41": "41", "41.5": "41.5",
        "42": "42", "43": "43", "44": "44", "44.5": "44.5",
        "45": "45", "45.5": "45.5", "46": "46"
    }
}
def detectar_talla(texto_usuario: str, tallas_disponibles: list[str]) -> str | None:
    texto = normalize(texto_usuario)

    # Reemplazos comunes para tallas con medio punto
    reemplazos = {
        "seis y medio": "6.5", "7 y medio": "7.5", "ocho y medio": "8.5", "nueve y medio": "9.5",
        "diez y medio": "10.5", "once y medio": "11.5", "doce y medio": "12.5",

        "6 y 1/2": "6.5", "7 y 1/2": "7.5", "8 y 1/2": "8.5", "9 y 1/2": "9.5",
        "10 y 1/2": "10.5", "11 y 1/2": "11.5", "12 y 1/2": "12.5",

        "seis punto cinco": "6.5", "siete punto cinco": "7.5", "ocho punto cinco": "8.5",
        "nueve punto cinco": "9.5", "diez punto cinco": "10.5", "once punto cinco": "11.5", "doce punto cinco": "12.5",

        "6.5": "6.5", "7.5": "7.5", "8.5": "8.5", "9.5": "9.5", "10.5": "10.5",
        "11.5": "11.5", "12.5": "12.5", "13": "13"
    }

    for k, v in reemplazos.items():
        if k in texto:
            texto = texto.replace(k, v)

    # Sistema
    if "usa" in texto:
        sistema = "usa"
    elif "euro" in texto or "europea" in texto:
        sistema = "euro"
    elif "colomb" in texto:
        sistema = "colombia"
    else:
        sistema = None

    # Extrae números incluyendo decimales (6.5, 10.5, etc)
    numeros = re.findall(r"\d+(?:\.\d+)?", texto)

    if not numeros:
        return None

    for num in numeros:
        if sistema:
            talla_estandar = CONVERSION_TALLAS.get(sistema, {}).get(num)
            if talla_estandar and talla_estandar in tallas_disponibles:
                return talla_estandar
        else:
            if num in tallas_disponibles:
                return num

    return None

def reset_estado(cid: int):
    estado_usuario[cid] = {
        "fase": "inicio",
        "marca": None,
        "modelo": None,
        "color": None,
        "talla": None,
        "nombre": None,
        "correo": None,
        "telefono": None,
        "ciudad": None,
        "provincia": None,
        "direccion": None,
        "referencia": None,
        "resumen": None,
        "sale_id": None,
        "welcome_enviado": cid in usuarios_saludo_enviado  # ← No se borra nunca si ya lo recibió
    }


def menu_botones(opts: list[str]):
    return ReplyKeyboardMarkup([[KeyboardButton(o)] for o in opts], resize_keyboard=True)

def obtener_inventario() -> list[dict]:
    global inventario_cache
    if inventario_cache is None:
        try:
            inventario_cache = requests.get(URL_SHEETS_INVENTARIO).json()
        except:
            inventario_cache = []
    return inventario_cache

def disponible(item: dict) -> bool:
    return normalize(item.get("stock","")) == "si"

def obtener_marcas_unicas(inv: list[dict]) -> list[str]:
    return sorted({i.get("marca","").strip() for i in inv if disponible(i)})

def obtener_modelos_por_marca(inv: list[dict], marca: str) -> list[str]:
    return sorted({i.get("modelo","").strip()
                   for i in inv
                   if normalize(i.get("marca","")) == normalize(marca) and disponible(i)})

def obtener_colores_por_modelo(inv: list[dict], modelo: str) -> list[str]:
    return sorted({i.get("color", "").strip()
                   for i in inv
                   if normalize(i.get("modelo", "")) == normalize(modelo)
                   and disponible(i)})

def obtener_tallas_por_color(inv: list[dict], modelo: str, color: str) -> list[str]:
    return sorted({
        str(i.get("talla", "")).strip()
        for i in inv
        if normalize(i.get("modelo", "")) == normalize(modelo)
        and normalize(i.get("color", "")) == normalize(color)
        and disponible(i)
    })

#  TRANSCRIPCIÓN DE AUDIO (WHISPER)
# ───────────────────────────────────────────────────────────────

TEMP_AUDIO_DIR = "temp_audio"
os.makedirs(TEMP_AUDIO_DIR, exist_ok=True)

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def transcribe_audio(file_path: str) -> str | None:
    """
    Envía el .ogg a Whisper-1 (idioma ES) y devuelve la transcripción.
    Si falla, devuelve None.
    """
    try:
        with open(file_path, "rb") as f:
            audio_bytes = io.BytesIO(f.read())
            audio_bytes.name = os.path.basename(file_path)  # necesario para Whisper

            rsp = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_bytes,
                language="es",
                response_format="text",
                prompt="Español Colombia, jerga: parce, mano, ñero, buenos días, buenas, hola"
            )

        if isinstance(rsp, str) and rsp.strip():
            return rsp.strip()
    except Exception as e:
        logging.error(f"❌ Whisper error: {e}")
    return None


# ───────────────────────────────────────────────────────────────

# 🔥 Manejar preguntas frecuentes (FAQ)
async def manejar_pqrs(update, ctx) -> bool:
    txt = normalize(update.message.text or "")

    faq_respuestas = {
        "garantia": "🛡️ Todos nuestros productos tienen *60 días de garantía* por defectos de fábrica.",
        "garantía": "🛡️ Todos nuestros productos tienen *60 días de garantía* por defectos de fábrica.",
        "envio": "🚚 Hacemos envíos a toda Colombia en máximo *2 días hábiles*.",
        "envío": "🚚 Hacemos envíos a toda Colombia en máximo *2 días hábiles*.",
        "demora": "⏳ El envío normalmente tarda *2 días hábiles*. ¡Te llega rápido!",
        "contraentrega": "💵 Tenemos *pago contra entrega* con anticipo de $35.000.",
        "pago": "💳 Puedes pagar por transferencia bancaria, QR o contra entrega.",
        "original": "✅ Sí, son *originales colombianos* de alta calidad.",
        "ubicacion": "📍 Estamos en *Bucaramanga, Santander* y enviamos a todo el país.",
        "ubicación": "📍 Estamos en *Bucaramanga, Santander* y enviamos a todo el país.",
        "talla": "📏 Nuestra horma es *normal*. La talla que usas normalmente te quedará perfecta.",
        "descuento": "🎉 Si compras 2 pares te damos *10% de descuento* adicional."
    }

    for palabra, respuesta in faq_respuestas.items():
        if palabra in txt:
            await ctx.bot.send_message(
                chat_id=update.effective_chat.id,
                text=respuesta,
                parse_mode="Markdown"
            )
            return True

    return False


# 🧠 Cargar base de embeddings guardados
EMBEDDINGS_PATH = "/var/data/embeddings.json"

def cargar_embeddings_desde_cache():
    path = "/var/data/embeddings.json"
    if not os.path.exists(path):
        raise FileNotFoundError("No se encontró embeddings.json; ejecuta generar_embeddings.py primero.")
    with open(path, "r") as f:
        return json.load(f)

# 🔥 Manejar imagen enviada por el usuario (ahora con CLIP)
async def manejar_imagen(update, ctx):
    cid = update.effective_chat.id
    est = estado_usuario.setdefault(cid, reset_estado(cid))

    # Descargar la imagen temporalmente
    f = await update.message.photo[-1].get_file()
    tmp_path = os.path.join("temp", f"{cid}.jpg")
    os.makedirs("temp", exist_ok=True)
    await f.download_to_drive(tmp_path)

    # Leer imagen como base64
    with open(tmp_path, "rb") as f_img:
        base64_img = base64.b64encode(f_img.read()).decode("utf-8")
    os.remove(tmp_path)

    try:
        mensaje = await identificar_modelo_desde_imagen(base64_img)

        if "coincide con *" in mensaje.lower():
            modelo_detectado = re.findall(r"\*(.*?)\*", mensaje)
            if modelo_detectado:
                partes = modelo_detectado[0].split("_")
                marca  = partes[0] if len(partes) > 0 else "Desconocida"
                modelo = partes[1] if len(partes) > 1 else "Desconocido"
                color  = partes[2] if len(partes) > 2 else "Desconocido"

                est.update({
                    "marca":  marca,
                    "modelo": modelo,
                    "color":  color,
                    "fase":   "imagen_detectada"
                })

            await ctx.bot.send_message(
                chat_id=cid,
                text=(
                    f"📸 La imagen coincide con:\n"
                    f"*Marca:* {marca}\n"
                    f"*Modelo:* {modelo}\n"
                    f"*Color:* {color}\n\n"
                    "¿Deseas continuar tu compra con este modelo? (SI/NO)"
                ),
                parse_mode="Markdown",
                reply_markup=menu_botones(["SI", "NO"]),
            )
            return

        # Si no hubo coincidencia satisfactoria
        reset_estado(cid)
        await ctx.bot.send_message(
            chat_id=cid,
            text=mensaje,
            parse_mode="Markdown",
            reply_markup=menu_botones(["Enviar otra imagen", "Ver catálogo"]),
        )

    except Exception as e:
        logging.error(f"❌ Error usando CLIP en manejar_imagen: {e}")
        reset_estado(cid)
        await ctx.bot.send_message(
            chat_id=cid,
            text="⚠️ Hubo un problema procesando la imagen. ¿Puedes intentar con otra?",
            reply_markup=menu_botones(["Enviar otra imagen"]),
        )

    # 🔍 Identificar modelo con CLIP

    try:
        mensaje = await identificar_modelo_desde_imagen(base64_img)

        if "coincide con *" in mensaje.lower():
            # extrae el texto entre asteriscos *
            modelo_detectado = re.findall(r"\*(.*?)\*", mensaje)
            if modelo_detectado:
                partes = modelo_detectado[0].split("_")
                marca  = partes[0] if len(partes) > 0 else "Desconocida"
                modelo = partes[1] if len(partes) > 1 else "Desconocido"
                color  = partes[2] if len(partes) > 2 else "Desconocido"

                est.update({
                    "marca":  marca,
                    "modelo": modelo,
                    "color":  color,
                    "fase":   "imagen_detectada"
                })

            await ctx.bot.send_message(
                chat_id=cid,
                text=(
                    f"📸 La imagen coincide con:\n"
                    f"*Marca:* {marca}\n"
                    f"*Modelo:* {modelo}\n"
                    f"*Color:* {color}\n\n"
                    "¿Deseas continuar tu compra con este modelo? (SI/NO)"
                ),
                parse_mode="Markdown",
                reply_markup=menu_botones(["SI", "NO"]),
            )
            return

        # ⬇️ Si no hubo coincidencia satisfactoria
        reset_estado(cid)
        await ctx.bot.send_message(
            chat_id=cid,
            text=mensaje,   # contiene la respuesta 'no identificado…'
            parse_mode="Markdown",
            reply_markup=menu_botones(["Enviar otra imagen", "Ver catálogo"]),
        )
        return

    except Exception as e:
        logging.error(f"❌ Error usando CLIP en manejar_imagen: {e}")
        await ctx.bot.send_message(
            chat_id=cid,
            text="⚠️ Hubo un problema procesando la imagen. ¿Puedes intentar de nuevo?",
            reply_markup=menu_botones(["Enviar otra imagen"]),
        )
        return

        # Si no se detectó bien
        reset_estado(cid)
        await ctx.bot.send_message(
            chat_id=cid,
            text="😔 No pude reconocer el modelo de la imagen. ¿Quieres intentar otra vez?",
            parse_mode="Markdown",
            reply_markup=menu_botones(["Enviar otra imagen", "Ver catálogo"])
        )

    except Exception as e:
        logging.error(f"❌ Error usando CLIP en manejar_imagen: {e}")
        await ctx.bot.send_message(
            chat_id=cid,
            text="❌ Hubo un error al procesar la imagen. ¿Puedes intentar de nuevo?",
            reply_markup=menu_botones(["Enviar otra imagen"])
        )
# ─────────────────────────────────────────────────────────────
# Ayudante: busca un producto exacto en el inventario
# ─────────────────────────────────────────────────────────────
def buscar_item(inv: list, marca: str, modelo: str, color: str):
    """Devuelve el dict del ítem que coincide 100 % o None."""
    for i in inv:
        if (
            normalize(i["marca"])  == normalize(marca)  and
            normalize(i["modelo"]) == normalize(modelo) and
            normalize(i["color"])  == normalize(color)
        ):
            return i
    return None


async def manejar_color_detectado(ctx, cid: str, color: str, inventario: list):
    ruta = "/var/data/modelos_video"
    if not os.path.exists(ruta):
        await ctx.bot.send_message(cid, "⚠️ Aún no tengo imágenes cargadas. Intenta más tarde.")
        return

    aliases = [color] + [k for k, v in color_aliases.items() if v == color]

    coincidencias = [
        f for f in os.listdir(ruta)
        if f.lower().endswith(".jpg") and any(alias in f.lower() for alias in aliases)
    ]
    if not coincidencias:
        await ctx.bot.send_message(cid, f"😕 No encontré modelos con color *{color.upper()}*.")
        return

    modelos_enviados = []
    modelos_info = []

    # 🟥 Mensaje inicial antes de enviar las fotos
    if len(coincidencias) == 1:
        mensaje_intro = (
            f"📸 *Este es el modelo de color {color.upper()} que manejamos.*\n"
            "🚚 Recuerda que el *envío es totalmente gratis*."
        )
    else:
        mensaje_intro = (
            f"📸 *Estos son los modelos de color {color.upper()} que manejamos.*\n"
            "🚚 Recuerda que el *envío es totalmente gratis*.\n"
            "🧐 Dime cuál es el que mas te gusto."
        )

    await ctx.bot.send_message(
        cid,
        mensaje_intro,
        parse_mode="Markdown"
    )


    for archivo in coincidencias:
        try:
            path = os.path.join(ruta, archivo)
            modelo_raw = archivo.replace(".jpg", "").replace("_", " ")
            marca = "DS"

            partes = modelo_raw.split(maxsplit=2)
            modelo = partes[1] if len(partes) > 1 else ""
            color_archivo = partes[2] if len(partes) > 2 else color

            item = next(
                (i for i in inventario
                 if normalize(i["marca"]) == normalize(marca)
                 and normalize(i["modelo"]) == normalize(modelo)
                 and normalize(i["color"]) in normalize(color_archivo)),
                None
            )
            precio = f"{int(item['precio']):,} COP" if item else "Consultar"

            caption = (
                f"📸 *{modelo_raw}*\n"
                f"💰 Precio: {precio}"
            )

            await ctx.bot.send_photo(
                chat_id=cid,
                photo=open(path, "rb"),
                caption=caption,
                parse_mode="Markdown"
            )

            modelos_enviados.append(modelo_raw)
            modelos_info.append({
                "marca": marca,
                "modelo": modelo,
                "color": color_archivo,
                "precio_total": int(item["precio"]) if item else 0
            })

            if len(modelos_enviados) >= 4:
                break

        except Exception as e:
            logging.error(f"❌ Error enviando imagen: {e}")

    estado_usuario[cid].update({
        "color": color,
        "fase": "esperando_modelo_elegido",
        "modelos_enviados": modelos_enviados,
        "modelos_info": modelos_info
    })





# ───────────────────────────────────────────────────────────────

def registrar_orden_unificada(data: dict, destino: str = "PEDIDOS") -> bool:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials

    try:
        logging.info(f"[SHEETS] ⇢ Intentando registrar en hoja: {destino}")
        logging.info(f"[SHEETS] Datos recibidos:\n{json.dumps(data, indent=2, ensure_ascii=False)}")

        # Cargar credenciales desde variable de entorno
        creds_dict = json.loads(os.getenv("GOOGLE_CREDS_JSON"))
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)

        # Abrir archivo y hoja
        sh = client.open("PEDIDOS")
        sheet = sh.worksheet(destino)

        # Fecha actual
        fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Fila por tipo
        if destino == "PEDIDOS":
            fila = [
                data.get("Número Venta", ""),
                fecha_actual,
                data.get("Cliente", "No informado"),
                data.get("Cédula", "No informada"),
                data.get("Teléfono", "No informado"),
                data.get("Producto", "No informado"),
                data.get("Color", "No informado"),
                data.get("Talla", "No informada"),
                data.get("Correo", "No informado"),
                data.get("Pago", "No definido"),
                data.get("fase_actual", "Sin registrar"),
                data.get("Estado", "PENDIENTE")
            ]
        elif destino == "PENDIENTES":
            fila = [
                fecha_actual,
                data.get("Cliente", "No informado"),
                data.get("Teléfono", "No informado"),
                data.get("Producto", "No informado"),
                data.get("Pago", "No indicado")  # Se usa "Pago" como campo 'Día/Hora contacto'
            ]
        elif destino == "ADDI":
            fila = [
                fecha_actual,
                data.get("Cliente", "No informado"),
                data.get("Cédula", "No informada"),
                data.get("Teléfono", "No informado"),
                data.get("Correo", "No informado"),
            ]
        else:
            logging.error(f"[SHEETS] ❌ Hoja desconocida: {destino}")
            return False

        # Escribir
        sheet.append_row(fila)
        logging.info(f"[SHEETS] ✅ Fila escrita correctamente en hoja '{destino}'")
        return True

    except Exception as e:
        logging.exception(f"[SHEETS] ❌ Error escribiendo en hoja '{destino}': {e}")
        return False



# ───────────────────────────────────────────────────────────────

# 🔥 Generar ID único para una venta
def generate_sale_id() -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")  # ✅ sin datetime.datetime
    rnd = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"VEN-{ts}-{rnd}"

async def enviar_sticker(ctx, cid, nombre_archivo):
    ruta = os.path.join("/var/data/stickers", nombre_archivo)
    if os.path.exists(ruta):
        try:
            await ctx.client.sendImageAsSticker(cid, ruta)
            logging.info(f"✅ Sticker enviado: {ruta}")
        except Exception as e:
            logging.warning(f"⚠️ No se pudo enviar el sticker {nombre_archivo}: {e}")
    else:
        logging.warning(f"⚠️ Sticker no encontrado: {ruta}")

# ────────────────────────────────────────────────────────────
# FUNCIÓN AUXILIAR – ENVIAR VIDEO (VENOM) CON LOGS DETALLADOS
# ────────────────────────────────────────────────────────────
async def enviar_todos_los_videos(cid):
    try:
        carpeta = "/var/data/videos"
        if not os.path.exists(carpeta):
            logging.warning(f"[VIDEOS] ⚠️ Carpeta no encontrada: {carpeta}")
            return {
                "type": "text",
                "text": "⚠️ No tengo videos cargados por ahora. Intenta más tarde."
            }

        archivos = sorted([
            f for f in os.listdir(carpeta)
            if f.lower().endswith(".mp4")
        ])

        logging.info(f"[VIDEOS] Archivos detectados: {archivos}")

        if not archivos:
            return {
                "type": "text",
                "text": "⚠️ No tengo videos disponibles en este momento."
            }

        mensajes = []
        for nombre in archivos:
            ruta = os.path.join(carpeta, nombre)
            try:
                with open(ruta, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")

                mensajes.append({
                    "type": "video",
                    "base64": b64,
                    "mimetype": "video/mp4",
                    "filename": nombre,
                    "text": f"🎥 Video: {nombre.replace('.mp4', '').replace('_', ' ').title()}"
                })

            except Exception as ve:
                logging.error(f"❌ Error leyendo video '{nombre}': {ve}")

        if not mensajes:
            return {
                "type": "text",
                "text": "❌ No logré preparar ningún video. Intenta más tarde."
            }

        logging.info(f"[VIDEOS] ✅ Videos preparados: {len(mensajes)}")
        return {
            "type": "multi",
            "messages": mensajes
        }

    except Exception as e:
        logging.error(f"❌ Error general al preparar videos: {e}")
        return {
            "type": "text",
            "text": "❌ No logré enviarte los videos. Intenta más tarde."
        }






# 👟 Obtener tallas desde inventario, respetando alias del color
def obtener_tallas_por_color_alias(inventario, modelo, color_usuario):
    color_usuario = normalize(color_usuario)
    
    # 🔁 Crear set con todos los colores equivalentes: color original + sinónimos
    colores_equivalentes = {color_usuario}
    for alias, real in color_aliases.items():
        if normalize(alias) == color_usuario or normalize(real) == color_usuario:
            colores_equivalentes.add(normalize(alias))
            colores_equivalentes.add(normalize(real))

    tallas = set()
    for item in inventario:
        if normalize(item.get("modelo", "")) != normalize(modelo):
            continue
        if item.get("stock", "").lower() != "si":
            continue

        color_item = normalize(item.get("color", ""))
        if any(color_equiv in color_item for color_equiv in colores_equivalentes):
            tallas.add(str(item.get("talla", "")))

    return sorted(tallas)

def extraer_cm_y_convertir_talla(texto):
    import re

    tabla_cm = {
        23: 34, 24: 35, 24.5: 36, 25: 37, 26: 38,
        26.5: 39, 27: 40, 27.5: 41, 28.5: 42,
        29: 43, 30: 44, 31: 45
    }

    # Buscar patrones como 26cm, 260mm, JP 27.5, etc.
    coincidencias = re.findall(r'(\d{2,3}(?:\.\d+)?)\s?(cm|mm|jp)?', texto.lower())

    for valor, unidad in coincidencias:
        try:
            numero = float(valor)
            if unidad == "mm" or (not unidad and numero > 100):
                numero = numero / 10  # convertir mm a cm
            elif unidad == "jp":
                numero = numero  # ya está en CM

            # Redondear al más cercano de la tabla
            numero = round(numero * 2) / 2  # redondea a 0.5

            if numero in tabla_cm:
                return tabla_cm[numero]
        except:
            continue

    return None

def extraer_nombre(txt):
    palabras = txt.split()
    nombre = " ".join(p for p in palabras if p.istitle())
    return nombre or "Nombre no detectado"

def extraer_modelo(txt):
    m = re.search(r"\d{3,4}", txt)
    return m.group() if m else "Modelo no detectado"

def extraer_dia_hora(txt):
    m = re.search(r"(lunes|martes|miércoles|jueves|viernes|sábado|domingo)?\s*\d{1,2}(\s*(am|pm))?", txt, re.IGNORECASE)
    return m.group() if m else "No especificado"
import re

# 🎨 Alias de color (bidireccional + plurales)
color_aliases = {
    "rosado": "fucsia", "rosa": "fucsia", "fucsias": "fucsia",
    "celeste": "azul", "azules": "azul",
    "azul cielo": "aqua", "azul clarito": "aqua", "azul claro": "aqua", "azulito": "aqua",
    "verdes": "verde", "amarillas": "amarillo", "blancos": "blanco", "negros": "negro",
    "rojos": "rojo", "naranjas": "naranja", "turquesa": "aqua"
}

# 🚀 Agregar alias inversos automáticamente
for base_color in list(color_aliases.values()):
    color_aliases[base_color] = base_color

# 📼 Asociación de colores y modelos por video específico
colores_video_modelos = {
    "referencias": {
        "verde":    ["279", "305"],
        "azul":     ["279", "304", "305"],
        "fucsia":   ["279"],
        "amarillo": ["279"],
        "naranja":  ["279", "304"],
        "negro":    ["279", "304"],
        "blanco":   ["279", "305"],
        "rojo":     ["279"],
        "aqua":     ["305"],
    }
}

# 🎨 Detección general de colores (con regex)
def detectar_color(texto: str) -> str:
    texto = texto.lower().strip()

    for palabra, real_color in color_aliases.items():
        if re.search(rf"\b{re.escape(palabra)}\b", texto):
            return real_color

    colores_base = [
        "negro", "blanco", "rojo", "azul", "amarillo", "verde",
        "rosado", "gris", "morado", "naranja", "café", "beige",
        "neón", "limón", "fucsia", "celeste", "aqua", "turquesa"
    ]
    for c in colores_base:
        if re.search(rf"\b{re.escape(c)}\b", texto):
            return c

    return ""

# 🧠 Detección de color en contexto de video (también con regex)
def detectar_color_video(texto: str) -> str:
    texto = texto.lower().strip()

    for palabra, real_color in color_aliases.items():
        if re.search(rf"\b{re.escape(palabra)}\b", texto):
            return real_color

    for color in colores_video_modelos.get("referencias", {}):
        if re.search(rf"\b{re.escape(color)}\b", texto):
            return color

    return ""


# --------------------------------------------------------------------------------------------------

async def responder(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    numero = str(cid)
    txt_raw = update.message.text or ""
    txt = normalize(txt_raw)
   # Ya existe el usuario
    est = estado_usuario[cid]
    inv = obtener_inventario()
    tallas = obtener_tallas_por_color_alias(inv, est.get("modelo", ""), est.get("color", ""))
    if isinstance(tallas, (int, float, str)):
        tallas = [str(tallas)]

    print("🧠 FASE:", est.get("fase"))
    print("🧠 TEXTO:", txt_raw, "|", repr(txt_raw))
    print("🧠 ESTADO:", est)

    # 👋 Detectar saludo inicial y responder con bienvenida + videos
    if any(p in txt for p in ("hola", "buenas", "buenos días", "buenas tardes", "buenas noches")):
        logging.info(f"👋 Saludo detectado: {txt_raw} — CID: {cid}")

        # 1. Mensaje de bienvenida
        await update.message.reply_text(
            WELCOME_TEXT,
            reply_markup=menu_botones([
                "Hacer pedido", "Enviar imagen", "Ver catálogo",
                "Rastrear pedido", "Realizar cambio"
            ])
        )

        # 2. Envío automático de todos los videos disponibles (excepto confianza)
        ruta_videos = "/var/data/videos"
        try:
            if not os.path.exists(ruta_videos):
                logging.warning(f"⚠️ Carpeta de videos no encontrada: {ruta_videos}")
                await ctx.bot.send_message(cid, "⚠️ Aún no tengo videos cargados.")
                return

            archivos = sorted([
                f for f in os.listdir(ruta_videos)
                if f.lower().endswith(".mp4") and "confianza" not in f.lower()
            ])

            logging.info(f"🎬 Videos encontrados (sin confianza): {archivos}")
            print("📂 DEBUG: Archivos encontrados para enviar:", archivos)

            if not archivos:
                logging.warning("⚠️ Lista de videos vacía aunque la carpeta existe.")
                await ctx.bot.send_message(cid, "⚠️ Aún no tengo videos cargados.")
                return

            await ctx.bot.send_message(
                chat_id=cid,
                text="🎬 Mira nuestras referencias en video. ¡Dime cuál te gusta y en que talla lo deseas!"
            )
            logging.info("🎯 Procediendo a enviar videos...")

            for nombre in archivos:
                try:
                    path = os.path.join(ruta_videos, nombre)
                    size = os.path.getsize(path)
                    logging.info(f"🎥 Enviando: {nombre} — {size / 1024:.2f} KB")
                    print(f"📤 DEBUG: Enviando {nombre} a {cid}")

                    with open(path, "rb") as video_file:
                        await ctx.bot.send_video(
                            chat_id=cid,
                            video=video_file,
                            caption=f"🎥 {nombre.replace('.mp4', '').replace('_', ' ').title()}",
                            parse_mode="Markdown"
                        )

                except Exception as e:
                    logging.error(f"❌ Error enviando video '{nombre}': {e}")
                    await ctx.bot.send_message(cid, f"⚠️ No pude enviar el video {nombre}")

            await ctx.bot.send_message(
                chat_id=cid,
                text="🧐 ¿Dime que referencia te interesan, si no esta aca enviame la foto?"
            )

            # Solo cambiar la fase sin borrar el estado anterior
            est["fase"] = "esperando_modelo_elegido"
            estado_usuario[cid] = est
            return

        except Exception as e:
            logging.error(f"❌ Error al enviar videos tras saludo: {e}")
            await ctx.bot.send_message(cid, "❌ Hubo un error al cargar los videos.")
  
            return

    # 💬 Usuario pregunta por precios de modelos mostrados (uno o varios)
    if est.get("modelos_enviados") and any(p in texto for p in (
        "cuánto valen", "qué precio tienen", "cuánto cuestan", "precio de esos", "valen los",
        "cuanto valen", "cuanto cuesta", "cuánto cuesta", "cuánto tienen de precio",
        "valor de esos", "qué valor tienen", "dígame el precio", "dígame el valor",
        "cual es el precio", "cual es el valor", "valor"
    )):
        modelos = est["modelos_enviados"]
        respuestas = []

        # 🟢 Caso: 1 solo modelo mostrado → responder precio directo
        if len(modelos) == 1:
            partes = modelos[0].split()
            if len(partes) >= 3:
                marca = partes[0]
                modelo = partes[1]
                color = " ".join(partes[2:])

                est["marca"] = marca
                est["modelo"] = modelo
                est["color"] = color
                estado_usuario[cid] = est

                item = next(
                    (i for i in inv if
                     normalize(i["modelo"]) == normalize(modelo) and
                     normalize(i["color"]) == normalize(color) and
                     normalize(i["marca"]) == normalize(marca)),
                    None
                )

                if item and item.get("precio"):
                    precio = f"{int(item['precio']):,} COP"
                    return {
                        "type": "text",
                        "text": (
                            f"💰 El precio de los *{modelo}* color *{color}* es: *{precio}*.\n"
                            "🚚 Recuerda que el *envío es gratis* a cualquier ciudad de Colombia."
                        ),
                        "parse_mode": "Markdown"
                    }

        # 🟡 Caso: múltiples modelos → listar precios uno por uno
        for modelo_raw in modelos:
            partes = modelo_raw.split()
            if len(partes) >= 3:
                marca = partes[0]
                modelo = partes[1]
                color = " ".join(partes[2:])
            else:
                continue

            item = next(
                (i for i in inv if
                 normalize(i["modelo"]) == normalize(modelo) and
                 normalize(i["color"]) == normalize(color) and
                 normalize(i["marca"]) == normalize(marca)),
                None
            )

            if item and item.get("precio"):
                precio = f"{int(item['precio']):,} COP"
                respuestas.append(f"💰 *{modelo_raw}*: {precio}")

        if respuestas:
            return {
                "type": "text",
                "text": (
                    "👀 Mira estas referencias te cuestan:\n\n" +
                    "\n".join(respuestas) +
                    "\n\n🚚 *Con el envío totalmente gratis.*\n"
                    "📏 ¿En qué *talla* los deseas?"
                ),
                "parse_mode": "Markdown"
            }
        else:
            return {
                "type": "text",
                "text": "❌ No encontré los precios exactos de esos modelos. ¿Quieres que te los confirme manualmente?",
                "parse_mode": "Markdown"
            }




    # 💰 Usuario pregunta por precio de modelo ya mostrado (sin repetir imagen)
    if est.get("modelo") and est.get("color"):
        if any(palabra in texto for palabra in (
            "cuánto vale", "cuanto vale", "precio", "cuánto cuesta", "cuanto cuesta", "vale los", "cuánto valen", "cuanto valen"
        )):
            modelo = est["modelo"]
            color = est["color"]
            marca = est.get("marca", "DS")  # por defecto DS

            item = next(
                (i for i in inv if
                 normalize(i["modelo"]) == normalize(modelo) and
                 normalize(i["color"]) == normalize(color) and
                 normalize(i["marca"]) == normalize(marca)),
                None
            )
            if item and item.get("precio"):
                precio = f"{int(item['precio']):,} COP"
                return {
                    "type": "text",
                    "text": (
                        f"💰 El precio de los *{modelo}* color *{color}* es: *{precio}*.\n"
                        "🚚 Recuerda que el *envío es gratis* a todo Colombia."
                    ),
                    "parse_mode": "Markdown"
                }
            else:
                return {
                    "type": "text",
                    "text": "❌ Aún no tengo registrado el precio exacto para ese modelo. ¿Te gustaría que lo consulte por ti?"
                }

    # ──────────────────────────────────────────────────────────────
    # BLOQUE PRINCIPAL (§ Detecta color → muestra modelos → pregunta talla)
    # ──────────────────────────────────────────────────────────────
    # 🎨 1) El cliente menciona un color (p.e. “me gustaron los amarillos”)
    if detectar_color(txt) and est.get("fase") not in {"esperando_modelo_elegido", "esperando_talla"}:
        color = detectar_color(txt)
        await manejar_color_detectado(ctx, cid, color, inv)
        return

    # ── 2) Cliente responde después de ver las imágenes ─────────
    if est.get("fase") == "esperando_modelo_elegido":
        modelos = est.get("modelos_enviados", [])
        texto_normalizado = normalize(texto)

        # 🚀 Caso 1 - Un solo modelo + “talla X”
        if len(modelos) == 1 and (m := re.search(r"talla\s*(\d{1,2})", texto_normalizado)):
            est["modelo"] = modelos[0]
            est["talla"] = m.group(1)

        # 1️⃣ Referencia numérica (ej. 395)
        if not est.get("modelo") and (m := re.search(r"\b(\d{3})\b", texto)):
            ref = m.group(1)
            est["modelo"] = next((m for m in modelos if ref in m), None)

        # 2️⃣ Coincidencia textual
        if not est.get("modelo"):
            for m in modelos:
                if normalize(m) in texto_normalizado:
                    est["modelo"] = m
                    break

        # 3️⃣ Afirmación genérica (si solo hay 1 imagen)
        afirmaciones = {
            "si", "sí", "sii", "sisas", "de una", "dale", "hágale", "hagale",
            "me gustaron", "me llevo esos", "quiero esos", "quiero esas",
            "me encantaron", "esos", "esas", "ese", "esa"
        }
        faq_palabras = {"envio", "pago", "garantia", "talla", "tallas",
                        "ubicacion", "donde", "horma", "precio", "costos"}
        if (
            not est.get("modelo")
            and len(modelos) == 1
            and any(p in texto_normalizado for p in afirmaciones)
            and not any(p in texto_normalizado for p in faq_palabras)
        ):
            est["modelo"] = modelos[0]

        # 🚨 Si ya se identificó el modelo, usar directamente la info precargada
        if est.get("modelo"):
            modelo_actual = est["modelo"]
            info_candidatos = est.get("modelos_info", [])

            elegido = next((m for m in info_candidatos if m["modelo"] == modelo_actual), None)

            if elegido:
                est.update({
                    "marca": elegido["marca"],
                    "modelo": elegido["modelo"],
                    "color": elegido["color"],
                    "precio_total": elegido["precio_total"]
                })

        # 🛑 Si aún no sabemos qué modelo eligió
        if "modelo" not in est:
            await ctx.bot.send_message(cid, "❓ Dime cuál te gustó de las que te mandé.")
            return



        # ───────────────── MARCA / MODELO / COLOR ─────────────────
        marca = "DS"                                    # ← fija
        partes = est["modelo"].split()
        # Si formato “DS 395 VERDE LIMON…”
        if len(partes) >= 2 and partes[1].isdigit():
            modelo = partes[1]
            color_archivo = " ".join(partes[2:]) if len(partes) > 2 else est.get("color", "")
        else:  # si quedó “395”
            modelo = partes[0]
            color_archivo = est.get("color", "")
        est.update({"marca": marca, "modelo": modelo, "color": color_archivo})

        # ─────────────────── Calcular PRECIO ─────────────────────
        item = next(
            (i for i in inv
             if normalize(i["marca"]) == normalize(marca)
             and normalize(i["modelo"]) == normalize(modelo)
             and normalize(i["color"]) in normalize(color_archivo)),
            None
        )
        if not item:  # Fallback sin color
            item = next(
                (i for i in inv
                 if normalize(i["marca"]) == normalize(marca)
                 and normalize(i["modelo"]) == normalize(modelo)),
                None
            )
        if item:
            est["precio_total"] = int(item["precio"])

        # ───────────────── Manejo de talla ───────────────────────
        match_talla_preg = re.search(r"(tienen|hay|manejan|disponible).+talla\s+(\d{1,2})", texto_normalizado)
        match_talla = re.search(r"talla\s+(\d{1,2})", texto_normalizado)

        if est.get("talla"):
            talla = est["talla"]
            mensaje_inicial = f"✅ Perfecto, tomaremos *{marca} {modelo} {color_archivo}* en talla *{talla}*.\n"
        elif match_talla_preg:
            talla = match_talla_preg.group(2)
            est["talla"] = talla
            mensaje_inicial = f"✅ ¡Claro que tenemos talla *{talla}* para el modelo *{marca} {modelo} {color_archivo}*!\n"
        elif match_talla:
            talla = match_talla.group(1)
            est["talla"] = talla
            mensaje_inicial = f"✅ Perfecto, tomaremos *{marca} {modelo} {color_archivo}* en talla *{talla}*.\n"
        else:
            mensaje_inicial = f"✅ Perfecto, tomaremos *{marca} {modelo} {color_archivo}*.\n"

        # ─────────────── Persistir y pedir lengüeta ──────────────
        est["fase"] = "esperando_talla"
        estado_usuario[cid] = est

        ruta_ejemplo = "/var/data/extra/lengueta_ejemplo.jpg"
        if os.path.exists(ruta_ejemplo):
            with open(ruta_ejemplo, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            return {
                "type": "multi",
                "messages": [
                    {
                        "type": "text",
                        "text": (
                            mensaje_inicial +
                            "📸 Para confirmar la talla exacta, envíame una foto de la *lengüeta* "
                            "del zapato que usas normalmente 👟."
                        ),
                        "parse_mode": "Markdown"
                    },
                    {
                        "type": "photo",
                        "base64": f"data:image/jpeg;base64,{b64}",
                        "text": "Así debe verse la lengüeta. Envíame una foto parecida 📸"
                    }
                ]
            }

        return {
            "type": "text",
            "text": (
                mensaje_inicial +
                "📸 Envíame la foto de la lengüeta de tu zapato para confirmar la medida 👟."
            ),
            "parse_mode": "Markdown"
        }

    # ─────────────────────────────────────────────
    # 📦 RESPUESTA UNIVERSAL SI EL CLIENTE EXPRESA DESCONFIANZA
    # ─────────────────────────────────────────────
    texto_normalizado = normalize(txt)

    frases_desconfianza = [
        "no confio", "desconfio", "me han robado", "PERO YO COMO SE QUE NO ME VAN A ROBAR", "ya me robaron", "y si me roban",
        "me estafaron", "ya me estafaron", "me hicieron el robo", "como se que no me van a robar",
        "no quiero pagar anticipado", "no quiero dar plata antes", "no quiero enviar dinero sin ver",
        "me da desconfianza", "me da miedo pagar", "no me da confianza", "me han tumbado",
        "me hicieron fraude", "tengo miedo de pagar", "no tengo seguridad", "Como se que no me roban",
        "quiero pagar al recibir", "pago al recibir", "solo contraentrega", "pago cuando llegue",
        "cuando me lleguen pago", "Como se que no me van a robar", "pago cuando me llegue", "me tumbaron una vez",
        "me jodieron", "ya me tumbaron", "no vuelvo a caer", "yo como se que no me roban", "eso me paso antes",
        "no me sale el mensaje", "no me abre el link", "me han robado antes", "me da cosa pagar",
        "no puedo pagar sin saber", "no mando dinero asi", "no conozco su tienda", "no estoy seguro",
        "como se que es real", "como se que es confiable", "como saber si es real", "esto es confiable?",
        "no tengo pruebas", "es seguro esto?", "no me siento comodo pagando", "mejor contraentrega",
        "yo solo pago al recibir", "yo no pago antes", "a mi me han estafado", "me estafaron antes",
        "me robaron antes", "y si no me llega", "y si no llega", "y si me estafan", "me robaron antes",
        "ya me tumbaron plata", "me hicieron perder plata", "me quitaron la plata",
        "me da miedo que me estafen", "esto no parece seguro", "no se ve seguro", "y si es mentira",
        "y si es estafa", "robo", "yo no pago sin ver", "yo no mando plata asi", "robado",
        "esto parece raro", "y si no cumplen", "y si no es verdad", "parece una estafa", "se ve raro",
        "esto huele a estafa", "muy sospechoso", "no quiero perder plata", "no me arriesgo",
        "no voy a arriesgar mi dinero"
    ]

    # 🟥 Desconfianza: envía videos + audio de confianza
    if any(frase in texto_normalizado for frase in frases_desconfianza):
        carpeta_videos = "/var/data/videos"
        audio_path = "/var/data/audios/confianza/Desconfianza.mp3"

        mensajes = [{
            "type": "text",
            "text": "🤝 Entendemos tu preocupación. Te compartimos estos videos para que veas que somos una tienda real y seria."
        }]

        # ✅ Lista exacta de videos válidos
        videos_confianza = {
            "video_confianza.mp4",
            "WhatsApp Video 2025-05-28 at 4.26.50 PM.mp4"
        }

        for archivo in sorted(os.listdir(carpeta_videos)):
            if archivo in videos_confianza:
                ruta_video = os.path.join(carpeta_videos, archivo)
                try:
                    with open(ruta_video, "rb") as f:
                        mensajes.append({
                            "type": "video",
                            "base64": base64.b64encode(f.read()).decode("utf-8"),
                            "mimetype": "video/mp4",
                            "filename": archivo,
                            "text": f"🎥 Mira este video de confianza:"
                        })
                except Exception as e:
                    logging.warning(f"⚠️ No se pudo leer el video {archivo}: {e}")

        if os.path.exists(audio_path):
            with open(audio_path, "rb") as f:
                mensajes.append({
                    "type": "audio",
                    "base64": base64.b64encode(f.read()).decode("utf-8"),
                    "mimetype": "audio/mpeg",
                    "filename": "Desconfianza.mp3",
                    "text": "🎧 Escucha este audio breve también:"
                })

        await reanudar_fase_actual(cid, ctx, est)
        return {"type": "multi", "messages": mensajes}


    # 🟨 Detección universal de color — funciona en cualquier fase
    try:
        if detectar_color(txt):
            color = detectar_color(txt)
            logging.info(f"[COLOR] Petición de color → {color} | CID: {cid}")

            ruta = "/var/data/modelos_video"
            if not os.path.exists(ruta):
                logging.warning(f"[COLOR] Carpeta no existe: {ruta}")
                await ctx.bot.send_message(cid, "⚠️ Aún no tengo imágenes cargadas. Intenta más tarde.")
                return

            aliases_del_color = [color] + [k for k, v in color_aliases.items() if v == color]
            coincidencias = [
                f for f in os.listdir(ruta)
                if f.lower().endswith(".jpg") and any(alias in f.lower() for alias in aliases_del_color)
            ]
            logging.info(f"[COLOR] Coincidencias encontradas: {coincidencias}")

            if not coincidencias:
                await ctx.bot.send_message(cid, f"😕 No encontré modelos con color *{color.upper()}*.")
                return

            errores_envio = 0
            modelos_enviados = []

            for archivo in coincidencias:
                path = os.path.join(ruta, archivo)

                modelo_raw = archivo.replace(".jpg", "").replace("_", " ")
                partes = modelo_raw.split()

                if len(partes) >= 3:
                    marca = partes[0]
                    modelo = partes[1]
                    color_archivo = " ".join(partes[2:])
                else:
                    marca = modelo = color_archivo = ""

                modelos_enviados.append(modelo_raw)

                item = next(
                    (i for i in inv if
                     normalize(i["modelo"]) == normalize(modelo) and
                     normalize(i["color"]) == normalize(color_archivo)),
                    None
                )
                precio = f"{int(item['precio']):,} COP" if item else "Consultar"

                try:
                    await ctx.bot.send_photo(
                        chat_id=cid,
                        photo=open(path, "rb"),
                        caption=(
                            f"📸 Modelo *{modelo_raw}* en color *{color.upper()}*\n"
                            f"💰 Precio: {precio}"
                        ),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    errores_envio += 1
                    logging.error(f"❌ Error enviando {archivo}: {e}")

            if errores_envio:
                await ctx.bot.send_message(cid, f"⚠️ No pude enviar {errores_envio} de {len(coincidencias)} imágenes.")

            # Guardar estado para precio/tallas posteriores
            est["color"] = color
            est["fase"] = "esperando_modelo_elegido"
            est["modelos_enviados"] = modelos_enviados
            estado_usuario[cid] = est

            # Mensaje final
            await ctx.bot.send_message(
                cid,
                "🧐 Dime qué referencia te interesa. Si no está acá, envíame una foto 📸.",
                parse_mode="Markdown"
            )
            return

    except Exception as e:
        logging.error(f"❌ Error en bloque de detección de color: {e}")
        await ctx.bot.send_message(cid, "❌ Ocurrió un problema al procesar el color. Intenta de nuevo.")
        return


    # ──────────────────────────────────────────────────────
    # 💬 DETECTOR UNIVERSAL — "me pagan el 30"
    # ──────────────────────────────────────────────────────
    if re.search(r"(me\s+pagan|me\s+consignan|me\s+depositan)(\s+el)?\s+\d{1,2}", txt, re.IGNORECASE):
        ctx.resp.append({
            "type": "text",
            "text": (
                "🗓️ ¡Perfecto! Te contactaremos ese día para ayudarte a cerrar la compra.\n\n"
                "Para dejarte agendado, por favor mándame estos datos:\n\n"
                "• 🧑‍💼 *Tu nombre completo*\n"
                "• 👟 *Producto que te interesa*\n"
                "• 🕒 *¿Qué día y a qué hora te contactamos?*"
            ),
            "parse_mode": "Markdown"
        })
        est["fase"] = "esperando_datos_pago_posterior"
        estado_usuario[cid] = est
        return

    # ──────────────────────────────────────────────────────
    # 📋 RECOLECCIÓN DE DATOS PARA LA HOJA "PENDIENTES"
    # ──────────────────────────────────────────────────────
    if est.get("fase") == "esperando_datos_pago_posterior":
        try:
            texto_limpio = txt_raw.replace("\n", " ").strip()

            # 1️⃣ Modelo: primer número de 3-4 cifras
            modelo_match = re.search(r"\b\d{3,4}\b", texto_limpio)
            modelo = modelo_match.group(0) if modelo_match else ""

            # 2️⃣ Nombre: todo lo que va antes del modelo
            nombre = texto_limpio.split(modelo)[0].strip() if modelo else ""

            # 3️⃣ Día/hora: desde cualquier mención de fecha u hora en adelante
            dia_hora_match = re.search(
                r"(mañana|hoy|el\s+\d{1,2}\b|día\s+\d{1,2}\b|a\s+las\s+\d{1,2}(?:[:h]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?)",
                texto_limpio, re.IGNORECASE
            )
            dia_hora = texto_limpio[dia_hora_match.start():].strip() if dia_hora_match else ""

            if nombre and modelo and dia_hora:
                datos_pendiente = {
                    "Cliente":  nombre.title(),
                    "Teléfono": cid,
                    "Producto": modelo,
                    "Pago":     dia_hora
                }

                ok = registrar_orden_unificada(datos_pendiente, destino="PENDIENTES")

                if ok:
                    ctx.resp.append({
                        "type": "text",
                        "text": (
                            f"✅ ¡Listo {nombre.title()}! Te escribiremos {dia_hora} "
                            f"para cerrar la compra del modelo {modelo.upper()} 🔥"
                        )
                    })
                    est["fase"] = "pausado_promesa"
                    est["pausa_hasta"] = (datetime.now() + timedelta(hours=48)).isoformat()
                    estado_usuario[cid] = est
                else:
                    ctx.resp.append({
                        "type": "text",
                        "text": "⚠️ No pudimos registrar tu promesa de pago. Intenta nuevamente."
                    })
                return

            # ——— Datos incompletos ———
            ctx.resp.append({
                "type": "text",
                "text": (
                    "❌ Para agendar tu pago necesito 3 cosas:\n"
                    "1️⃣ Tu *nombre*\n2️⃣ El *modelo* que te gustó\n3️⃣ *Día y hora* estimada para contactarte\n\n"
                    "Ejemplo:\nJuan Pablo\nDS 298\nEl 30 a las 2 PM"
                ),
                "parse_mode": "Markdown"
            })
            return

        except Exception as e:
            logging.error(f"[PENDIENTES] ❌ Error registrando pago posterior: {e}")
            ctx.resp.append({
                "type": "text",
                "text": "⚠️ Ocurrió un problema registrando tus datos. Intenta de nuevo más tarde."
            })
            return



    # ─────────────────────────────────────────────
    # 📍 DETECTAR SI ES DE BUCARAMANGA (GLOBAL)
    # ─────────────────────────────────────────────
    if not est.get("es_de_bucaramanga") and any(b in txt for b in ["bucaramanga", "bga", "b/manga"]):
        est["es_de_bucaramanga"] = True
        estado_usuario[cid] = est
        logging.info(f"📍 Cliente {cid} es de Bucaramanga")

        if est.get("fase") == "inicio":
            await ctx.bot.send_message(
                chat_id=cid,
                text=(
                    "📍 ¡Genial! Como estás en *Bucaramanga*, más adelante podrás elegir entre *que lo envie un domiciliario* 🛵 "
                    "o *recoger en tienda* 🏪.\n\n"
                    "Continuemos con tu pedido 👟"
                ),
                parse_mode="Markdown"
            )
            return


    # 💬 Si el usuario pregunta el precio en cualquier parte del flujo
    palabras_precio = (
        "precio", "preció", "prezio", "que presio tienen",
        "valor", "que presio hay", "vale", "valen", "que precio tienen",
        "vale esto", "valen esto", "costo", "kosto", "cuesto",
        "cuanto cuesta", "cuanto vale", "cuanto esta", "cuanto es",
        "cuanto valen", "cuanto cuestan", "cuanto sale", "que precio", "que vale",
        "kuanto cuesta", "kuanto bale", "cuanttto bale", "k vale", "q cuesta",
        "q precio", "q vale", "cuanto me sale", "vale cuanto", "cuesta cuanto",
        "vale algo", "valen algo", "cuanto cobras", "cuanto cobran",
        "balor", "cuanto baale", "k bale", "vale eso", "cuanto valdra"
    )

    txt_norm = normalize(txt)

    pregunta_precio = (
        any(p in txt_norm for p in palabras_precio) or
        any(difflib.get_close_matches(w, palabras_precio, n=1, cutoff=0.8)
            for w in txt_norm.split())
    )

    if pregunta_precio:
        if est.get("modelo") and est.get("color"):
            precio = next(
                (i["precio"] for i in inv if
                 normalize(i["marca"])  == normalize(est.get("marca", "")) and
                 normalize(i["modelo"]) == normalize(est["modelo"]) and
                 normalize(i["color"])  == normalize(est["color"])
                ),
                None
            )
            if precio:
                await ctx.bot.send_message(
                    chat_id=cid,
                    text=f"💰 El modelo *{est['modelo']}* color *{est['color']}* "
                         f"tiene un precio de *${precio}* COP.",
                    parse_mode="Markdown"
                )
            else:
                await ctx.bot.send_message(
                    chat_id=cid,
                    text="😕 Aún no tengo el precio exacto de ese modelo. Déjame verificarlo."
                )
        else:
            await ctx.bot.send_message(
                chat_id=cid,
                text=("Para darte el precio necesito saber la referencia o repetirla. "
                      "¿Puedes decirme cuál estás mirando,")
            )
        return


    # 📷 Si el usuario envía una foto (detectamos modelo automáticamente)
    if update.message.photo:
        f = await update.message.photo[-1].get_file()
        tmp = os.path.join("temp", f"{cid}.jpg")
        os.makedirs("temp", exist_ok=True)
        await f.download_to_drive(tmp)

        # 1️⃣ OCR antes de CLIP
        texto_ocr = extraer_texto_comprobante(tmp)

        # ✅ Cargar carpetas desde Drive (para validación directa)
        carpetas_en_drive = listar_carpetas_drive()

        resultado = detectar_modelo_color(texto_ocr, carpetas_en_drive)

        if resultado:
            modelo_solo = normalize(resultado["modelo"])
            color_detectado = normalize(resultado["color"])

            item = next(
                (i for i in inv if normalize(i["modelo"]) == modelo_solo and normalize(i["color"]) == color_detectado),
                None
            )

            if item:
                est.update({
                    "marca": resultado["marca"],
                    "modelo": resultado["modelo"],
                    "color": resultado["color"],
                    "precio_total": item["precio"],
                    "fase": "esperando_talla"
                })
                estado_usuario[cid] = est
                os.remove(tmp)

                nombre_bonito = f"{resultado['marca']}{resultado['modelo']}"
                precio = item["precio"]

                await ctx.bot.send_message(
                    chat_id=cid,
                    text=(
                        f"🟢 ¡Qué buena elección! Los *{nombre_bonito}* de color *{resultado['color']}* están brutales 😎.\n"
                        f"💲 Su precio es: {precio:,} COP, además el envío es totalmente gratis a todo el país 🚚.\n"
                        f"🎁 Hoy tienes *5 % de descuento* si pagas ahora.\n\n"
                        f"¿Seguimos con la compra?"
                    ),
                    parse_mode="Markdown"
                )
                return




        # 2️⃣ CLIP si OCR falló o no hubo coincidencia en inventario
        with open(tmp, "rb") as f_img:
            base64_img = base64.b64encode(f_img.read()).decode("utf-8")
        os.remove(tmp)

        mensaje = await identificar_modelo_desde_imagen(base64_img)

        if "coincide con *" in mensaje.lower():
            modelo_detectado = re.findall(r"\*(.*?)\*", mensaje)
            if modelo_detectado:
                p = modelo_detectado[0].split("_")
                est.update({
                    "marca": p[0] if len(p) > 0 else "Desconocida",
                    "modelo": p[1] if len(p) > 1 else "Desconocido",
                    "color": p[2] if len(p) > 2 else "Desconocido",
                    "fase": "imagen_detectada",
                })
            await ctx.bot.send_message(
                chat_id=cid,
                text=mensaje + "\n¿Continuamos? (SI/NO)",
                reply_markup=menu_botones(["SI", "NO"]),
                parse_mode="Markdown"
            )
        else:
            reset_estado(cid)
            await ctx.bot.send_message(
                chat_id=cid,
                text="😕 No reconocí el modelo. Puedes intentar con otra imagen o escribir /start.",
                parse_mode="Markdown"
            )
        return



    # 📷 Confirmación si la imagen detectada fue correcta
    if est.get("fase") == "imagen_detectada":

        # 🆕 Pregunta directa por disponibilidad de talla
        consulta_talla = re.search(
            r"(?:tienen|tiene|hay|maneja(?:n)?)\s+talla\s+(\d{1,2})",
            txt
        )
        if consulta_talla:
            talla_pedida = consulta_talla.group(1)
            est["fase"] = "esperando_talla"
            estado_usuario[cid] = est

            ruta = "/var/data/extra/lengueta_ejemplo.jpg"
            if os.path.exists(ruta):
                with open(ruta, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")

                return {
                    "type": "multi",
                    "messages": [
                        {
                            "type": "text",
                            "text": (
                                f"✅ ¡Claro que tenemos talla {talla_pedida}! "
                                "📸 Para confirmar la medida exacta, mándame una foto de la *lengüeta* "
                                "del zapato que usas normalmente 👟."
                            ),
                            "parse_mode": "Markdown"
                        },
                        {
                            "type": "photo",
                            "base64": f"data:image/jpeg;base64,{b64}",
                            "text": "Así debe verse la lengüeta. Envíame una foto parecida 📸"
                        }
                    ]
                }
            else:
                return {
                    "type": "text",
                    "text": (
                        f"✅ ¡Claro que tenemos talla {talla_pedida}! "
                        "📸 Para darte tu talla ideal, mándame una foto de la lengüeta de tu zapato 👟."
                    ),
                    "parse_mode": "Markdown"
                }

        # ✔️ Respuesta afirmativa para avanzar en la compra
        if any(frase in txt for frase in (
            "si", "sí", "sii", "sis", "sisz",
            "de una", "dale", "hagale", "hágale", "hágale pues",
            "claro", "claro que sí", "quiero comprar", "continuar", "vamos"
        )):
            # ✅ Si ya hay talla (desde imagen de lengüeta), saltar a confirmar datos
            if est.get("talla"):
                est["fase"] = "esperando_talla"
                estado_usuario[cid] = est

                await ctx.bot.send_message(
                    chat_id=cid,
                    text=(
                        f"📏 Según la etiqueta que me enviaste, la talla ideal para tus zapatos "
                        f"es *{est['talla']}* en nuestra horma.\n"
                        "¿Deseas que te lo enviemos hoy mismo?"
                    ),
                    parse_mode="Markdown"
                )
                return await procesar_wa(cid, "sí")

            # 🔁 Si aún no tiene talla, pedir foto de lengüeta sin mostrar tallas
            est["fase"] = "esperando_talla"
            estado_usuario[cid] = est

            ruta = "/var/data/extra/lengueta_ejemplo.jpg"
            if os.path.exists(ruta):
                with open(ruta, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                    return {
                        "type": "multi",
                        "messages": [
                            {
                                "type": "text",
                                "text": (
                                    "📸 Para darte tu talla ideal, mándame una foto de la *lengüeta* "
                                    "del zapato que usas normalmente 👟."
                                ),
                                "parse_mode": "Markdown"
                            },
                            {
                                "type": "photo",
                                "base64": f"data:image/jpeg;base64,{b64}",
                                "text": "Así debe verse la lengüeta. Envíame una foto parecida 📸"
                            }
                        ]
                    }
            else:
                return {
                    "type": "text",
                    "text": (
                        "📸 Para darte tu talla ideal, mándame una foto de la lengüeta de tu zapato 👟."
                    ),
                    "parse_mode": "Markdown"
                }

        # ❓ Si no entendió nada útil
        await ctx.bot.send_message(
            chat_id=cid,
            text="Entonces dime cómo te ayudo. Puedes enviar una imagen del producto que deseas 👍🏻",
            parse_mode="Markdown"
        )
        reset_estado(cid)
        return

    # 🛒 Flujo manual si está buscando modelo
    if est.get("fase") == "esperando_modelo":
        modelos = obtener_modelos_por_marca(inv, est["marca"])
        if txt in map(normalize, modelos):
            est["modelo"] = next(m for m in modelos if normalize(m) == txt)
            est["fase"] = "esperando_color"
            colores = obtener_colores_por_modelo(inv, est["modelo"])
            await ctx.bot.send_message(
                chat_id=cid,
                text="¿Qué color deseas?",
                reply_markup=menu_botones(colores),
            )
        else:
            await ctx.bot.send_message(
                chat_id=cid,
                text="Elige un modelo válido.",
                reply_markup=menu_botones(modelos),
            )
        return

    # 🎨 Elegir color del modelo
    if est.get("fase") == "esperando_color":
        colores = obtener_colores_por_modelo(inv, est["modelo"])
        if isinstance(colores, (int, float, str)):
            colores = [str(colores)]

        # Normalizar entrada y colores
        colores_normalizados = {normalize(c): c for c in colores}
        entrada_normalizada = normalize(txt)
        coincidencias = difflib.get_close_matches(entrada_normalizada, colores_normalizados.keys(), n=1, cutoff=0.6)

        if coincidencias:
            color_seleccionado = colores_normalizados[coincidencias[0]]
            est["color"] = color_seleccionado
            est["fase"] = "esperando_talla"

            tallas = obtener_tallas_por_color(inv, est["modelo"], est["color"])
            if isinstance(tallas, (int, float, str)):
                tallas = [str(tallas)]

            await ctx.bot.send_message(
                chat_id=cid,
                text=(
                    f"Tenemos las siguientes tallas disponibles para el modelo *{est['modelo']}* color *{est['color']}*?\n\n"
                    f"👉 Tallas disponibles: {', '.join(tallas)}"
                ),
                parse_mode="Markdown"
            )
        else:
            colores_str = "\n".join(f"- {c}" for c in colores)
            await ctx.bot.send_message(
                chat_id=cid,
                text=(
                    f"⚠️ No entendí ese color.\n\n"
                    f"🎨 Los colores disponibles para *{est['modelo']}* son:\n\n"
                    f"{colores_str}\n\n"
                    "¿Cuál color te interesa?"
                ),
                parse_mode="Markdown"
            )
        return

    # 👟 Evitar repetir análisis de talla si ya tenemos la talla definida
    if est.get("fase") == "esperando_talla" and est.get("talla"):
        cliente = obtener_datos_cliente(numero)

        # SOLO si existe memoria, mostrar resumen. Si no, pedir nombre
        if not cliente:
            est["fase"] = "esperando_nombre"
            estado_usuario[cid] = est
            await ctx.bot.send_message(
                chat_id=cid,
                text="¿Tu nombre completo para el pedido? 📝",
                parse_mode="Markdown"
            )
            return

        nombre    = cliente.get("nombre", "cliente")
        correo    = cliente.get("correo", "No registrado")
        telefono  = cliente.get("telefono", numero)
        cedula    = cliente.get("cedula", "No registrada")
        ciudad    = cliente.get("ciudad", "No registrada")
        provincia = cliente.get("provincia", "No registrada")
        direccion = cliente.get("direccion", "No registrada")

        est.update({
            "nombre": nombre,
            "correo": correo,
            "telefono": telefono,
            "cedula": cedula,
            "ciudad": ciudad,
            "provincia": provincia,
            "direccion": direccion
        })

        precio = next(
            (i["precio"] for i in inv
             if normalize(i["marca"]) == normalize(est.get("marca", ""))
             and normalize(i["modelo"]) == normalize(est.get("modelo", ""))
             and normalize(i["color"])  == normalize(est.get("color", ""))),
            None
        )
        est["precio_total"] = int(precio) if precio else 0
        est["sale_id"] = generate_sale_id()

        est["resumen"] = {
            "Número Venta": est["sale_id"],
            "Fecha Venta": datetime.now().isoformat(),
            "Cliente": est.get("nombre", "cliente"),
            "Teléfono": est.get("telefono"),
            "Cédula": est.get("cedula"),
            "Producto": est.get("modelo"),
            "Color": est.get("color"),
            "Talla": est.get("talla"),
            "Correo": est.get("correo"),
            "Pago": None,
            "Estado": "PENDIENTE"
        }

        resumen_msg = (
            f"✅ Pedido: {est['sale_id']}\n"
            f"👤Nombre: {est.get('nombre')}\n"
            f"📧Correo: {est.get('correo')}\n"
            f"📱Celular: {est.get('telefono')}\n"
            f"🪪Cédula: {est.get('cedula')}\n"
            f"📍Dirección: {est.get('direccion')}, {est.get('ciudad')}, {est.get('provincia')}\n"
            f"👟Producto: {est['modelo']} color {est['color']} talla {est['talla']}\n"
            f"💲Valor a pagar: {est['precio_total']:,} COP\n\n"
            "¿Estos datos siguen siendo correctos o deseas cambiar algo?\n"
            "• Responde *sí* si todo está bien.\n"
            "• O dime el campo a cambiar (nombre, correo, teléfono, etc.)."
        )

        est["fase"] = "confirmar_datos_guardados"
        est["confirmacion_pendiente"] = True
        estado_usuario[cid] = est
        await ctx.bot.send_message(chat_id=cid, text=resumen_msg, parse_mode="Markdown")
        return

    # 👟 Elegir talla escrita (y pedir lengüeta)
    if est.get("fase") == "esperando_talla":
        tallas_disponibles = obtener_tallas_por_color(inv, est.get("modelo", ""), est.get("color", ""))
        if isinstance(tallas_disponibles, (int, float, str)):
            tallas_disponibles = [str(tallas_disponibles)]

        # Normalización y coincidencia difusa
        tallas_normalizadas = {normalize(t): t for t in tallas_disponibles}
        entrada_normalizada = normalize(txt)

        coincidencias = difflib.get_close_matches(entrada_normalizada, tallas_normalizadas.keys(), n=1, cutoff=0.6)

        if coincidencias:
            talla_detectada = tallas_normalizadas[coincidencias[0]]
            est["talla"] = talla_detectada
            estado_usuario[cid] = est

            ruta = "/var/data/extra/lengueta_ejemplo.jpg"
            if os.path.exists(ruta):
                with open(ruta, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                return {
                    "type": "multi",
                    "messages": [
                        {
                            "type": "text",
                            "text": (
                                f"✅ ¡Claro que tenemos talla {talla_detectada}! "
                                "📸 Para confirmar la medida exacta, mándame una foto de la *lengüeta* "
                                "del zapato que usas normalmente 👟."
                            ),
                            "parse_mode": "Markdown"
                        },
                        {
                            "type": "photo",
                            "base64": f"data:image/jpeg;base64,{b64}",
                            "text": "Así debe verse la lengüeta. Envíame una foto parecida 📸"
                        }
                    ]
                }

            return {
                "type": "text",
                "text": (
                    f"✅ ¡Claro que tenemos talla {talla_detectada}! "
                    "📸 Por favor mándame una foto de la lengüeta de tu zapato para asegurarnos de la talla correcta 👟."
                ),
                "parse_mode": "Markdown"
            }

        # ❌ No entendió ninguna talla, mostrar disponibles
        tallas_str = "\n".join(f"- {t}" for t in tallas_disponibles)
        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                "Mandame tu lengüeta pa que confirmemos el pedido.\n\n"
            ),
            parse_mode="Markdown"
        )
        return

    # 👟 Elegir talla (texto directo o confirmación de lengüeta)
    if est.get("fase") == "esperando_talla":
        tallas = obtener_tallas_por_color(inv, est["modelo"], est["color"])
        if isinstance(tallas, (int, float, str)):
            tallas = [str(tallas)]

        # 🟢 1. Si ya hay una talla detectada (por imagen) y cliente confirma con "sí"
        if est.get("talla") and any(p in txt for p in ("sí", "si", "s", "dale", "claro", "continuar", "comprar", "vamos")):
            talla_detectada = est["talla"]

        # 🟡 2. Si escribió la talla manualmente
        else:
            talla_detectada = detectar_talla(txt_raw, tallas)

        if talla_detectada:
            est["talla"] = talla_detectada

            # 🔍 Ver si ya hay memoria del cliente
            cliente = obtener_datos_cliente(numero)

            if cliente:
                nombre    = cliente.get("nombre", "cliente")
                correo    = cliente.get("correo", "No registrado")
                telefono  = cliente.get("telefono", numero)
                cedula    = cliente.get("cedula", "No registrada")
                ciudad    = cliente.get("ciudad", "No registrada")
                provincia = cliente.get("provincia", "No registrada")
                direccion = cliente.get("direccion", "No registrada")

                est.update({
                    "nombre": nombre,
                    "correo": correo,
                    "telefono": telefono,
                    "cedula": cedula,
                    "ciudad": ciudad,
                    "provincia": provincia,
                    "direccion": direccion
                })

                precio = next(
                    (i["precio"] for i in inv
                     if normalize(i["marca"]) == normalize(est["marca"])
                     and normalize(i["modelo"]) == normalize(est["modelo"])
                     and normalize(i["color"]) == normalize(est["color"])),
                    None
                )
                est["precio_total"] = int(precio) if precio else 0
                est["sale_id"] = generate_sale_id()

                resumen = (
                    f"✅ Pedido: {est['sale_id']}\n"
                    f"👤Nombre: {nombre}\n"
                    f"📧Correo: {correo}\n"
                    f"📱Celular: {telefono}\n"
                    f"🪪Cédula: {cedula}\n"
                    f"📍Dirección: {direccion}, {ciudad}, {provincia}\n"
                    f"👟Producto: {est['modelo']} color {est['color']} talla {est['talla']}\n"
                    f"💲Valor a pagar: {est['precio_total']:,} COP\n\n"
                    "¿Estos datos siguen siendo correctos o deseas cambiar algo?"
                )

                est["fase"] = "confirmar_datos_guardados"
                estado_usuario[cid] = est
                await ctx.bot.send_message(chat_id=cid, text=resumen, parse_mode="Markdown")
                return

            # 🧾 No hay cliente guardado → continuar normal
            est["fase"] = "esperando_nombre"
            estado_usuario[cid] = est
            await ctx.bot.send_message(
                chat_id=cid,
                text="¿Tu nombre completo para el pedido?",
                parse_mode="Markdown"
            )
            return

        # 🚫 No se detectó ninguna talla → mostrar tallas y pedir imagen
        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                f"Tenemos las siguientes tallas disponibles para el modelo *{est['modelo']}* color *{est['color']}*:\n\n"
                f"👉 Tallas disponibles: {', '.join(tallas)}\n\n"
                "📸 Para darte tu *talla ideal*, mándame una foto de la *lengüeta de tu zapato* 👟 y la detectamos automáticamente."
            ),
            parse_mode="Markdown"
        )
        return

    # 👤 Confirmar o editar datos guardados
    if est.get("fase") == "confirmar_datos_guardados":
        if est.get("confirmacion_pendiente"):
            if any(p in txt.lower() for p in (
                "si", "sí", "correcto", "ok", "listo", "vale", "dale",
                "todo bien", "todo correcto", "está bien", "esta bien"
            )):
                est["confirmacion_pendiente"] = False
                est["fase"] = "esperando_pago"

                # 🛠 Verificar datos antes de buscar precio (solo si no existe)
                marca  = normalize(est.get("marca", ""))
                modelo = normalize(est.get("modelo", ""))
                color  = normalize(est.get("color", ""))

                if (est.get("precio_total", 0) == 0) and marca and modelo:
                    item = next(
                        (i for i in inv if
                            normalize(i["marca"]) == marca and
                            normalize(i["modelo"]) == modelo and
                            (not color or normalize(i["color"]) == color)),
                        None
                    )
                    if item:
                        est["precio_total"] = int(item["precio"])

                precio = est.get("precio_total", 0)
                est["sale_id"] = est.get("sale_id") or generate_sale_id()

                est["resumen"] = {
                    "Número Venta": est["sale_id"],
                    "Fecha Venta": datetime.now().isoformat(),
                    "Cliente": est.get("nombre"),
                    "Teléfono": est.get("telefono"),
                    "Cédula": est.get("cedula"),
                    "Producto": est.get("modelo"),
                    "Color": est.get("color"),
                    "Talla": est.get("talla"),
                    "Correo": est.get("correo"),
                    "Pago": None,
                    "Estado": "PENDIENTE"
                }

                msg = (
                    f"✅ Pedido: {est['sale_id']}\n"
                    f"👤Nombre: {est['nombre']}\n"
                    f"📧Correo: {est['correo']}\n"
                    f"📱Celular: {est['telefono']}\n"
                    f"📍Dirección: {est['direccion']}, {est['ciudad']}, {est['provincia']}\n"
                    f"👟Producto: {est['modelo']} color {est['color']} talla {est['talla']}\n"
                    f"💲Valor a pagar: {precio:,} COP\n\n"
                    "😊 Tenemos *4 formas de pago* 💰\n\n"
                    "1. 💵 *Pago anticipado* (Nequi, Daviplata, Bancolombia):\n"
                    "   Pagas el valor completo antes del envío y tu compra queda asegurada 🚀.\n\n"
                    "2. ✈️ *Pago contra entrega*:\n"
                    "   Haces un abono de *$30.000* y el restante lo pagas a la transportadora al recibir tu calzado.\n\n"
                    "3. 💳 *Tarjeta de crédito*:\n"
                    "   Paga online con tu tarjeta desde el enlace que te enviamos (Visa, MasterCard, etc.).\n\n"
                    "4. 💙 *Crédito a cuotas por medio de Addi*:\n"
                    "   Financia tu compra y paga en cuotas mensuales de forma fácil y rápida.\n\n"
                    "🤩 ¿Por cuál medio te queda más fácil hacer el pago?\n"
                    "Escribe: *Pago anticipado*, *Contraentrega*, *Tarjeta* o *Addi*."
                )
                await ctx.bot.send_message(chat_id=cid, text=msg, parse_mode="Markdown")
                estado_usuario[cid] = est
                return
            else:
                await ctx.bot.send_message(
                    chat_id=cid,
                    text="¿Si los datos están correctos? ✅\nDime que *sí* y continuamos con la compra o dime qué campo deseas actualizar (nombre, ciudad, etc.)",
                    parse_mode="Markdown"
                )
                return


        # B) Detectar qué campo desea cambiar
        campos = {
            "nombre": ["nombre"],
            "correo": ["correo", "email", "mail"],
            "telefono": ["telefono", "teléfono", "celular", "cel"],
            "cedula": ["cedula", "cédula", "dni", "id"],
            "ciudad": ["ciudad"],
            "provincia": ["provincia", "departamento"],
            "direccion": ["direccion", "dirección", "dir"]
        }
        for campo, alias in campos.items():
            if any(a in txt for a in alias):
                est["campo_a_editar"] = campo
                est["fase"] = "editando_dato"
                await ctx.bot.send_message(
                    chat_id=cid,
                    text=f"Por favor escribe el nuevo *{campo}* 📝",
                    parse_mode="Markdown"
                )
                return

        await ctx.bot.send_message(
            chat_id=cid,
            text="Indícame qué dato deseas cambiar (nombre, correo, teléfono, ciudad, etc.).",
            parse_mode="Markdown"
        )
        return




    # 💾 Guardar nuevo valor editado
    if est.get("fase") == "editando_dato":
        campo = est.get("campo_a_editar")

        if campo == "correo" and not re.match(r"[^@]+@[^@]+\.[^@]+", txt_raw):
            await ctx.bot.send_message(
                chat_id=cid,
                text="⚠️ Ese correo no parece válido. Intenta con nombre@dominio.com",
                parse_mode="Markdown"
            )
            return
        if campo == "telefono" and not re.match(r"^\+?\d{7,15}$", txt_raw):
            await ctx.bot.send_message(
                chat_id=cid,
                text="⚠️ Ese teléfono no es válido. Incluye solo números y, opcional, el +57.",
                parse_mode="Markdown"
            )
            return

        est[campo] = txt_raw.strip()
        est.pop("campo_a_editar", None)
        est["fase"] = "confirmar_datos_guardados"

        resumen = (
            f"🔄 *Datos actualizados:*\n\n"
            f"👤Nombre: {est.get('nombre')}\n"
            f"📧Correo: {est.get('correo')}\n"
            f"📱Celular: {est.get('telefono')}\n"
            f"🪪Cédula: {est.get('cedula')}\n"
            f"📍Dirección: {est.get('direccion')}, {est.get('ciudad')}, {est.get('provincia')}\n"
            f"👟Producto: {est['modelo']} color {est['color']} talla {est['talla']}\n"
            f"💲Valor a pagar: {est['precio_total']:,} COP\n\n"
            "¿Todo correcto o quieres cambiar otro dato?"
        )
        await ctx.bot.send_message(chat_id=cid, text=resumen, parse_mode="Markdown")
        return


    # ✏️ Nombre del cliente
    if est.get("fase") == "esperando_nombre":
        est["nombre"] = txt_raw
        est["fase"] = "esperando_correo"
        await ctx.bot.send_message(
            chat_id=cid,
            text="¿Cuál es tu correo electrónico? 📧",
            parse_mode="Markdown"
        )
        return

    # 📧 Correo del cliente
    if est.get("fase") == "esperando_correo":
        if re.match(r"[^@]+@[^@]+\.[^@]+", txt_raw):
            est["correo"] = txt_raw
            est["fase"] = "esperando_telefono"
            await ctx.bot.send_message(
                chat_id=cid,
                text="¿Tu número de teléfono? 📱",
                parse_mode="Markdown"
            )
        else:
            await ctx.bot.send_message(
                chat_id=cid,
                text="Mandame tu correo pa que sigamos con la compra😊.",
                parse_mode="Markdown"
            )
        return

    # 📞 Teléfono del cliente
    if est.get("fase") == "esperando_telefono":
        if re.match(r"^\+?\d{7,15}$", txt_raw):
            est["telefono"] = txt_raw
            est["fase"] = "esperando_cedula"
            await ctx.bot.send_message(
                chat_id=cid,
                text="¿Tu número de cédula? 🪪",
                parse_mode="Markdown"
            )
        else:
            await ctx.bot.send_message(
                chat_id=cid,
                text="Este no parece un telefono real manda el tuyo porfa.",
                parse_mode="Markdown"
            )
        return

    # 🪪 Cédula del cliente
    if est.get("fase") == "esperando_cedula":
        if re.match(r"^\d{5,15}$", txt_raw):
            est["cedula"] = txt_raw
            est["fase"] = "esperando_ciudad"
            await ctx.bot.send_message(
                chat_id=cid,
                text="¿En qué ciudad estás? 🏙️",
                parse_mode="Markdown"
            )
        else:
            await ctx.bot.send_message(
                chat_id=cid,
                text="⚠️ Tu cedula real para el pedido porfavor.",
                parse_mode="Markdown"
            )
        return

    # 🌆 Ciudad del cliente
    if est.get("fase") == "esperando_ciudad":
        est["ciudad"] = txt_raw
        est["fase"] = "esperando_provincia"
        await ctx.bot.send_message(
            chat_id=cid,
            text="¿En qué departamento o provincia estás? 🏞️",
            parse_mode="Markdown"
        )
        return

    # 🏞️ Provincia del cliente
    if est.get("fase") == "esperando_provincia":
        est["provincia"] = txt_raw
        est["fase"] = "esperando_direccion"
        await ctx.bot.send_message(
            chat_id=cid,
            text="¿Dirección exacta de envío? 🏡",
            parse_mode="Markdown"
        )
        return

    # 🏡 Dirección de envío
    if est.get("fase") == "esperando_direccion":
        est["direccion"] = txt_raw.strip()

        # Guardar cliente
        actualizar_cliente(numero, {
            "nombre": est.get("nombre"),
            "correo": est.get("correo"),
            "telefono": est.get("telefono"),
            "cedula": est.get("cedula"),
            "ciudad": est.get("ciudad"),
            "provincia": est.get("provincia"),
            "direccion": est.get("direccion")
        })

        precio = next(
            (
                i["precio"] for i in inv
                if normalize(i["marca"]) == normalize(est["marca"])
                and normalize(i["modelo"]) == normalize(est["modelo"])
                and normalize(i["color"]) == normalize(est["color"])
            ),
            None
        )
        if precio is None:
            await ctx.bot.send_message(
                chat_id=cid,
                text="No pude obtener el precio, intenta de nuevo."
            )
            return

        est["precio_total"] = int(precio)
        est.setdefault("talla", "—")
        est["sale_id"] = est.get("sale_id") or generate_sale_id()

        est["resumen"] = {
            "Número Venta": est["sale_id"],
            "Fecha Venta": datetime.now().isoformat(),
            "Cliente": est["nombre"],
            "Teléfono": est["telefono"],
            "Cédula": est["cedula"],
            "Producto": est["modelo"],
            "Color": est["color"],
            "Talla": est["talla"],
            "Correo": est["correo"],
            "Pago": None,
            "Estado": "PENDIENTE"
        }

    # ────────────────────────────────────────────────
    # 💳 MÉTODO DE PAGO – RESUMEN PERSONALIZADO
    # ────────────────────────────────────────────────
    if est.get("fase") == "resumen_compra":
        msg = (
            f"✅ Pedido: {est['sale_id']}\n"
            f"👤Nombre: {est['nombre']}\n"
            f"📧Correo: {est['correo']}\n"
            f"📱Celular: {est['telefono']}\n"
            f"📍Dirección: {est['direccion']}, {est['ciudad']}, {est['provincia']}\n"
            f"👟Producto: {est['modelo']} color {est['color']} talla {est['talla']}\n"
            f"💲Valor a pagar: {est['precio_total']:,} COP\n\n"
        )

        if est.get("es_de_bucaramanga"):
            msg += (
                "📍 Como estás en *Bucaramanga*, puedes elegir:\n"
                "• 🛵 *Domicilio*: te lo llevamos y pagas al recibir\n"
                "• 🏪 *Tienda*: puedes pasar a recogerlo tú mismo\n\n"
                "¿Qué prefieres? Escribe *domicilio* o *tienda*"
            )
            est["fase"] = "esperando_metodo_bucaramanga"
        else:
            msg += (
                "😊 Tenemos *4 formas de pago* 💰\n\n"
                "1. 💵 *Pago anticipado* (Nequi, Daviplata, Bancolombia):\n"
                "   Pagas el valor completo antes del envío y tu compra queda asegurada 🚀.\n\n"
                "2. ✈️ *Pago contra entrega*:\n"
                "   Haces un abono de *$30.000* y el restante lo pagas a la transportadora al recibir tu calzado.\n\n"
                "3. 💳 *Tarjeta de crédito*:\n"
                "   Paga online con tu tarjeta desde el enlace que te enviamos (Visa, MasterCard, etc.).\n\n"
                "4. 💙 *Crédito a cuotas por medio de Addi*:\n"
                "   Financia tu compra y paga en cuotas mensuales de forma fácil y rápida.\n\n"
                "🤩 ¿Por cuál medio te queda más fácil hacer el pago?\n"
                "Escribe: *Pago anticipado*, *Contraentrega*, *Tarjeta* o *Addi*."
            )
            est["fase"] = "esperando_pago"

        await ctx.bot.send_message(chat_id=cid, text=msg, parse_mode="Markdown")
        estado_usuario[cid] = est
        return


    # ────────────────────────────────────────────────
    # 💳 MÉTODO DE PAGO – ELECCIÓN
    # ────────────────────────────────────────────────
    if est.get("fase") == "esperando_pago":
        opciones = {
            "transferencia": [
                "transferencia", "trasferencia", "transf", "trans", "pago inmediato", "qr",
                "nequi", "davivienda", "daviplata", "bancolombia", "pse"
            ],
            "contraentrega": [
                "contraentrega", "contra entrega", "contra", "contrapago"
            ],
            "addi": [
                "addi", "pagar con addi", "credito", "crédito", "financiacion", "financiación"
            ],
            "tarjeta": [
                "tarjeta", "tarjeta de credito", "tarjeta de crédito", "pago con tarjeta", "visa", "mastercard"
            ]
        }
        txt_normalizado = normalize(txt_raw)
        metodo_detectado = None
        for metodo, alias in opciones.items():
            if difflib.get_close_matches(txt_normalizado, alias, n=1, cutoff=0.6):
                metodo_detectado = metodo
                break

        if not metodo_detectado:
            await ctx.bot.send_message(
                chat_id=cid,
                text="💳 Dime porfa cómo deseas pagar: *pago anticipado*, *transferencia*, *nequi*, *daviplata*, *bancolombia*, *tarjeta*, *contraentrega* o *Addi* 😊",
                parse_mode="Markdown"
            )
            return

        resumen = est["resumen"]
        precio_original = est["precio_total"]

        if metodo_detectado == "transferencia":
            est["fase"] = "esperando_comprobante"
            est["metodo_pago"] = "Transferencia"
            descuento = round(precio_original * 0.05)
            valor_final = precio_original - descuento

            resumen.update({
                "Pago": "Transferencia",
                "Descuento": f"-{descuento} COP",
                "Valor Final": valor_final
            })

            estado_usuario[cid] = est
            msg = (
                "🟢 Elegiste *Pago anticipado* (Nequi, Daviplata, Bancolombia, Davivienda).\n\n"
                f"💰 Valor original: {precio_original:,} COP\n"
                f"🎉 Descuento 5 %: -{descuento:,} COP\n"
                f"✅ Total a pagar: {valor_final:,} COP\n\n"
                "💳 Cuentas:\n"
                "- Bancolombia 30300002233 (X100 SAS)\n"
                "- Nequi 317 717 1171\n"
                "- Daviplata 300 414 1021\n"
                "- Davivienda 0066000000 (ejemplo)\n\n"
                "📸 Envía aquí la foto del comprobante."
            )
            await ctx.bot.send_message(chat_id=cid, text=msg, parse_mode="Markdown")
            return

        elif metodo_detectado == "contraentrega":
            est["fase"] = "esperando_comprobante"
            est["metodo_pago"] = "Contraentrega"
            resumen.update({
                "Pago": "Contra entrega",
                "Valor Anticipo": 30000
            })

            estado_usuario[cid] = est
            msg = (
                "🟡 Elegiste *CONTRAENTREGA*.\n\n"
                "Debes adelantar *30 000 COP* para el envío (se descuenta del total).\n\n"
                "💳 Cuentas:\n"
                "- Bancolombia 30300002233 (X100 SAS)\n"
                "- Nequi 317 717 1171\n"
                "- Daviplata 300 414 1021\n"
                "- Davivienda 0066000000 (ejemplo)\n\n"
                "📸 Envía aquí la foto del comprobante."
            )
            await ctx.bot.send_message(chat_id=cid, text=msg, parse_mode="Markdown")
            return

        # ────────────────────────────────────────────────
        # 💳 DETECTÓ MÉTODO "Addi"
        # ────────────────────────────────────────────────
        elif metodo_detectado == "addi":
            est["fase"] = "esperando_datos_addi"
            est["metodo_pago"] = "Addi"
            estado_usuario[cid] = est

            await ctx.bot.send_message(
                chat_id=cid,
                text=(
                    "🟦 Elegiste *Addi* para financiar tu compra.\n\n"
                    "Por favor envíame los siguientes datos (cada uno en una línea):\n"
                    "1️⃣ Nombre completo\n"
                    "2️⃣ Número de cédula\n"
                    "3️⃣ Correo electrónico\n"
                    "4️⃣ Teléfono WhatsApp\n\n"
                    "_La aprobación está sujeta a políticas de Addi y centrales de riesgo._"
                ),
                parse_mode="Markdown"
            )
            return   # ← nada más se procesa en esta vuelta

        elif metodo_detectado == "tarjeta":
            est["fase"] = "esperando_comprobante"
            est["metodo_pago"] = "Tarjeta"
            resumen.update({
                "Pago": "Tarjeta de crédito",
                "Valor": precio_original
            })

            estado_usuario[cid] = est
            msg = (
                "💳 Elegiste *tarjeta de crédito*.\n\n"
                f"💰 Valor a pagar: {precio_original:,} COP\n\n"
                "Te enviaré un enlace para pagar con tu tarjeta Visa, MasterCard o similar.\n"
                "Avísame si tienes alguna preferencia o requieres ayuda con el proceso."
            )
            await ctx.bot.send_message(chat_id=cid, text=msg, parse_mode="Markdown")
            return


    # ────────────────────────────────────────────────────────────────
    # ⏸️  PAUSA GLOBAL DEL CHAT (si un humano debe continuar)
    # ────────────────────────────────────────────────────────────────
    if est.get("pausa_hasta"):
        pausa_hasta = datetime.fromisoformat(est["pausa_hasta"])
        if datetime.now() < pausa_hasta:
            logging.info(f"[PAUSA] Chat {cid} pausado hasta {pausa_hasta}")
            return {
                "type": "text",
                "text": "⏸️ Un asesor está procesando tu solicitud. Te contactarán pronto."
            }
        else:
            # La pausa expiró → reiniciamos el flujo
            est.pop("pausa_hasta", None)
            if est.get("fase", "").startswith("pausado_"):
                est["fase"] = "inicial"
            estado_usuario[cid] = est

    # ────────────────────────────────────────────────────────────────
    # 📋 DATOS PARA ADDI – VERSIÓN TOLERANTE
    # ────────────────────────────────────────────────────────────────
    if est.get("fase") == "esperando_datos_addi":
        try:
            # 1. Separa en líneas no vacías
            partes = [p.strip() for p in txt_raw.splitlines() if p.strip()]

            # 2. Necesitamos exactamente 4 líneas con algún contenido
            if len(partes) < 4:
                await ctx.bot.send_message(
                    chat_id=cid,
                    text=(
                        "❌ *Faltan datos.*\n\n"
                        "Envíame 4 líneas así:\n"
                        "1️⃣ Nombre completo\n2️⃣ Cédula\n3️⃣ Correo\n4️⃣ Teléfono WhatsApp"
                    ),
                    parse_mode="Markdown"
                )
                return  # sigue esperando

            nombre, cedula, correo, telefono = partes[:4]

            datos_addi = {
                "Cliente":   nombre.title(),
                "Cédula":    cedula,
                "Teléfono":  telefono,
                "Correo":    correo,
                "Fecha":     datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            if registrar_orden_unificada(datos_addi, destino="ADDI"):
                await ctx.bot.send_message(
                    chat_id=cid,
                    text=(
                        "✅ ¡Gracias! Tus datos fueron enviados a Addi.\n"
                        "Enseguida me comunico para seguir el proceso. 💙"
                    )
                )
                est["fase"] = "pausado_addi"
                est["pausa_hasta"] = (datetime.now() + timedelta(hours=24)).isoformat()
                estado_usuario[cid] = est
            else:
                await ctx.bot.send_message(
                    chat_id=cid,
                    text="⚠️ No pudimos registrar tus datos. Intenta nuevamente más tarde."
                )
            return

        except Exception as e:
            logging.error(f"[ADDI] ❌ Error registrando datos: {e}")
            await ctx.bot.send_message(
                chat_id=cid,
                text="❌ Hubo un error procesando tus datos para Addi. Intenta de nuevo más tarde."
            )
            return


    # 📸 Recibir comprobante de pago
    if est.get("fase") == "esperando_comprobante" and update.message.photo:
        try:
            f = await update.message.photo[-1].get_file()
            tmp = os.path.join("temp", f"{cid}_proof.jpg")
            os.makedirs("temp", exist_ok=True)
            await f.download_to_drive(tmp)

            with io.open(tmp, "rb") as image_file:
                content = image_file.read()
            image = vision.Image(content=content)
            response = vision_client.text_detection(image=image)
            textos_detectados = response.text_annotations

            texto_extraido = textos_detectados[0].description if textos_detectados else ""
            print("🧾 TEXTO EXTRAÍDO:\n", texto_extraido)

            if not es_comprobante_valido(texto_extraido):
                await ctx.bot.send_message(
                    chat_id=cid,
                    text="⚠️ El comprobante no parece válido. Asegúrate de que sea legible y que diga *Pago exitoso*.",
                    parse_mode="Markdown"
                )
                os.remove(tmp)
                return

            # Enviar correos (si aplica)
            try:
                enviar_correo(
                    est["correo"],
                    f"Pago recibido {est['resumen']['Número Venta']}",
                    json.dumps(est["resumen"], indent=2)
                )
                enviar_correo_con_adjunto(
                    EMAIL_JEFE,
                    f"Comprobante {est['resumen']['Número Venta']}",
                    json.dumps(est["resumen"], indent=2),
                    tmp
                )
            except Exception as e:
                logging.warning(f"📧 Error al enviar correos: {e}")

            # ✅ Registrar en hoja PEDIDOS como completado
            resumen_final = est.get("resumen", {})
            resumen_final["fase_actual"] = "Finalizado"
            resumen_final["Estado"] = "COMPLETADO"
            registrar_orden_unificada(resumen_final, destino="PEDIDOS")

            os.remove(tmp)

            await ctx.bot.send_message(
                chat_id=cid,
                text="✅ ¡Pago registrado exitosamente! Tu pedido está en proceso. 🚚"
            )

            await enviar_sticker(ctx, cid, "sticker_fin_de_compra_gracias.webp")

            reset_estado(cid)
            estado_usuario.pop(cid, None)
            return

        except Exception as e:
            logging.error(f"❌ Error al procesar comprobante: {e}")
            await ctx.bot.send_message(
                chat_id=cid,
                text="❌ No pude procesar el comprobante. Intenta con otra imagen.",
                parse_mode="Markdown"
            )
            return






    # 🚚 Rastrear pedido
    if est.get("fase") == "esperando_numero_rastreo":
        await ctx.bot.send_message(
            chat_id=cid,
            text="📦 Puedes rastrear tu pedido aquí:\nhttps://www.instagram.com/juanp_ocampo/",
            parse_mode="Markdown"
        )
        reset_estado(cid)
        return

    # 🔄 Solicitud de devolución
    if est.get("fase") == "esperando_numero_devolucion":
        est["referencia"] = txt_raw.strip()
        est["fase"] = "esperando_motivo_devolucion"
        await ctx.bot.send_message(
            chat_id=cid,
            text="📝 ¿Cuál es el motivo de la devolución?",
            parse_mode="Markdown"
        )
        return

    if est.get("fase") == "esperando_motivo_devolucion":
        enviar_correo(
            EMAIL_DEVOLUCIONES,
            f"Solicitud de Devolución {NOMBRE_NEGOCIO}",
            f"Venta: {est['referencia']}\nMotivo: {txt_raw}"
        )
        await ctx.bot.send_message(
            chat_id=cid,
            text="✅ Solicitud de devolución enviada exitosamente.",
            parse_mode="Markdown"
        )
        reset_estado(cid)
        return

    # 🎙️ Procesar audio
    if update.message.voice or update.message.audio:
        fobj = update.message.voice or update.message.audio
        tg_file = await fobj.get_file()
        local_path = os.path.join(TEMP_AUDIO_DIR, f"{cid}_{tg_file.file_id}.ogg")
        await tg_file.download_to_drive(local_path)
        txt_raw = await transcribe_audio(local_path)
        os.remove(local_path)

        if not txt_raw:
            await update.message.reply_text(
                "Ese audio se escucha muy mal 😕. ¿Podrías enviarlo de nuevo o escribir tu mensaje?",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        txt = normalize(txt_raw)

    # 💬 Manejar precio por referencia
    if await manejar_precio(update, ctx, inv):
        return

    # 🛒 Confirmación para continuar con compra después de ver precios
    if est.get("fase") == "confirmar_compra":
        if txt in ("si", "sí", "si quiero comprar", "sí quiero comprar", "quiero comprar", "comprar", "dale", "SI", "De una", "claro"):
            modelo = est.get("modelo_confirmado")
            color_confirmado = est.get("color_confirmado")

            if not modelo:
                await ctx.bot.send_message(
                    chat_id=cid,
                    text="❌ No encontré el modelo que seleccionaste. Vuelve a escribirlo o envíame una imagen.",
                    parse_mode="Markdown"
                )
                est["fase"] = "inicio"
                estado_usuario[cid] = est
                return

            est["modelo"] = modelo

            colores = obtener_colores_por_modelo(inv, modelo)
            if isinstance(colores, (int, float, str)):
                colores = [str(colores)]

            if len(colores) == 1:
                est["color"] = colores[0]
                est["fase"] = "esperando_talla"
                tallas = obtener_tallas_por_color(inv, modelo, colores[0])
                if isinstance(tallas, (int, float, str)):
                    tallas = [str(tallas)]

                await ctx.bot.send_message(
                    chat_id=cid,
                    text=f"Tenemos las siguientes tallas disponibles para el modelo *{modelo}* color *{colores[0]}*?\n👉 Tallas disponibles: {', '.join(tallas)}",
                    parse_mode="Markdown"
                )
            else:
                est["fase"] = "esperando_color"
                colores_str = "\n".join(f"- {c}" for c in colores)
                await ctx.bot.send_message(
                    chat_id=cid,
                    text=f"🎨 El modelo *{modelo}* está disponible en varios colores:\n\n{colores_str}\n\n¿Cuál color te interesa?",
                    parse_mode="Markdown"
                )

            estado_usuario[cid] = est
            return

        else:
            await ctx.bot.send_message(
                chat_id=cid,
                text="No hay problema. Si deseas, puedes ver nuestro catálogo completo 📋.\n👉 https://wa.me/c/573246666652",
                parse_mode="Markdown"
            )
            est["fase"] = "inicio"
            estado_usuario[cid] = est
            return


    # 🔄 Si el usuario dice “sí” antes de confirmar compra (por fuera del flujo)
    if "sí" in txt_raw or "claro" in txt_raw or "dale" in txt_raw or "quiero" in txt_raw:
        modelo = est.get("modelo_confirmado")
        if not modelo:
            await ctx.bot.send_message(
                chat_id=cid,
                text="❌ No encontré el modelo que seleccionaste. Vuelve a escribirlo o envíame una imagen.",
                parse_mode="Markdown"
            )
            est["fase"] = "inicio"
            return

        colores = obtener_colores_por_modelo(inventario, modelo)

        # Caso único color
        if len(colores) == 1:
            est["modelo"] = modelo
            est["color"] = colores[0]
            est["fase"] = "esperando_talla"

            tallas = obtener_tallas_por_color(inventario, modelo, colores[0])
            await ctx.bot.send_message(
                chat_id=cid,
                text=f"Perfecto 👌 ¿Qué talla deseas para el modelo *{modelo}* color *{colores[0]}*? 👟📏",
                parse_mode="Markdown",
                reply_markup=menu_botones(tallas),
            )
            return

        # Caso múltiples colores
        est["modelo"] = modelo
        est["fase"] = "esperando_color"

        await ctx.bot.send_message(
            chat_id=cid,
            text=f"🎨 ¿Qué color deseas para el modelo *{modelo}*?",
            parse_mode="Markdown",
            reply_markup=menu_botones(colores),
        )
        return

    # 🖼️ Procesar imagen subida si estaba esperando
    if est.get("fase") == "esperando_imagen" and update.message.photo:
        f = await update.message.photo[-1].get_file()
        tmp = os.path.join("temp", f"{cid}.jpg")
        os.makedirs("temp", exist_ok=True)
        await f.download_to_drive(tmp)

        with open(tmp, "rb") as f_img:
            base64_img = base64.b64encode(f_img.read()).decode("utf-8")
        os.remove(tmp)

        mensaje = await identificar_modelo_desde_imagen(base64_img)

        if "coincide con *" in mensaje.lower():
            modelo_detectado = re.findall(r"\*(.*?)\*", mensaje)
            if modelo_detectado:
                p = modelo_detectado[0].split("_")
                est.update({
                    "marca":  p[0] if len(p) > 0 else "Desconocida",
                    "modelo": p[1] if len(p) > 1 else "Desconocido",
                    "color":  p[2] if len(p) > 2 else "Desconocido",
                    "fase":   "imagen_detectada",
                })
            await ctx.bot.send_message(
                chat_id=cid,
                text=mensaje + "\n¿Continuamos? (SI/NO)",
                reply_markup=menu_botones(["SI", "NO"]),
                parse_mode="Markdown"
            )
        else:
            reset_estado(cid)
            await ctx.bot.send_message(
                chat_id=cid,
                text="😕 No reconocí el modelo en la imagen. Intenta con otra o escribe /start.",
                parse_mode="Markdown"
            )
        return

    # 🛍️ Detectar marca escrita
    marcas = obtener_marcas_unicas(inv)
    elegida = next((m for m in marcas if any(t in txt for t in normalize(m).split())), None)

    if not elegida:
        tokens = txt.split()
        for m in marcas:
            for tok in normalize(m).split():
                if difflib.get_close_matches(tok, tokens, n=1, cutoff=0.6):
                    elegida = m
                    break
            if elegida:
                break

    if elegida:
        est["marca"] = elegida
        est["fase"] = "esperando_modelo"
        await ctx.bot.send_message(
            chat_id=cid,
            text=f"¡Genial! Veo que buscas {elegida}. ¿Qué modelo de {elegida} te interesa?",
            reply_markup=menu_botones(obtener_modelos_por_marca(inv, elegida)),
        )
        return




     # ——— Hasta aquí llega todo el flujo normal del bot ———

    # 🔥 Fallback inteligente CORREGIDO con 4 espacios

    # 🛑 Si ya se enviaron modelos, evitar fallback (cliente está en flujo activo)
    if est.get("fase") == "esperando_modelo_elegido" or est.get("modelos_enviados"):
        print("[🧠] Ignorando fallback porque ya hay modelos enviados.")
        return

    # 1) Detectar palabras típicas primero (antes que IA)
    palabras_clave_flujo = [
        "catalogo", "catálogo", "ver catálogo", "ver catalogo",
        "imagen", "foto", "enviar imagen", "ver tallas",
        "quiero comprar", "hacer pedido", "comprar", "zapatos", "tenis",
        "pago", "contraentrega", "garantía", "garantia",
        "demora", "envío", "envio"
    ]

    if any(p in txt for p in palabras_clave_flujo):
        await ctx.bot.send_message(
            chat_id=cid,
            text="📋 Parece que quieres hacer un pedido o consultar el catálogo. Usa las opciones disponibles 😉",
            reply_markup=menu_botones(["Hacer pedido", "Ver catálogo", "Enviar imagen"])
        )
        return

    # 2) NO usar IA si estamos en una fase crítica (proteger cierre de venta)
    fases_criticas = [
        "esperando_talla", "esperando_color", "esperando_nombre", "esperando_correo",
        "esperando_telefono", "esperando_ciudad", "esperando_provincia", "esperando_direccion",
        "esperando_pago", "esperando_comprobante", "imagen_detectada",
        "esperando_video_referencia", "esperando_numero_rastreo",
        "esperando_numero_devolucion", "esperando_motivo_devolucion"
    ]

    if est.get("fase") in fases_criticas:
        await ctx.bot.send_message(
            chat_id=cid,
            text="✏️ Por favor completa primero el proceso en el que estás. ¿Te ayudo a terminarlo?",
            reply_markup=menu_botones(["Volver al menú"])
        )
        return

    # 3) Ahora sí, usar IA si no entendimos nada
    respuesta_fallback = await responder_con_openai(txt_raw)
    if respuesta_fallback:
        await ctx.bot.send_message(
            chat_id=cid,
            text=respuesta_fallback,
            reply_markup=menu_botones(["Hacer pedido", "Ver catálogo", "Enviar imagen"])
        )
    else:
        await ctx.bot.send_message(
            chat_id=cid,
            text="😅 No logré entender tu solicitud. ¿Quieres ver el catálogo o realizar un pedido?",
            reply_markup=menu_botones(["Hacer pedido", "Ver catálogo"])
        )
    return

# ─────────────────────────────────────────
# FUNCIÓN AUXILIAR – REANUDAR FASE ACTUAL
# ─────────────────────────────────────────
async def reanudar_fase_actual(cid, ctx, est):
    fase = est.get("fase")

    if fase == "esperando_nombre":
        await ctx.bot.send_message(chat_id=cid, text="¿Dime tu nombre completo para seguir la compra? ✍️")

    elif fase == "esperando_correo":
        await ctx.bot.send_message(chat_id=cid, text="¿Dime cuál es tu correo para seguir? 📧")

    elif fase == "esperando_telefono":
        await ctx.bot.send_message(chat_id=cid, text="¿Tu teléfono celular para continuar? 📱")

    elif fase == "esperando_cedula":
        await ctx.bot.send_message(chat_id=cid, text="¿Dime la cédula para que sigamos? 🪪")

    elif fase == "esperando_ciudad":
        await ctx.bot.send_message(chat_id=cid, text="¿Dime la ciudad para ya cerrar tu pedido? 🏙️")

    elif fase == "esperando_provincia":
        await ctx.bot.send_message(chat_id=cid, text="¿Dime el Departamento o provincia? 🏞️")

    elif fase == "esperando_direccion":
        await ctx.bot.send_message(chat_id=cid, text="¿Cuál es entonces tu dirección para el pedido? 🏡")

    elif fase == "esperando_pago":
        await ctx.bot.send_message(
            chat_id=cid,
            text="¿Cómo deseas pagar? Escribe *transferencia* o *contraentrega*.",
            parse_mode="Markdown"
        )

    elif fase == "esperando_comprobante":
        await ctx.bot.send_message(chat_id=cid, text="📸 Por favor, envíame el comprobante de pago.")

    elif fase == "esperando_talla":
        if est.get("talla"):
            await ctx.bot.send_message(
                chat_id=cid,
                text=f"✅ Ya tengo registrada tu talla como *{est['talla']}*. ¿Deseas continuar con el pedido?",
                parse_mode="Markdown"
            )
        else:
            await ctx.bot.send_message(
                chat_id=cid,
                text="📏 ¿Cuál es tu talla? O si prefieres, mándame una foto de la lengüeta del zapato para ayudarte automáticamente."
            )

    elif fase == "esperando_color":
        if est.get("color"):
            await ctx.bot.send_message(
                chat_id=cid,
                text=f"🎨 Ya tengo registrado que te interesan los *{est['color']}*. ¿Deseas ver más modelos de ese color?",
                parse_mode="Markdown"
            )
        else:
            await ctx.bot.send_message(
                chat_id=cid,
                text="🎨 ¿Qué color te gustaría para ese modelo? Puedes decirme por ejemplo 'negros', 'blancos', etc."
            )

    elif fase == "confirmar_datos_guardados":
        await ctx.bot.send_message(
            chat_id=cid,
            text="✅ ¿Estos datos están correctos o deseas cambiar algo? Escribe 'sí son correctos' o dime qué deseas modificar."
        )

# Función para manejar la solicitud de precio por referencia
PALABRAS_PRECIO = ['precio', 'vale', 'cuesta', 'valor', 'coste', 'precios', 'cuánto']

async def manejar_precio(update, ctx, inventario):
    cid = update.effective_chat.id
    mensaje = (update.message.text or "").lower()
    txt = normalize(mensaje)
    logging.debug(f"[manejar_precio] Mensaje recibido: {mensaje}")

    # ✅ PROTECCIÓN — Solo ejecutarse si no está en fases de video
    est = estado_usuario.get(cid, {})
    fase_actual = est.get("fase", "")

    if fase_actual in (
        "esperando_video_referencia",
        "esperando_color_post_video",
        "esperando_modelo_elegido"
    ):
        logging.info(f"[manejar_precio] Ignorado: usuario en fase '{fase_actual}'")
        return False

    # Detectar referencia de 3 o 4 dígitos
    m_ref = re.search(r"(?:referencia|modelo)?\s*(\d{3,4})", txt)
    if not m_ref:
        logging.debug("[manejar_precio] No se detectó referencia en el mensaje.")
        return False

    referencia = m_ref.group(1)
    logging.debug(f"[manejar_precio] Referencia detectada: {referencia}")

    # Buscar productos que coincidan
    productos = [
        item for item in inventario
        if referencia in normalize(item.get("modelo", "")) and disponible(item)
    ]
    logging.debug(f"[manejar_precio] Productos encontrados con stock: {len(productos)}")

    if productos:
        from collections import defaultdict
        agrupados = defaultdict(set)

        for item in productos:
            try:
                precio_raw = str(item.get("precio", "0")).replace(".", "").replace("COP", "").strip()
                precio_formateado = f"{int(precio_raw):,}COP"
            except Exception as e:
                logging.error(f"[manejar_precio] Error formateando precio: {e}")
                precio_formateado = "No disponible"

            try:
                key = (
                    item.get("modelo", "desconocido"),
                    item.get("color", "varios colores"),
                    precio_formateado
                )
                agrupados[key].add(str(item.get("talla", "")))
            except Exception as e:
                logging.error(f"[manejar_precio] Error agrupando tallas: {e}")
        
        respuesta_final = ""
        primer_producto = productos[0]

        for (modelo, color, precio), tallas in agrupados.items():
            try:
                if not isinstance(tallas, (set, list, tuple)):
                    tallas = [str(tallas)]

                tallas_ordenadas = sorted(tallas, key=lambda t: int(t) if t.isdigit() else t)
                tallas_str = ", ".join(tallas_ordenadas)

                respuesta_final += (
                    f"👟 *{modelo}* ({color})\n"
                    f"💲 Precio: *{precio}*\n"
                    f"Tallas disponibles: {tallas_str}\n\n"
                )
            except Exception as e:
                logging.error(f"[manejar_precio] Error formateando tallas: {e}")

        # ✅ Guardar estado de forma segura
        est["fase"] = "confirmar_compra"
        est["modelo_confirmado"] = primer_producto["modelo"]
        est["color_confirmado"] = primer_producto["color"]
        est["marca"] = primer_producto.get("marca", "sin marca")
        estado_usuario[cid] = est

        logging.debug(f"[manejar_precio] Guardado modelo: {primer_producto['modelo']}, color: {primer_producto['color']}")

        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                f"Veo que estás interesado en nuestra referencia *{referencia}*:\n\n"
                f"{respuesta_final}"
                "¿Seguimos con la compra?\n\n"
            ),
            parse_mode="Markdown"
        )
        return True

    else:
        logging.debug("[manejar_precio] No se encontraron productos con esa referencia.")
        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                f"😕 No encontré la referencia {referencia}. "
                "¿Quieres revisar el catálogo?\n\n"
                "👉 Opciones: Ver catálogo / Volver al menú"
            ),
            parse_mode="Markdown"
        )
        return True
   
# --------------------------------------------------------------------

nest_asyncio.apply()

# 2. Conversión de número WhatsApp
def wa_chat_id(wa_from: str) -> str:
    return re.sub(r"\D", "", wa_from)

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def responder_con_openai(mensaje_usuario):
    try:
        respuesta = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres un asesor de ventas de la tienda de zapatos deportivos 'X100🔥👟'. "
                        "Solo vendemos nuestra propia marca *X100* (no manejamos marcas como Skechers, Adidas, Nike, etc.). "
                        "Nuestros productos son 100% colombianos y hechos en Bucaramanga.\n\n"
                        "Tu objetivo principal es:\n"
                        "- Si preguntan por precio di, dime qué referencia exacta buscas.\n"
                        "- Siempre que puedas, pregunta que color le gusto.\n"
                        "- Pide que envíe una imagen del zapato que busca 📸.\n"
                        "Siempre que puedas, invita amablemente a enviar  una imagen para agilizar el pedido o que preguntar que color le llamo la atencion.\n"
                        "Si el cliente pregunta por marcas externas, responde cálidamente explicando que solo manejamos X100 y todo es unisex.\n\n"
                        "Cuando no entiendas muy bien la intención, ofrece opciones como:\n"
                        "- '¿Dime que color te gusto yo te ayudo✨'\n"
                        "- '¿Quieres enviarme una imagen para ayudarte mejor? 📸'\n\n"
                        "Responde de forma CÁLIDA, POSITIVA, BREVE (máximo 2 líneas), usando emojis amistosos 🎯👟🚀✨.\n"
                        "Actúa como un asesor de ventas que siempre busca ayudar al cliente y cerrar la compra de manera rápida, amigable y eficiente."
                    )
                },
                {
                    "role": "user",
                    "content": mensaje_usuario
                }
            ],
            temperature=0.5,
            max_tokens=300
        )
        return respuesta.choices[0].message.content.strip()

    except Exception as e:
        logging.error(f"❌ Error al consultar OpenAI: {e}")
        return "⚠️ Disculpa, estamos teniendo un inconveniente en este momento. ¿Puedes intentar de nuevo más tarde?"


# 🧭 Manejo del catálogo si el usuario lo menciona
async def manejar_catalogo(update, ctx):
    cid = getattr(update, "from", None) or getattr(update.effective_chat, "id", "")
    txt = getattr(update.message, "text", "").lower()

    if menciona_catalogo(txt):
        # 📝 Primero el mensaje con el link
        mensaje = (
            f"👇🏻AQUÍ ESTA EL CATÁLOGO 🆕\n"
            f"Sigue este enlace para ver la ultima colección 👟 X💯: {CATALOG_LINK}\n"
            "Si ves algo que te guste, solo dime el modelo o mándame una foto 📸"
        )
        ctx.resp.append({"type": "text", "text": mensaje})

        # 🧷 Luego el sticker (para que quede de último)
        try:
            sticker_path = "/var/data/stickers/catalogo_sticker_catalogo.webp"
            if os.path.exists(sticker_path):
                with open(sticker_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")

                ctx.resp.append({
                    "type": "sticker",
                    "base64": f"data:image/webp;base64,{b64}"
                })
        except Exception as e:
            logging.error(f"❌ Error cargando sticker catálogo en manejar_catalogo: {e}")

        return True

    return False

async def procesar_wa(cid: str, body: str, msg_id: str = "") -> dict:
    cid   = str(cid)
    texto = (body or "").lower()
    txt   = texto
    globals()["texto"] = texto

    # 🧠 Inicializa estado si no existe
    if cid not in estado_usuario or not estado_usuario[cid].get("fase"):
        reset_estado(cid)
        estado_usuario[cid] = {
            "fase": "inicio",
            "esperando_nombre": True,
            "welcome_enviado": False  # ✅ ← ESTA ES LA LÍNEA CLAVE
        }

    est = estado_usuario[cid]
    # 📍 Detección libre de nombre y ciudad aunque no esté en fase 'inicio'
    try:
        texto_limpio = texto.strip().lower()

        match_dual = re.search(
            r"(?:soy|me llamo)\s+([a-záéíóúñ\s]{2,30}?)(?:\s+y\s+\w+)?\s+(?:de|desde)\s+([a-záéíóúñ\s]{3,30})",
            texto_limpio
        )
        if match_dual:
            nombre_detectado = match_dual.group(1).strip().title()
            ciudad_detectada = match_dual.group(2).strip().title()

            if any(normalize(ciudad_detectada) == normalize(c) for c in CIUDADES_DISPONIBLES):
                est["nombre"] = nombre_detectado
                est["ciudad"] = ciudad_detectada
                guardar_memoria_ciudad_temporal(cid, ciudad_detectada)
                guardar_memoria_usuario(cid, "ciudad", ciudad_detectada)
                logging.info(f"🌎 Nombre/Ciudad detectados FUERA de fase: {nombre_detectado}, {ciudad_detectada}")
            else:
                logging.warning(f"❌ Ciudad detectada fuera de fase pero no válida: {ciudad_detectada}")
    except Exception as e:
        logging.error(f"❌ Error en detección libre de nombre/ciudad: {e}")

    # ─── FILTRO 1: mensaje vacío ───
    if not body or not body.strip():
        print(f"[IGNORADO] Mensaje vacío de {cid}")
        return {"type": "text", "text": ""}

    # ─── FILTRO 2: anti‑duplicados (<30 s) ───
    DEDUP_WINDOW = 30
    now = time.time()
    info = ultimo_msg.get(cid)
    if info and msg_id and msg_id == info["id"] and now - info["t"] < DEDUP_WINDOW:
        print(f"[IGNORADO] Duplicado reciente de {cid}")
        return {"type": "text", "text": ""}
    if msg_id:
        ultimo_msg[cid] = {"id": msg_id, "t": now}

    # Función auxiliar para codificar imagen como base64
    def codificar_base64(path, tipo='image/jpeg'):
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{tipo};base64,{b64}"

    # ─────────── Preguntas frecuentes (FAQ) ───────────

    if est.get("fase") not in ("esperando_pago", "esperando_comprobante"):

        # FAQ 1: ¿Cuánto demora el envío?
        if any(p in texto for p in (
                "cuanto demora", "cuanto tarda", "cuanto se demora",
                "en cuanto llega", "me llega rapido", "llegan rapido",
                "cuántos días", "cuanto se demoran", "días en llegar",
                "si lo pido hoy", "si hago el pedido hoy", "si los pido hoy", "cuando me llegan"
        )):
            return {
                "type": "text",
                "text": (
                    "🚚 El tiempo de entrega depende de la ciudad de destino, "
                    "pero generalmente tarda *2 hábiles* en llegar.\n\n"
                    "Si lo necesitas para *mañana mismo*, podemos enviarlo al terminal de transporte. "
                    "En ese caso aplica *pago anticipado* (no contra entrega)."
                ),
                "parse_mode": "Markdown"
            }


        # FAQ 2: ¿Pago contra entrega?
        if any(p in texto for p in (
            "pago contra entrega", "pago contraentrega", "contraentrega", "contra entrega",
            "pagan al recibir", "puedo pagar al recibir", "tienen contra entrega"
        )):
            try:
                ruta_audio = "/var/data/audios/contraentrega/CONTRAENTREGA.mp3"
                if not os.path.exists(ruta_audio):
                    raise FileNotFoundError("❌ No se encontró el audio CONTRAENTREGA.mp3")

                with open(ruta_audio, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")

                return {
                    "type": "audio",
                    "base64": b64,
                    "mimetype": "audio/mpeg",
                    "filename": "CONTRAENTREGA.mp3",
                    "text": "🎧 Aquí tienes la explicación del pago contra entrega:"
                }

            except Exception as e:
                logging.error(f"❌ Error enviando audio CONTRAENTREGA: {e}")
                return {
                    "type": "text",
                    "text": "⚠️ No pude enviar el audio en este momento."
                }

        # FAQ 3: ¿Tienen garantía?
        if any(p in texto for p in (
            "tienen garantia", "hay garantia", "garantia", "tienen garantia de fabrica"
        )):
            return {
                "type": "text",
                "text": (
                    "🛡️ Todos nuestros productos tienen *garantía de 60 días* "
                    "por defectos de fábrica o problemas de pegado.\n\n"
                    "Cualquier inconveniente, estamos para ayudarte."
                ),
                "parse_mode": "Markdown"
            }

        # FAQ 5: ¿Dónde están ubicados?
        if any(p in texto for p in (
            "donde estan ubicados", "donde estan", "ubicacion", "ubicación",
            "direccion", "tienda fisica", "donde es la tienda",
            "estan ubicados", "ubicados en donde", "en que ciudad estan", "en que parte estan"
        )):

            def cargar_memoria_ciudad_temporal(cid):
                ruta_tmp = "/tmp/memoria_ciudades_temp.json"
                if os.path.exists(ruta_tmp):
                    try:
                        with open(ruta_tmp, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        return data.get(cid)
                    except Exception as e:
                        logging.warning(f"⚠️ Error leyendo memoria temporal: {e}")
                return None

            mensajes = [
                {
                    "type": "text",
                    "text": (
                        "📍 Estamos en *Bucaramanga, Santander*.\n\n"
                        "🏡 *Barrio San Miguel, Calle 52 #16-74*\n\n"
                        "🚚 ¡Enviamos a todo Colombia con Servientrega!\n\n"
                        "🗺️ Ubicación Google Maps: https://maps.google.com/?q=7.109500,-73.121597"
                    ),
                    "parse_mode": "Markdown"
                }
            ]

            # ✅ Verificar ciudad en memoria
            memoria_persistente = cargar_memoria_usuario(cid)
            ciudad_cliente = (
                cargar_memoria_ciudad_temporal(cid) or
                memoria_persistente.get("ciudad") or
                est.get("ciudad")
            )

            if ciudad_cliente:
                mensajes.append({
                    "type": "text",
                    "text": (
                        f"📦 *Recuerda que el envío a {ciudad_cliente} es completamente gratis.* "
                        "¿Quieres que te los enviemos ya mismo? Te llegarán en unos *2 días hábiles* 🤩"
                    ),
                    "parse_mode": "Markdown"
                })
            else:
                mensajes.append({
                    "type": "text",
                    "text": (
                        "🚚 *Recuerda que el envío a tu ciudad es totalmente gratis* "
                        "y te llega en *2 días hábiles* a la puerta de tu casa. 📦✨"
                    ),
                    "parse_mode": "Markdown"
                })

            return {
                "type": "multi",
                "messages": mensajes
            }




        # FAQ 6: ¿Son nacionales o importados?
        if any(p in texto for p in (
            "son nacionales", "son importados", "es nacional o importado",
            "nacionales o importados", "hecho en colombia", "fabricados en colombia",
            "son de aqui", "es de colombia", "fabricacion colombiana"
        )):
            return {
                "type": "text",
                "text": (
                    "🇨🇴 Nuestra marca es *100 % colombiana* y las zapatillas "
                    "se elaboran con orgullo en *Bucaramanga* por artesanos locales."
                ),
                "parse_mode": "Markdown"
            }

        # FAQ 7: ¿Son originales?
        if any(p in texto for p in (
            "son originales", "es original", "originales",
            "es copia", "son copia", "son replica", "réplica", "imitacion"
        )):
            return {
                "type": "text",
                "text": (
                    "✅ ¡Claro! Son *originales*. Somos *X100*, marca 100 % colombiana reconocida por su calidad y diseño."
                ),
                "parse_mode": "Markdown"
            }

        # FAQ 8: ¿De qué calidad son?
        if any(p in texto for p in (
            "que calidad son", "de que calidad son", "son buena calidad", "son de buena calidad",
            "son de mala calidad", "que calidad manejan", "que calidad tienen", "calidad de las zapatillas"
        )):
            return {
                "type": "text",
                "text": (
                    "✨ Nuestras zapatillas están elaboradas con *materiales de alta calidad*.\n\n"
                    "Cada par se fabrica cuidadosamente para asegurar *calidad AAA* 👟🔝, "
                    "garantizando comodidad, durabilidad y excelente acabado."
                ),
                "parse_mode": "Markdown"
            }

        # FAQ 9: ¿Hay descuento por 2 pares?
        if any(p in texto for p in (
            "si compro 2 pares", "dos pares descuento", "descuento por 2 pares",
            "descuento por dos pares", "me descuentan si compro dos", "descuento si compro dos",
            "hay descuento por dos", "promocion dos pares", "descuento en 2 pares"
        )):
            return {
                "type": "text",
                "text": (
                    "🎉 ¡Sí! Si compras *2 pares* te damos un *10% de descuento adicional* sobre el total.\n\n"
                    "¡Aprovecha para estrenar más y pagar menos! 🔥👟👟"
                ),
                "parse_mode": "Markdown"
            }

        # FAQ 10: ¿Precios para mayoristas?
        if any(p in texto for p in (
            "precio mayorista", "precios para mayoristas", "mayorista", "quiero vender",
            "puedo venderlos", "descuento para revender", "revender", "comprar para vender",
            "manejan precios para mayoristas", "mayoreo", "venta al por mayor"
        )):
            return {
                "type": "text",
                "text": (
                    "🛍️ ¡Claro! Manejamos *precios para mayoristas* en pedidos de *6 pares en adelante*, "
                    "sin importar tallas ni referencias.\n\n"
                    "Condición: vender mínimo al mismo precio que nosotros para cuidar el mercado."
                ),
                "parse_mode": "Markdown"
            }

        # FAQ 11: ¿Las tallas son normales?
        if any(p in texto for p in (
            "las tallas son normales", "horma normal", "talla normal",
            "horma grande", "horma pequeña", "tallas grandes", "tallas pequeñas",
            "las tallas son grandes", "las tallas son pequeñas", "como son las tallas"
        )):
            return {
                "type": "text",
                "text": (
                    "👟 Nuestra horma es *normal*. Si calzas talla *40* nacional, te queda bien la *40* de nosotros.\n\n"
                    "Para mayor seguridad, puedes enviarnos una foto de la *etiqueta interna* de tus tenis actuales 📏✨."
                ),
                "parse_mode": "Markdown"
            }

        # FAQ 12: ¿Talla más grande?
        if any(p in texto for p in (
            "talla mas grande", "talla más grande", "cual es la talla mas grande",
            "horma", "mayor talla", "talla maxima", "talla máxima"
        )):
            return {
                "type": "text",
                "text": (
                    "📏 La talla más grande que manejamos es:\n\n"
                    "• *45 Nacional* 🇨🇴\n"
                    "• *47 Europeo* 🇪🇺\n\n"
                    "¡También tenemos opciones para pies grandes! 👟✨"
                ),
                "parse_mode": "Markdown"
            }
    # 🔧 Normalizar texto antes de los FAQ
    texto_normalizado = normalizar(texto)

    # FAQ: Redes sociales
    if any(p in texto_normalizado for p in (
        "REDES SOCIALES", "INSTAGRAM", "FACEBOOK", "TIKTOK", "PAGINA WEB",
        "TIENEN INSTAGRAM", "TIENEN FACEBOOK", "TIENEN TIKTOK", "COMO LOS ENCUENTRO EN REDES",
        "SUS REDES", "SIGUEN EN REDES", "WEB"
    )):
        return {
            "type": "text",
            "text": (
                "📲 ¡Claro! Aquí están todas nuestras redes y página oficial:\n\n"
                "👟 *Instagram:* [@x100_col](https://www.instagram.com/x100_col)\n"
                "📘 *Facebook:* [@x100col](https://www.facebook.com/x100col)\n"
                "🎵 *TikTok:* [@x100_col](https://www.tiktok.com/@x100_col?_t=ZS-8wiexPh9ah6&_r=1)\n"
                "🌐 *Página web:* [x100-col.com](https://www.x100-col.com/tienda/)\n\n"
                "Síguenos para conocer nuevos modelos, promociones exclusivas y más 🔥💯"
            ),
            "parse_mode": "Markdown"
        }

    # FAQ: ¿Por qué tan caros?
    if any(p in texto_normalizado for p in (
        "POR QUE TAN CAROS", "PORQUE TAN CARO", "PORQUE TAN COSTOSO",
        "ES MUY CARO", "MUY COSTOSO"
    )):
        try:
            ruta_audio = "/var/data/audios/caros/CAROS.mp3"
            if not os.path.exists(ruta_audio):
                raise FileNotFoundError("❌ No se encontró el audio CAROS.mp3")

            with open(ruta_audio, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            return {
                "type": "audio",
                "base64": b64,
                "mimetype": "audio/mpeg",
                "filename": "CAROS.mp3",
                "text": "🎧 Aquí te explicamos por qué valen lo que valen:"
            }

        except Exception as e:
            logging.error(f"❌ Error enviando audio CAROS: {e}")
            return {
                "type": "text",
                "text": "⚠️ No pude enviar el audio en este momento."
            }

    # FAQ: ¿Son cosidos?
    if any(p in texto_normalizado for p in (
        "SON COSIDOS", "VIENEN COSIDOS", "ESTAN COSIDOS", "COSIDO", "COSIDOS"
    )):
        try:
            ruta_audio = "/var/data/audios/cosidos/cosidos.mp3"
            if not os.path.exists(ruta_audio):
                raise FileNotFoundError("❌ No se encontró el audio COSIDAS.mp3")

            with open(ruta_audio, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            return {
                "type": "audio",
                "base64": b64,
                "mimetype": "audio/mpeg",
                "filename": "COSIDAS.mp3",
                "text": "🧵 Aquí tienes la explicación sobre si son cosidos:"
            }

        except Exception as e:
            logging.error(f"❌ Error enviando audio COSIDAS: {e}")
            return {
                "type": "text",
                "text": "⚠️ No pude enviar el audio en este momento."
            }

    # FAQ: ¿La suela es de caucho?
    if any(p in texto_normalizado for p in (
        "SUELA DE CAUCHO", "ES DE CAUCHO", "LA SUELA ES DE",
        "LA SUELA DE QUE ES", "MATERIAL DE LA SUELA"
    )):
        try:
            ruta_audio = "/var/data/audios/caucho/caucho.mp3"
            if not os.path.exists(ruta_audio):
                raise FileNotFoundError("❌ No se encontró el audio caucho.mp3")

            with open(ruta_audio, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            return {
                "type": "audio",
                "base64": b64,
                "mimetype": "audio/mpeg",
                "filename": "caucho.mp3",
                "text": "👟 Te explicamos de qué material es la suela:"
            }

        except Exception as e:
            logging.error(f"❌ Error enviando audio CAUCHO: {e}")
            return {
                "type": "text",
                "text": "⚠️ No pude enviar el audio en este momento."
            }

    texto = texto.lower()

    # 1️⃣ 🏡 Bucaramanga — prioridad máxima si se menciona
    if "bucaramanga" in texto and any(p in texto for p in {
        "envío", "envios", "envían", "enviar", "envian", "enviarme", 
        "soy de", "estoy en", "pueden llevar", "tienen envio a", "el envio a", 
        "envío a", "envian a", "como es el envio", "hacen envíos", "tienen envío"
    }):
        return {
            "type": "text",
            "text": (
                "📍 *¡Perfecto! Como eres de Bucaramanga, te podemos enviar hoy mismo el pedido con un domiciliario*, "
                "y lo pagas al recibir 🛵💵.\n\n"
                "🛍️ También puedes pasar a recogerlo directamente en nuestra tienda si prefieres.\n\n"
                "📌 *Estamos en:* Barrio *San Miguel*, Calle 52 #16-74\n"
                "🗺️ Google Maps: https://maps.google.com/?q=7.109500,-73.121597\n\n"
            ),
            "parse_mode": "Markdown"
        }
    # 2️⃣ Bucaramanga — pero preguntan por demora
    if "bucaramanga" in texto and any(p in texto for p in (
        "cuanto demora", "cuanto tarda", "cuanto se demora",
        "en cuanto llega", "me llega rapido", "llegan rapido", 
        "cuántos días", "días en llegar", "se demora en llegar"
    )):
        return {
            "type": "text",
            "text": (
                "📦 ¡Como estamos ubicados en *Bucaramanga*! 😎\n\n"
                "El pedido se te puede enviar ya mismo con un domiciliario pagas al recibir no tienes que dar anticipo 🚀."
            ),
            "parse_mode": "Markdown"
        }
    # 2️⃣ 🚚 Cuánto cuesta el envío a... o ¿es gratis?
    if "envio" in texto:
        # 2A: ¿Cuánto cuesta el envío a...?
        envio_match = re.search(
            r"(cu[aá]nto(?: cuesta| vale| cobran)?(?: el)? env[ií]o(?: a)?\s*([a-záéíóúñ\s]+)?)",
            texto
        )
        if envio_match:
            ciudad = envio_match.group(2).strip().title() if envio_match.group(2) else "tu ciudad"
            return {
                "type": "text",
                "text": f"🚚 El envío a *{ciudad}* es totalmente gratuito, no tiene costo. 📦",
                "parse_mode": "Markdown"
            }

        # 2B: ¿El envío es gratis?
        if re.search(r"(env[ií]o.*(es )?gratis|es gratis.*env[ií]o|el env[ií]o tiene costo)", texto):
            return {
                "type": "text",
                "text": "🚚 ¡Sí! El envío es *totalmente gratuito a cualquier ciudad de Colombia*. 📦",
                "parse_mode": "Markdown"
            }

    # 3️⃣ 🌍 Preguntas genéricas sobre envío sin ciudad clara
    if any(p in texto for p in {
        "envían a", "envio a", "envíos a", "hacen envíos a", "tienen envío a", 
        "pueden enviar a", "enviarían a", "envian hasta", "envían hasta", 
        "pueden enviar hasta", "envían por", "tienen envíos a"
    }):
        return {
            "type": "text",
            "text": (
                "🚚 *¡Claro que sí! Hacemos envíos a todo Colombia 🇨🇴*, incluyendo tu ciudad.\n\n"
                "📦 El envío es totalmente *GRATIS* y te llega en promedio en *2  días hábiles* 📬.\n"
                "Puedes pagar contraentrega o por transferencia como prefieras 💳💵."
            ),
            "parse_mode": "Markdown"
        }

    # 4️⃣ 💳 Métodos de pago
    if any(p in texto for p in (
        "método de pago", "metodos de pago", "formas de pago", "formas para pagar",
        "como pago", "cómo puedo pagar", "qué medios de pago", "medios de pago", "aceptan nequi",
        "pago por daviplata", "manejan bancolombia", "que pago manejan", "que pagos manejan"
    )):
        ruta_metodo = "/var/data/extra/metodosdepago.jpeg"
        if os.path.exists(ruta_metodo):
            with open(ruta_metodo, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
                return {
                    "type": "multi",
                    "messages": [
                        {
                            "type": "text",
                            "text": "💳 Estos son los *métodos de pago* que manejamos actualmente:",
                            "parse_mode": "Markdown"
                        },
                        {
                            "type": "photo",
                            "base64": f"data:image/jpeg;base64,{b64}",
                            "text": "📷 Métodos de pago disponibles"
                        }
                    ]
                }
        else:
            return {
                "type": "text",
                "text": "💳 Aceptamos *Nequi, Daviplata, Bancolombia* y también *contraentrega*."
            }


    # Lista de palabras afirmativas comunes
    AFIRMATIVAS = [
        "si", "sí", "sii", "sis", "sisz", "siss", "de una", "dale", "hágale", "hagale", 
        "hágale pues", "me gusta", "quiero", "lo quiero", "vamos", "claro", 
        "obvio", "eso es", "ese", "de ley", "de fijo", "ok", "okay", "listo"
    ]

    # ───────────────────────────────────────────
    # ───────────────────────────────────────────
    class DummyCtx(SimpleNamespace):
        async def bot_send(self, chat_id, text, **kw):
            self.resp.append({"type": "text", "text": text})

        async def bot_send_chat_action(self, chat_id, action, **kw):
            pass

        async def bot_send_video(self, chat_id, video, caption=None, **kw):
            self.resp.append({
                "type": "video",
                "path": video.name,
                "text": caption or ""
            })

        async def bot_send_photo(self, chat_id, photo, caption=None, **kw):
            try:
                base64_img = codificar_base64(photo.name)
                self.resp.append({
                    "type": "photo",
                    "base64": base64_img,
                    "text": caption or ""
                })
            except Exception as e:
                self.resp.append({
                    "type": "text",
                    "text": f"❌ Error cargando imagen: {e}"
                })

    ctx = DummyCtx(resp=[])
    ctx.bot = SimpleNamespace(
        send_message=ctx.bot_send,
        send_chat_action=ctx.bot_send_chat_action,
        send_video=ctx.bot_send_video,
        send_photo=ctx.bot_send_photo
    )

    # ───────────────────────── DummyMsg (definido una sola vez) ─────────────────────────
    class DummyMsg(SimpleNamespace):
        def __init__(self, text, ctx, photo=None, voice=None, audio=None):
            self.text  = text
            self.photo = photo
            self.voice = voice
            self.audio = audio
            self._ctx  = ctx

        async def reply_text(self, text, **kw):
            self._ctx.resp.append({"type": "text", "text": text})

    # ─────────────── Crear dummy_msg y dummy_update ───────────────
    dummy_msg = DummyMsg(text=body, ctx=ctx)
    dummy_update = SimpleNamespace(
        message=dummy_msg,
        effective_chat=SimpleNamespace(id=cid)
    )

    # 👤 Solo aceptar nombre/ciudad si se pidió explícitamente luego del welcome
    if est.get("fase") == "inicio" and est.get("esperando_nombre"):

        texto_limpio = texto.strip()
        logging.info(f"🧠 Analizando texto para nombre/ciudad: '{texto_limpio}'")

        # 1️⃣ Detectar frases como: "Hola soy Juan Pablo y soy de Pereira"
        match_dual = re.search(
            r"(?:soy|me llamo)\s+([a-záéíóúñ\s]{2,30}?)(?:\s+y\s+\w+)?\s+(?:de|desde)\s+([a-záéíóúñ\s]{3,30})",
            texto_limpio.lower()
        )
        if match_dual:
            nombre_detectado = match_dual.group(1).strip().title()
            ciudad_detectada = match_dual.group(2).strip().title()
            logging.info(f"✅ Detected nombre='{nombre_detectado}' ciudad='{ciudad_detectada}' [match_dual]")

            est["nombre"] = nombre_detectado

            if any(normalize(ciudad_detectada) == normalize(c) for c in CIUDADES_DISPONIBLES):
                est["ciudad"] = ciudad_detectada
                guardar_memoria_ciudad_temporal(cid, ciudad_detectada)
                guardar_memoria_usuario(cid, "ciudad", ciudad_detectada)
                logging.info(f"📍 Ciudad validada con archivo y guardada: {ciudad_detectada}")
            else:
                logging.warning(f"❌ Ciudad '{ciudad_detectada}' no está en CIUDADES_DISPONIBLES")

        # 2️⃣ Si no se detectó lo anterior, usar regex tradicionales
        if "nombre" not in est:
            match_nombre = re.search(r"(mi nombre es|me llamo|soy)\s+([a-zA-Záéíóúñ\s]+)", normalize(texto))
            if match_nombre:
                est["nombre"] = match_nombre.group(2).strip().title()
                logging.info(f"✅ Nombre detectado por regex tradicional: {est['nombre']}")

        if "ciudad" not in est:
            match_ciudad = re.search(r"(de|desde|en|ubicado en|soy de|me ubico en|estoy en)\s+([a-zA-Záéíóúñ\s]+)", normalize(texto))
            if match_ciudad:
                ciudad_detectada = match_ciudad.group(2).strip().title()
                if any(normalize(ciudad_detectada) == normalize(c) for c in CIUDADES_DISPONIBLES):
                    est["ciudad"] = ciudad_detectada
                    guardar_memoria_ciudad_temporal(cid, ciudad_detectada)
                    guardar_memoria_usuario(cid, "ciudad", ciudad_detectada)
                    logging.info(f"📍 Ciudad detectada por fallback y guardada: {ciudad_detectada}")
                else:
                    logging.warning(f"❌ Ciudad '{ciudad_detectada}' no está en CIUDADES_DISPONIBLES")

        # 3️⃣ Si se detectó algo útil, enviar saludo
        if "nombre" in est or "ciudad" in est:
            est["esperando_nombre"] = False
            estado_usuario[cid] = est

            nombre = est.get("nombre", "amig@")
            ciudad = est.get("ciudad")
            ciudad_texto = f"Qué bueno que seas de {ciudad} 🏡\n" if ciudad else ""

            logging.info(f"✅ ESTADO FINAL: nombre={nombre}, ciudad={ciudad}")

            return {
                "type": "text",
                "text": (
                    f"👋 Hola {nombre}! "
                    f"{ciudad_texto}"
                    "El envío es gratis 🚚. ¿Qué modelo te gustó o qué estás buscando?"
                ),
                "parse_mode": "Markdown"
            }

        # 4️⃣ Si no se detectó nada, seguir flujo normal
        est["esperando_nombre"] = False
        estado_usuario[cid] = est
        logging.info("⚠️ No se detectó nombre ni ciudad en el mensaje.")

    # ──────────────────────────────
    # 🔁 CONTROL DE FLUJO INICIAL
    # ──────────────────────────────
    ADMIN_CID = "573137842559"  # Tu número de prueba
    is_media_inicial = dummy_msg.photo or dummy_msg.voice or dummy_msg.audio

    # 1️⃣ COMANDO /start solo para admin (resetea todo)
    if texto.strip() == "/start" and cid == ADMIN_CID:
        reset_estado(cid)
        estado_usuario[cid] = {
            "fase": "inicio",
            "esperando_nombre": True,
            "welcome_enviado": False
        }
        if cid in usuarios_saludo_enviado:
            usuarios_saludo_enviado.remove(cid)  # Permite que vuelva a recibir el welcome
        return {
            "type": "text",
            "text": "🔄 Has reiniciado el flujo. El welcome se enviará en el próximo mensaje."
        }

    # 2️⃣ Imagen como primer mensaje (salta welcome pero saluda antes)
    if dummy_msg.photo and est.get("fase") == "inicio" and not est.get("welcome_enviado"):
        est["fase"] = "imagen_detectada"

        try:
            respuesta_imagen = await manejar_imagen_inicial(cid, dummy_msg.photo, est)

            saludo = {
                "type": "text",
                "text": "👋 Hola! Claro, déjame mostrarte lo que encontré con esta imagen 📸"
            }

            if respuesta_imagen:
                est["welcome_enviado"] = True
                usuarios_saludo_enviado.add(cid)    # ← Importante
                estado_usuario[cid] = est

                if respuesta_imagen.get("type") == "multi":
                    return {
                        "type": "multi",
                        "messages": [saludo] + respuesta_imagen.get("messages", [])
                    }
                else:
                    return {
                        "type": "multi",
                        "messages": [saludo, respuesta_imagen]
                    }

        except Exception as e:
            logging.error(f"❌ Error procesando imagen inicial: {e}")
            est["welcome_enviado"] = True
            usuarios_saludo_enviado.add(cid)    # ← Importante
            estado_usuario[cid] = est
            return {
                "type": "text",
                "text": "⚠️ No pude analizar la imagen. ¿Puedes enviarla de nuevo enfocando solo el zapato?"
            }

    # 3️⃣ Enviar welcome si no se ha enviado aún y no es media
    if est.get("fase") == "inicio" and not est.get("welcome_enviado") and not is_media_inicial:
        est["welcome_enviado"] = True
        usuarios_saludo_enviado.add(cid)    # ← Importante
        estado_usuario[cid] = est

        tipo_saludo = clasificar_saludo(txt)          # ← usa el primer mensaje del cliente
        bienvenida  = await enviar_welcome_venom(cid, tipo_saludo)

        bienvenida_msgs = bienvenida.get("messages", []) if bienvenida.get("type") == "multi" else [bienvenida]
        audio_msg = next((m for m in bienvenida_msgs if m.get("type") == "audio"), None)
        otros_msgs = [m for m in bienvenida_msgs if m.get("type") != "audio"]

        try:
            carpeta = "/var/data/videos"
            orden_deseado = ["Referencias.mp4", "Referencias2.mp4", "Descuentos.mp4", "Infantil.mp4"]
            archivos = [f for f in orden_deseado if os.path.exists(os.path.join(carpeta, f))]

            nombres_con_emojis = {
                "Referencias2.mp4": "👟 Referencias 🔝 261 🔥 277 🔥 303 🔥 295 🔥 299 🔥",
                "Referencias.mp4":  "👟 Referencias 🔝 279 🔥 304 🔥 305 🔥",
                "Descuentos.mp4":   "👟 Referencias 🔝 🔥 Promo 39 % Off 🔥",
                "Infantil.mp4":     "👟 Referencias 🔝 🔥 Niños 🔥"
            }

            videos = []
            for nombre in archivos:
                path = os.path.join(carpeta, nombre)
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                texto_video = nombres_con_emojis.get(
                    nombre, f"🎥 {nombre.replace('.mp4', '').replace('_', ' ').title()}"
                )
                videos.append({
                    "type": "video",
                    "base64": f"data:video/mp4;base64,{b64}",
                    "text": texto_video
                })

            if videos:
                videos.insert(0, {
                    "type": "text",
                    "text": "🎬 Mira nuestras referencias en video. ¡Dime cuál te gusta y en qué talla lo deseas!"
                })
                videos.append({
                    "type": "text",
                    "text": "🧐 Dime qué referencia te interesa. Si no está acá, envíame una foto 📸"
                })

            mensajes = []
            if audio_msg:
                mensajes.append(audio_msg)
            mensajes.extend(videos)
            mensajes.extend(otros_msgs)

            if "precio" in txt:
                mensajes.append({
                    "type": "text",
                    "text": "💸 Manejamos varios precios. Envíame la referencia exacta o una foto 📸 del zapato que te interesa y te doy el precio al instante."
                })

            est["fase"] = "esperando_color"
            estado_usuario[cid] = est

            return {"type": "multi", "messages": mensajes}

        except Exception as e:
            logging.error(f"❌ Error cargando videos desde /var/data/videos: {e}")
            return {
                "type": "text",
                "text": "⚠️ Te doy la bienvenida, pero no pude cargar los videos aún. Intenta más tarde."
            }

    # 4️⃣ Filtro: si no se ha enviado el welcome_text, no responder a nada más
    if not est.get("welcome_enviado") and cid not in usuarios_saludo_enviado:
        saludos_pasivos = {
            "hola", "hola!", "holaa", "buenos dias", "buenos días",
            "buenas tardes", "buenas noches"
        }
        if texto.strip() in saludos_pasivos:
            return {"type": "text", "text": ""}
        return {"type": "text", "text": ""}


    # 🔊 Petición de audio
    if any(f in txt for f in (
        "mandame un audio", "mándame un audio", "envíame un audio",
        "puede enviarme un audio", "puedes enviarme un audio", "me puedes enviar un audio",
        "háblame", "hábleme", "háblame por voz", "me puedes hablar",
        "leeme", "léeme", "no sé leer", "no se leer", "no puedo leer"
    )):
        texto_respuesta = (
            "Hola 👋 soy tu asistente. "
            "Cuéntame qué modelo deseas adquirir hoy."
        )

        try:
            # 1️⃣ Generar el MP3 con OpenAI TTS
            ruta_audio = await generar_audio_openai(texto_respuesta, f"audio_{cid}.mp3")
            if not ruta_audio or not os.path.exists(ruta_audio):
                raise FileNotFoundError("El TTS no generó el archivo")

            # 2️⃣ Convertir a base64 para enviarlo por Venom / WhatsApp
            with open(ruta_audio, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")

            # 3️⃣ Devolver estructura que Venom entiende
            return {
                "type": "audio",
                "base64": b64,            # ← base64 limpio
                "mimetype": "audio/mpeg", # ← obligatorio
                "filename": os.path.basename(ruta_audio),
                "text": "🎧 Aquí tienes tu audio:"
            }

        except Exception as e:
            logging.error(f"❌ Error generando o codificando audio: {e}")
            return {
                "type": "text",
                "text": "❌ No pude generar el audio en este momento."
            }
        
    # ─── MAIN try/except ───
    try:
        # 🧠 El cliente pidió catálogo (texto tipo "mandeme fotos", "catalogo", etc.)
        if menciona_catalogo(texto):
                await manejar_catalogo(dummy_update, ctx)
                est["fase"] = "inicio"
                estado_usuario[cid] = est
                if ctx.resp:
                        return {"type": "multi", "messages": ctx.resp}
                return {"type": "text", "text": "👟 Te envié el catálogo arriba 👆🏻"}

        reply = await responder(dummy_update, ctx)

        # 🟢 Si responder() devuelve un dict (video/audio), lo mandamos directo
        if isinstance(reply, dict):
                return reply

        # 🟢 Si hay mensajes acumulados por ctx
        if ctx.resp:
                if len(ctx.resp) == 1:
                        return ctx.resp[0]
                else:
                        return {"type": "multi", "messages": ctx.resp}

        # ✅ Confirmar compra si usuario responde con afirmación
        est = estado_usuario.get(cid, {})
        if est.get("fase") == "confirmar_compra":
                if any(pal in txt for pal in AFIRMATIVAS):
                        estado_usuario[cid]["fase"] = "esperando_direccion"
                        return {"type": "text", "text": "Perfecto 💥 ¿A qué dirección quieres que enviemos el pedido?"}
                elif any(x in txt for x in ["cancel", "cancelar", "otra", "ver otro", "no gracias"]):
                        estado_usuario.pop(cid, None)
                        return {"type": "text", "text": "❌ Cancelado. Escribe /start para reiniciar o dime si deseas ver otra referencia 📦."}
                else:
                        return {"type": "text", "text": "¿Confirmas que quieres comprar este modelo? Puedes decir: 'sí', 'de una', 'dale', etc."}

        # 🟡 Si está esperando pago o comprobante
        est = estado_usuario.get(cid, {})
        if est.get("fase") in ("esperando_pago", "esperando_comprobante"):
                return {"type": "text", "text": "💬 Espero tu método de pago o comprobante. 📸"}

        # 🔁 Caso final: pasar a la IA
        respuesta_ia = await responder_con_openai(body)
        return {"type": "text", "text": respuesta_ia or "🤖 Estoy revisando el sistema…"}

    except Exception as e:
        print(f"🔥 Error interno en procesar_wa(): {e}")
        try:
            respuesta_ia = await responder_con_openai(body)
            return {"type": "text", "text": respuesta_ia or "⚠️ Hubo un error inesperado. Intenta de nuevo."}
        except Exception as fallback_error:
            logging.error(f"[FALLBACK] También falló responder_con_openai: {fallback_error}")
            return {"type": "text", "text": "⚠️ Error inesperado. Por favor intenta más tarde."}

@api.post("/venom")
async def venom_webhook(req: Request):
    """Webhook principal que recibe los mensajes de Venom y procesa imagen, audio o texto."""
    inv = obtener_inventario()

    try:
        data     = await req.json()
        cid      = wa_chat_id(data.get("from", ""))
        body     = data.get("body", "") or ""          # ← SIN .lower()  (no daña base-64)
        body_raw = body  # ← este es el que se usa para imagen (sin modificar ni hacer .lower())
        mtype    = (data.get("type") or "").lower()
        mimetype = (data.get("mimetype") or "").lower()

        logging.info(f"📩 Mensaje recibido — CID:{cid} — Tipo:{mtype} — MIME:{mimetype}")
        if (
            data.get("isForwarded") or
            data.get("isNotification") or
            data.get("type") == "e2e_notification" or
            data.get("fromMe") or
            data.get("isSentByMe") or
            data.get("isGroupMsg") or
            not body
        ):
            logging.warning(f"[VENOM] Ignorado — CID:{cid}")
            return {"status": "ignored"}

        # 🖼️ IMAGEN
        if mtype == "image" or mimetype.startswith("image"):
            try:
                logging.info("🖼️ [IMG] Recibida imagen, iniciando decodificación…")

                if len(body_raw) < 200:
                    return JSONResponse({
                        "type": "text",
                        "text": "❌ La imagen llegó incompleta. Intenta enviarla otra vez."
                    })

                b64_data = body_raw.split(",", 1)[1] if body_raw.startswith("data:image") else body_raw
                img_bytes = base64.b64decode(b64_data + "===")

                with io.BytesIO(img_bytes) as bio:
                    img = Image.open(bio)
                    img.load()
                    img = img.convert("RGB")

                logging.info(f"✅ Imagen decodificada — Formato:{img.format} Tamaño:{img.size}")

            except Exception as e:
                logging.error(f"❌ [IMG] No pude leer la imagen: {e}")
                return JSONResponse({
                    "type": "text",
                    "text": "❌ No pude leer la imagen 😕. Prueba con otra foto."
                })

            est  = estado_usuario.get(cid, {})
            fase = est.get("fase", "")


            # 3️⃣ COMPROBANTE -------------------------------------------------
            if fase == "esperando_comprobante":
                try:
                    os.makedirs("temp", exist_ok=True)
                    temp_path = f"temp/{cid}_proof.jpg"
                    with open(temp_path, "wb") as f:
                        f.write(img_bytes)

                    texto = extraer_texto_comprobante(temp_path)
                    logging.info(f"[OCR] Texto extraído (500 chars):\n{texto[:500]}")

                    if es_comprobante_valido(texto):
                        logging.info("✅ Comprobante válido por OCR")
                        resumen = est.get("resumen", {})

                        # Asegurar que tenga todas las claves necesarias
                        resumen.setdefault("Número Venta", est.get("numero", ""))
                        resumen.setdefault("Cliente", est.get("nombre", ""))
                        resumen.setdefault("Cédula", est.get("cedula", ""))
                        resumen.setdefault("Teléfono", est.get("telefono", ""))
                        resumen.setdefault("Producto", est.get("modelo", ""))
                        resumen.setdefault("Color", est.get("color", ""))
                        resumen.setdefault("Talla", est.get("talla", ""))
                        resumen.setdefault("Correo", est.get("correo", ""))
                        resumen.setdefault("Pago", est.get("pago", ""))
                        resumen["fase_actual"] = "Finalizado"
                        resumen["Estado"] = "COMPLETADO"

                        registrar_orden_unificada(resumen, destino="PEDIDOS")

                        enviar_correo(
                            est["correo"],
                            f"Pago recibido {resumen.get('Número Venta')}",
                            json.dumps(resumen, indent=2)
                        )
                        enviar_correo_con_adjunto(
                            EMAIL_JEFE,
                            f"Comprobante {resumen.get('Número Venta')}",
                            json.dumps(resumen, indent=2),
                            temp_path
                        )
                        os.remove(temp_path)
                        reset_estado(cid)

                        # ✅ Enviar texto + sticker de fin de compra
                        try:
                            sticker_path = "/var/data/stickers/sticker_fin_de_compra_sticker_final.webp"
                            if os.path.exists(sticker_path):
                                with open(sticker_path, "rb") as f:
                                    b64 = base64.b64encode(f.read()).decode("utf-8")

                                return JSONResponse({
                                    "type": "multi",
                                    "messages": [
                                        {"type": "text", "text": "✅ Comprobante verificado. Tu pedido está en proceso. 🚚"},
                                        {"type": "sticker", "base64": f"data:image/webp;base64,{b64}"}
                                    ]
                                })
                        except Exception as e:
                            logging.error(f"❌ Error al cargar el sticker de fin de compra: {e}")

                        # fallback si falla el sticker
                        return JSONResponse({
                            "type": "text",
                            "text": "✅ Comprobante verificado. Tu pedido está en proceso. 🚚"
                        })

                    else:
                        os.remove(temp_path)
                        return JSONResponse({
                            "type": "text",
                            "text": "⚠️ No pude verificar el comprobante. Asegúrate que diga 'Pago exitoso'."
                        })

                except Exception as e:
                    logging.error(f"❌ Error al procesar comprobante: {e}")
                    return JSONResponse({
                        "type": "text",
                        "text": "❌ No pude procesar el comprobante. Intenta con otra imagen."
                    })

            # 👟 LENGÜETA - detectar talla si está esperando_talla
            elif fase == "esperando_talla":
                try:
                    os.makedirs("temp", exist_ok=True)
                    path_img = f"temp/{cid}_lengueta.jpg"
                    with open(path_img, "wb") as f:
                        f.write(img_bytes)

                    image = vision.Image(content=img_bytes)
                    response = vision_client.text_detection(image=image)
                    textos_detectados = response.text_annotations
                    texto_extraido = textos_detectados[0].description if textos_detectados else ""
                    logging.info(f"[OCR LENGÜETA] Texto detectado:\n{texto_extraido}")

                    talla_detectada = extraer_cm_y_convertir_talla(texto_extraido)
                    if talla_detectada:
                        est["talla"] = talla_detectada
                        estado_usuario[cid] = est
                        return JSONResponse({
                            "type": "text",
                            "text": f"📏 Según la etiqueta que me envias, la talla ideal para tus zapatos es la *{talla_detectada}* en nuestra horma. ¿Deseas que te las enviemos hoy mismo?",
                            "parse_mode": "Markdown"
                        })
                    else:
                        return JSONResponse({
                            "type": "text",
                            "text": "❌ No logré identificar tu talla. ¿Podrías enviarme una foto más clara de la lengüeta del zapato?"
                        })
                except Exception as e:
                    logging.error(f"[OCR LENGÜETA] ❌ Error al procesar la imagen: {e}")
                    return JSONResponse({
                        "type": "text",
                        "text": "❌ Hubo un error procesando la imagen. Intenta de nuevo con otra foto, por favor."
                    })

            # 🧠 OCR - intentar antes de CLIP
            else:
                try:
                    os.makedirs("temp", exist_ok=True)
                    path_img = f"temp/{cid}_img.jpg"
                    with open(path_img, "wb") as f:
                        f.write(img_bytes)

                    texto_ocr = extraer_texto_comprobante(path_img)

                    # ✅ Cargar carpetas desde Drive antes de intentar OCR
                    carpetas_en_drive = listar_carpetas_drive()
                    respuesta_ocr = detectar_modelo_color(texto_ocr, carpetas_en_drive)

                    if respuesta_ocr:
                        est.update({
                            "modelo": respuesta_ocr["modelo"],
                            "color": respuesta_ocr["color"],
                            "marca": respuesta_ocr["marca"],
                            "fase": "imagen_detectada"
                        })
                        estado_usuario[cid] = est

                        os.remove(path_img)  # 🔥 Limpieza de imagen temporal

                        return JSONResponse(respuesta_ocr)

                except Exception as e:
                    logging.warning(f"[OCR] ⚠️ Fallo intento de detección por texto: {e}")

                # 🧠 CLIP - identificación de modelo
                try:
                    logging.info("[CLIP] 🚀 Iniciando identificación de modelo")

                    embeddings_raw = cargar_embeddings_desde_cache()
                    embeddings: dict[str, list[list[float]]] = {}
                    for modelo, vecs in embeddings_raw.items():
                        if isinstance(vecs, list):
                            if len(vecs) == 512 and all(isinstance(x, (int, float)) for x in vecs):
                                embeddings[modelo] = [vecs]
                            else:
                                limpios = [v for v in vecs if isinstance(v, list) and len(v) == 512]
                                if limpios:
                                    embeddings[modelo] = limpios

                    emb_u = generar_embedding_imagen(img)
                    emb_u = torch.tensor(emb_u, dtype=torch.float32)
                    emb_u = torch.nn.functional.normalize(emb_u, dim=-1)
                    if emb_u.shape[0] != 512:
                        raise ValueError(f"Embedding cliente tamaño {emb_u.shape} ≠ 512")

                    mejor_sim, mejor_modelo = 0.0, None
                    for modelo, lista in embeddings.items():
                        for i, emb_ref in enumerate(lista):
                            try:
                                arr_ref = torch.tensor(emb_ref, dtype=torch.float32)
                                arr_ref = torch.nn.functional.normalize(arr_ref, dim=-1)
                                sim = torch.dot(emb_u, arr_ref).item()
                                if sim > mejor_sim:
                                    mejor_sim, mejor_modelo = sim, modelo
                            except Exception as e:
                                logging.warning(f"[CLIP] Error en {modelo}[{i}]: {e}")

                    logging.info(f"[CLIP] Mejor modelo: {mejor_modelo} — Similitud: {mejor_sim:.4f}")

                    if mejor_modelo and mejor_sim >= 0.85:
                        p = mejor_modelo.split("_")
                        estado_usuario.setdefault(cid, reset_estado(cid))
                        estado_usuario[cid].update(
                            fase="imagen_detectada",
                            marca=p[0],
                            modelo=p[1] if len(p) > 1 else "Des.",
                            color="_".join(p[2:]) if len(p) > 2 else "Des."
                        )

                        modelo = estado_usuario[cid]["modelo"]
                        color = estado_usuario[cid]["color"]
                        marca = estado_usuario[cid]["marca"]
                        precio = next(
                            (
                                i["precio"] for i in inv
                                if normalize(i["modelo"]) == normalize(modelo)
                                and normalize(i["color"]) == normalize(color)
                                and normalize(i["marca"]) == normalize(marca)
                            ),
                            None
                        )
                        precio_str = f"{int(precio):,} COP" if precio else "No disponible"

                        return JSONResponse({
                            "type": "text",
                            "text": (
                                f"🟢 ¡Qué buena elección! Los *{modelo}* de color *{color}* están brutales 😎.\n"
                                f"💲 Su precio es: *{precio_str}*, además el *envío es totalmente gratis a todo el país* 🚚.\n"
                                f"🎁 Hoy tienes *5 % de descuento* si pagas ahora.\n\n"
                                "¿Seguimos con la compra?"
                            ),
                            "parse_mode": "Markdown"
                        })
                    else:
                        reset_estado(cid)
                        return JSONResponse({
                            "type": "text",
                            "text": (
                                "❌ No logré identificar bien el modelo de la imagen.\n"
                                "¿Podrías enviarme otra foto un poco más clara?"
                            )
                        })

                except Exception:
                    logging.exception("[CLIP] Error en identificación:")
                    return JSONResponse({
                        "type": "text",
                        "text": "⚠️ Ocurrió un error analizando la imagen."
                    })

        # 💬 TEXTO
        elif mtype == "chat":
                fase_actual = estado_usuario.get(cid, {}).get("fase", "")
                logging.info(f"💬 Texto recibido en fase: {fase_actual or 'NO DEFINIDA'}")
                reply = await procesar_wa(cid, body)

                # A) Dict directo válido
                if isinstance(reply, dict) and reply.get("type") in ("video", "audio", "image", "photo", "multi", "text"):
                        return JSONResponse(reply)

                # B) Lista → convertir a multi
                if isinstance(reply, list):
                        return JSONResponse({"type": "multi", "messages": reply})

                # C) Texto plano (evita text anidado)
                if isinstance(reply, str):
                        return JSONResponse({"type": "text", "text": reply})

                # D) Seguridad: si vino algo raro
                return JSONResponse({"type": "text", "text": "⚠️ Error inesperado. Intenta de nuevo."})



        # 🎙️ AUDIO
        elif mtype in ("audio", "ptt") or mimetype.startswith("audio"):
            try:
                logging.info("🎙️ Audio recibido. Iniciando procesamiento...")
                if not body:
                    return JSONResponse({"type": "text", "text": "❌ No recibí un audio válido."})

                b64_str = body.split(",", 1)[1] if "," in body else body
                audio_bytes = base64.b64decode(b64_str + "===")

                os.makedirs("temp_audio", exist_ok=True)
                audio_path = f"temp_audio/{cid}_voice.ogg"
                with open(audio_path, "wb") as f:
                    f.write(audio_bytes)

                texto_transcrito = await transcribe_audio(audio_path)
                if texto_transcrito:
                    reply = await procesar_wa(cid, texto_transcrito)
                    return JSONResponse(reply)
                else:
                    return JSONResponse({"type": "text", "text": "⚠️ No pude entender bien el audio. ¿Podrías repetirlo?"})

            except Exception:
                logging.exception("❌ Error durante el procesamiento del audio")
                return JSONResponse({
                    "type": "text",
                    "text": "❌ Ocurrió un error al procesar tu audio. Intenta de nuevo."
                })

        # 🤷 TIPO NO MANEJADO
        else:
            logging.warning(f"🤷‍♂️ Tipo de mensaje no manejado: {mtype}")
            return JSONResponse({"type": "text", "text": f"⚠️Disculpe que pena pero no manejamos {mtype} enviame una foto del zapato que deseas: "})

    except Exception:
        logging.exception("🔥 Error general en venom_webhook")
        return JSONResponse(
            {"type": "text", "text": "⚠️ Error interno procesando el mensaje."},
            status_code=200
        )




# -------------------------------------------------------------------------
# 5. Arranque del servidor
# -------------------------------------------------------------------------
if __name__ == "__main__":
    descargar_memoria_ciudades()          # ⬇️ Descarga ciudades.json desde Drive

    # ✅ Cargar lista de ciudades desde archivo
    with open("/var/data/ciudades/ciudades.json", "r", encoding="utf-8") as f:
        CIUDADES_DISPONIBLES = json.load(f)

    descargar_videos_drive()              # ⬇️ Descarga los videos (si no existen)
    descargar_imagenes_catalogo()         # ⬇️ Descarga 1 imagen por modelo del catálogo
    descargar_stickers_drive()
    descargar_video_confianza()
    descargar_audios_bienvenida_drive()
    descargar_imagen_lengueta()
    descargar_metodos_pago_drive()

    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("lector:api", host="0.0.0.0", port=port)
