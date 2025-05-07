# ——— Librerías estándar de Python ———
import os
import io
import base64
import logging
import json
import re
import requests
import random
import string
import datetime
import unicodedata
import difflib
import asyncio
from types import SimpleNamespace
from collections import defaultdict
from transformers import CLIPModel, CLIPProcessor
import subprocess
import torch
from torchvision import transforms

# ——— Librerías externas ———
from dotenv import load_dotenv
from PIL import Image
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
import nest_asyncio
from openai import AsyncOpenAI
import numpy as np

# Google Cloud
from google.cloud import vision
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Telegram
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
logging.basicConfig(level=logging.DEBUG)

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
            return f"✅ La imagen coincide con *{mejor_modelo}* (confianza {mejor_sim:.2f})"
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

def menciona_catalogo(texto: str) -> bool:
    texto = normalize(texto)
    claves = [
        "catalogo", "catálogo", "ver catálogo", "mostrar catálogo",
        "quiero ver", "ver productos", "mostrar productos",
        "ver lo que tienes", "ver tenis", "muéstrame",
        "mostrar lo que tienes", "tenis disponibles"
    ]
    return any(palabra in texto for palabra in claves)

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

WELCOME_TEXT = (
    f"¡Bienvenido a {NOMBRE_NEGOCIO}!\n\n"
    "Si tienes una foto puedes enviarla\n"
    "Si tienes numero de referencia enviamelo\n"
    "Puedes enviarme la foto del pedido\n"
    "Te gustaria ver unos videos de nuestras referencias👟?\n"
    "Cuéntame sin ningún problema 😀"
)
CLIP_INSTRUCTIONS = (
    "Para enviarme una imagen, pulsa el ícono de clip (📎), "
    "selecciona “Galería” o “Archivo” y elige la foto."
)
CATALOG_LINK = "https://wa.me/c/573007607245"
CATALOG_MESSAGE = (
    f"👇🏻AQUÍ ESTA EL CATÁLOGO 🆕\n"
    f"Sigue este enlace para ver la ultima colección 👟 X💯: {CATALOG_LINK}"
)

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

    return fase in fases_validas

def enviar_correo(dest, subj, body):
    logging.info(f"[EMAIL STUB] To: {dest}\nSubject: {subj}\n{body}")

def enviar_correo_con_adjunto(dest, subj, body, adj):
    logging.info(f"[EMAIL STUB] To: {dest}\nSubject: {subj}\n{body}\n[Adj: {adj}]")

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
        "marca": None, "modelo": None, "color": None, "talla": None,
        "nombre": None, "correo": None, "telefono": None,
        "ciudad": None, "provincia": None, "direccion": None,
        "referencia": None, "resumen": None, "sale_id": None
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

# 🔥 Enviar video de referencia (un solo archivo para varias referencias)
async def enviar_video_referencia(cid, ctx, referencia):
    try:
        referencias_soportadas = ["261", "277", "303", "295", "299", "ds 261", "ds 277", "ds 303", "ds 295", "ds 299"]
        ref = normalize(referencia.lower())

        if ref in referencias_soportadas:
            ruta_video = "videosreferencias_top.MP4"  # Asegúrate que esté al mismo nivel del archivo .py
            if os.path.exists(ruta_video):
                with open(ruta_video, "rb") as video:
                    await ctx.bot.send_video(
                        chat_id=cid,
                        video=video,
                        caption=(
                            f"🎬 Video de referencia {referencia.upper()}.\n"
                            "¿Deseas continuar tu compra? (SI/NO)"
                        ),
                        parse_mode="Markdown"
                    )
                return

        await ctx.bot.send_message(
            chat_id=cid,
            text="😕 Por ahora solo tengo un video para las referencias DS 261, 277, 303, 295 y 299.",
            parse_mode="Markdown"
        )

    except Exception as e:
        logging.error(f"[Video] ❌ Error: {e}")
        await ctx.bot.send_message(
            chat_id=cid,
            text="⚠️ Hubo un error enviando el video. Intenta de nuevo."
        )

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

def decodificar_imagen_base64(base64_str: str) -> Image.Image:
    data = base64.b64decode(base64_str + "===")
    return Image.open(io.BytesIO(data)).convert("RGB")

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

# ───────────────────────────────────────────────────────────────

# 🔥 Registrar la orden en Google Sheets
def registrar_orden(data: dict, fase: str = ""):
    payload = {
        "numero_venta": data.get("Número Venta", ""),
        "fecha_venta":  data.get("Fecha Venta", ""),
        "cliente":      data.get("Cliente", ""),
        "cedula":       data.get("Cédula", ""),  # ✅ NUEVO
        "telefono":     data.get("Teléfono", ""),
        "producto":     data.get("Producto", ""),
        "color":        data.get("Color", ""),
        "talla":        data.get("Talla", ""),
        "correo":       data.get("Correo", ""),
        "pago":         data.get("Pago", ""),
        "estado":       data.get("Estado", ""),
        "fase_actual":  fase                     # ✅ NUEVO
    }
    logging.info(f"[SHEETS] Payload JSON que envío:\n{payload}")
    try:
        resp = requests.post(URL_SHEETS_PEDIDOS, json=payload)
        logging.info(f"[SHEETS] HTTP {resp.status_code} — Body: {resp.text}")
    except Exception as e:
        logging.error(f"[SHEETS] Error al hacer POST: {e}")

# ───────────────────────────────────────────────────────────────

# 🔥 Generar ID único para una venta
def generate_sale_id() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    rnd = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"VEN-{ts}-{rnd}"



# --------------------------------------------------------------------------------------------------

async def responder(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id

    # 1) Primer contacto: saludo
    if cid not in estado_usuario:
        reset_estado(cid)
        await update.message.reply_text(
            WELCOME_TEXT,
            reply_markup=menu_botones([
                "Hacer pedido", "Enviar imagen", "Ver catálogo",
                "Rastrear pedido", "Realizar cambio"
            ])
        )
        return

    # 2) Estado actual e inventario
    est = estado_usuario[cid]
    inv = obtener_inventario()

    # 3) Captura y normaliza texto
    txt_raw = update.message.text or ""
    txt = normalize(txt_raw)

    # ✅ DEBUG real
    print("🧠 FASE:", est.get("fase"))
    print("🧠 TEXTO:", txt_raw, "|", repr(txt_raw))
    print("🧠 ESTADO:", est)

    # 4) Reinicio explícito si escribe /start o similares
    if txt in ("reset", "reiniciar", "empezar", "volver", "/start", "menu", "inicio"):
        reset_estado(cid)
        await update.message.reply_text(
            WELCOME_TEXT,
            reply_markup=menu_botones([
                "Hacer pedido", "Enviar imagen", "Ver catálogo",
                "Rastrear pedido", "Realizar cambio"
            ])
        )
        return

    # 5) Muestra el catálogo si lo menciona
    if menciona_catalogo(txt_raw):
        await ctx.bot.send_message(
            chat_id=cid,
            text=CATALOG_MESSAGE
        )
        est["fase"] = "inicio"
        return

    # 🎬 Si pide videos normales
    if any(frase in txt for frase in ("videos", "quiero videos", "ver videos", "video")):
        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                "🎬 ¡Claro! Aquí tienes videos de nuestras referencias más populares:\n\n"
                "• DS 261🔥 277🔥 303🔥 295🔥 299\n"
                "• PROMO 39%🔥\n"
                "• Referencias niño🔥\n\n"
                "¿Cuál te gustaría ver?"
            ),
            reply_markup=menu_botones(["DS 277", "DS 261", "DS 303"]),
            parse_mode="Markdown"
        )
        est["fase"] = "esperando_video_referencia"
        estado_usuario[cid] = est
        return

    # 🎬 Esperar selección de video
    if est.get("fase") == "esperando_video_referencia":
        # Ignora coincidencia con modelo tipo 261
        if re.match(r"^\d{3}$", txt_raw.strip()):
            await enviar_video_referencia(cid, ctx, txt)
            est["fase"] = "inicio"
            estado_usuario[cid] = est
            return

        await ctx.bot.send_message(
            chat_id=cid,
            text="👀 Solo necesito el número de referencia, como 261 o 277. Intenta de nuevo."
        )
        return

# ─────────── Preguntas frecuentes (FAQ) ───────────
    if est.get("fase") not in ("esperando_pago", "esperando_comprobante"):

        # FAQ 1: ¿Cuánto demora el envío?
        if any(frase in txt for frase in (
            "cuanto demora", "cuánto demora", "cuanto tarda", "cuánto tarda",
            "cuanto se demora", "cuánto se demora", "en cuanto llega", "en cuánto llega",
            "me llega rapido", "llegan rapido"
        )):
            await ctx.bot.send_message(
                chat_id=cid,
                text=(
                    "🚚 El tiempo de entrega depende de la ciudad de destino, "
                    "pero generalmente tarda *2 días hábiles* en llegar.\n\n"
                    "Si lo necesitas para *mañana mismo*, podemos enviarlo al terminal de transporte. "
                    "En ese caso aplica *pago anticipado* (no contra entrega)."
                ),
                parse_mode="Markdown"
            )
            return

        # FAQ 2: ¿Tienen pago contra entrega?
        if any(frase in txt for frase in (
            "pago contra entrega", "pago contraentrega", "contraentrega", "contra entrega",
            "pagan al recibir", "puedo pagar al recibir", "tienen contra entrega"
        )):
            await ctx.bot.send_message(
                chat_id=cid,
                text=(
                    "📦 ¡Claro que sí! Tenemos *pago contra entrega*.\n\n"
                    "Pedimos un *anticipo de $35 000* que cubre el envío. "
                    "Ese valor se descuenta del precio total cuando recibes el pedido."
                ),
                parse_mode="Markdown"
            )
            return

        # FAQ 3: ¿Tienen garantía?
        if any(frase in txt for frase in (
            "tienen garantia", "tienen garantía", "hay garantía", "hay garantia",
            "garantía", "garantia", "tienen garantia de fabrica"
        )):
            await ctx.bot.send_message(
                chat_id=cid,
                text=(
                    "🛡️ Todos nuestros productos tienen *garantía de 60 días* "
                    "por defectos de fábrica o problemas de pegado.\n\n"
                    "Cualquier inconveniente, estamos para ayudarte."
                ),
                parse_mode="Markdown"
            )
            return


    # ... puedes dejar tus demás FAQs igual que están ...

    # FAQ 4: ¿Cómo sé que no me van a robar?
    if any(frase in txt for frase in (
        "no me van a robar", "me van a robar", "es seguro",
        "como se que es seguro", "no es estafa", "es confiable",
        "me estafan", "roban por internet", "es real", "desconfío",
        "no me da confianza", "no confío", "dudas"
    )):
        video_url = "https://tudominio.com/videos/video_confianza.mp4"
        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                "🤝 Entendemos tu preocupación. "
                "Te compartimos este video para que veas que somos una tienda real y seria."
            ),
            parse_mode="Markdown"
        )
        await ctx.bot.send_chat_action(chat_id=cid, action=ChatAction.UPLOAD_VIDEO)
        await ctx.bot.send_video(
            chat_id=cid,
            video=video_url,
            caption="¡Estamos aquí para ayudarte en lo que necesites! 👟✨"
        )
        return

    # FAQ 5: ¿Dónde están ubicados?
    if any(frase in txt for frase in (
        "donde estan ubicados", "donde queda", "ubicacion", "ubicación",
        "direccion", "dirección", "donde estan", "donde es la tienda",
        "estan ubicados", "ubicados en donde", "en que ciudad estan", "en que parte estan"
    )):
        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                "📍 Estamos en *Bucaramanga, Santander*.\n\n"
                "🏡 *Barrio San Miguel, Calle 52 #16-74*\n\n"
                "🚚 ¡Enviamos a todo Colombia con Servientrega!\n\n"
                "Ubicación Google Maps: https://maps.google.com/?q=7.109500,-73.121597"
            ),
            parse_mode="Markdown"
        )
        return

    # FAQ 6: ¿Son nacionales o importados?
    if any(frase in txt for frase in (
        "son nacionales", "son importados", "es nacional o importado",
        "nacionales o importados", "hecho en colombia", "fabricados en colombia",
        "son de aqui", "es de colombia", "fabricacion colombiana"
    )):
        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                "🇨🇴 Nuestra marca es *100 % colombiana* y las zapatillas "
                "se elaboran con orgullo en *Bucaramanga* por artesanos locales."
            ),
            parse_mode="Markdown"
        )
        return

    # FAQ 7: ¿Son originales?
    if any(frase in txt for frase in (
        "son originales", "es original", "originales",
        "es copia", "son copia", "son replica", "réplica", "imitacion"
    )):
        await ctx.bot.send_message(
            chat_id=cid,
            text="✅ ¡Claro! Son *originales*. Somos *X100*, marca 100 % colombiana reconocida por su calidad y diseño.",
            parse_mode="Markdown"
        )
        return

    # FAQ 8: ¿De qué calidad son?
    if any(frase in txt for frase in (
        "que calidad son", "de que calidad son", "son buena calidad", "son de buena calidad",
        "son de mala calidad", "que calidad manejan", "que calidad tienen", "calidad de las zapatillas"
    )):
        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                "✨ Nuestras zapatillas están elaboradas con *materiales de alta calidad*.\n\n"
                "Cada par se fabrica cuidadosamente para asegurar *calidad AAA* 👟🔝, "
                "garantizando comodidad, durabilidad y excelente acabado."
            ),
            parse_mode="Markdown"
        )
        return

    # FAQ 9: ¿Hay descuento si compro 2 pares?
    if any(frase in txt for frase in (
        "si compro 2 pares", "dos pares descuento", "descuento por 2 pares",
        "descuento por dos pares", "me descuentan si compro dos", "descuento si compro dos",
        "hay descuento por dos", "promocion dos pares", "descuento en 2 pares"
    )):
        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                "🎉 ¡Sí! Si compras *2 pares* te damos un *10% de descuento adicional* sobre el total.\n\n"
                "¡Aprovecha para estrenar más y pagar menos! 🔥👟👟"
            ),
            parse_mode="Markdown"
        )
        return

    # FAQ 10: ¿Manejan precios para mayoristas?
    if any(frase in txt for frase in (
        "precio mayorista", "precios para mayoristas", "mayorista", "quiero vender",
        "puedo venderlos", "descuento para revender", "revender", "comprar para vender",
        "manejan precios para mayoristas", "mayoreo", "venta al por mayor"
    )):
        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                "🛍️ ¡Claro! Manejamos *precios para mayoristas* en pedidos de *6 pares en adelante*, "
                "sin importar tallas ni referencias.\n\n"
                "Condición: vender mínimo al mismo precio que nosotros para cuidar el mercado."
            ),
            parse_mode="Markdown"
        )
        return

    # FAQ 11: ¿Las tallas son normales o grandes?
    if any(frase in txt for frase in (
        "las tallas son normales", "horma normal", "talla normal",
        "horma grande", "horma pequeña", "tallas grandes", "tallas pequeñas",
        "las tallas son grandes", "las tallas son pequeñas", "como son las tallas"
    )):
        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                "👟 Nuestra horma es *normal*. Si calzas talla *40* nacional, te queda bien la *40* de nosotros.\n\n"
                "Para mayor seguridad, puedes enviarnos una foto de la *etiqueta interna* de tus tenis actuales 📏✨."
            ),
            parse_mode="Markdown"
        )
        return

    # FAQ 12: ¿Cuál es la talla más grande que manejan?
    if any(frase in txt for frase in (
        "talla mas grande", "talla más grande", "cual es la talla mas grande",
        "hasta que talla llegan", "mayor talla", "talla maxima", "talla máxima"
    )):
        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                "📏 La talla más grande que manejamos es:\n\n"
                "• *45 Nacional* 🇨🇴\n"
                "• *47 Europeo* 🇪🇺\n\n"
                "¡También tenemos opciones para pies grandes! 👟✨"
            ),
            parse_mode="Markdown"
        )
        return

    # 📷 Si el usuario envía una foto (detectamos modelo automáticamente)
    if update.message.photo:
        f = await update.message.photo[-1].get_file()
        tmp = os.path.join("temp", f"{cid}.jpg")
        os.makedirs("temp", exist_ok=True)
        await f.download_to_drive(tmp)

        # ➜ convert to base64 y usar CLIP
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
        if any(frase in txt for frase in ("si", "sí", "s", "claro", "claro que sí", "quiero comprar", "continuar", "vamos")):
            est["fase"] = "esperando_talla"
            tallas = obtener_tallas_por_color(inv, est["modelo"], est["color"])
            if isinstance(tallas, (int, float, str)):
                tallas = [str(tallas)]

            await ctx.bot.send_message(
                chat_id=cid,
                text=(
                    f"Perfecto 🎯 ¿Qué talla deseas para el modelo *{est['modelo']}* color *{est['color']}*?\n\n"
                    f"👉 Opciones: {', '.join(tallas)}"
                ),
                parse_mode="Markdown"
            )
            return
        else:
            await ctx.bot.send_message(
                chat_id=cid,
                text="Cancelado. /start para reiniciar o cuéntame si quieres ver otra referencia. 📋",
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
                    f"Perfecto 🎯 ¿Qué talla deseas para el modelo *{est['modelo']}* color *{est['color']}*?\n\n"
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

    # 👟 Elegir talla
    if est.get("fase") == "esperando_talla":
        tallas = obtener_tallas_por_color(inv, est["modelo"], est["color"])
        if isinstance(tallas, (int, float, str)):
            tallas = [str(tallas)]

        talla_detectada = detectar_talla(txt_raw, tallas)

        if talla_detectada:
            est["talla"] = talla_detectada
            est["fase"] = "esperando_nombre"
            await ctx.bot.send_message(
                chat_id=cid,
                text="¿Tu nombre completo? 👤",
                parse_mode="Markdown"
            )
        else:
            await ctx.bot.send_message(
                chat_id=cid,
                text=f"⚠️ Las tallas disponibles para {est['modelo']} color {est['color']} son:\n{', '.join(tallas)}",
                parse_mode="Markdown",
                reply_markup=menu_botones(tallas),
            )
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
                text="⚠️ Correo inválido. Intenta de nuevo.",
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
                text="⚠️ Teléfono inválido. Intenta de nuevo.",
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
                text="⚠️ Cédula inválida. Intenta de nuevo solo con números.",
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
        sale_id = generate_sale_id()
        est["sale_id"] = sale_id
        est["resumen"] = {
            "Número Venta": sale_id,
            "Fecha Venta": datetime.datetime.now().isoformat(),
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

        msg = (
            f"✅ Pedido: {sale_id}\n"
            f"👤Nombre: {est['nombre']}\n"
            f"📧Correo: {est['correo']}\n"
            f"📱Celular: {est['telefono']}\n"
            f"📍Dirección: {est['direccion']}, {est['ciudad']}, {est['provincia']}\n"
            f"👟Producto: {est['modelo']} color {est['color']} talla {est['talla']}\n"
            f"💲Valor a pagar: {precio:,} COP\n\n"
            "¿Cómo deseas hacer el pago?\n"
            "•💸 Contraentrega: adelanta 35 000 COP para el envío (se descuenta del total).\n"
            "• 💰Transferencia inmediata: paga completo hoy y obtén 5 % de descuento.\n\n"
            "Escribe tu método de pago: Transferencia o Contraentrega."
        )
        await ctx.bot.send_message(chat_id=cid, text=msg)
        est["fase"] = "esperando_pago"
        estado_usuario[cid] = est
        return


    # 💳 Método de pago
    if est.get("fase") == "esperando_pago":
        print("🧪 ENTRÓ AL BLOQUE DE PAGO ✅")

        # Sinónimos que reconocemos
        opciones = {
            "transferencia": ["transferencia", "trasferencia", "transf", "trans", "pago inmediato", "qr"],
            "contraentrega": ["contraentrega", "contra entrega", "contra", "contrapago"]
        }

        txt_normalizado = normalize(txt_raw)

        # ── Detectar método ────────────────────────────────────────────────────
        metodo_detectado = None
        for metodo, variantes in opciones.items():
            coincidencias = difflib.get_close_matches(txt_normalizado, variantes, n=1, cutoff=0.6)
            if coincidencias:
                metodo_detectado = metodo
                break

        # No entendimos
        if not metodo_detectado:
            await ctx.bot.send_message(
                chat_id=cid,
                text="💳 No entendí el método de pago. Escribe *transferencia* o *contraentrega* 😊",
                parse_mode="Markdown"
            )
            return

        # Guardar elección
        est["metodo_pago"] = metodo_detectado
        resumen = est["resumen"]
        precio_original = est.get("precio_total", 0)
        precio_original = int(precio_original)

        print("💰 MÉTODO DETECTADO:", metodo_detectado)

        # ── TRANSFERENCIA ─────────────────────────────────────────────────────
        if metodo_detectado == "transferencia":
            est["fase"] = "esperando_comprobante"
            resumen["Pago"] = "Transferencia"
            descuento = round(precio_original * 0.05)
            valor_final = precio_original - descuento
            resumen["Descuento"] = f"-{descuento} COP"
            resumen["Valor Final"] = valor_final

            msg = (
                "🟢 Elegiste *TRANSFERENCIA*.\n\n"
                f"💰 Valor original: {precio_original:,} COP\n"
                f"🎉 Descuento 5 %: -{descuento:,} COP\n"
                f"✅ Total a pagar: {valor_final:,} COP\n\n"
                "💳 Cuentas disponibles:\n"
                "- Bancolombia 30300002233 (X100 SAS)\n"
                "- Nequi 3177171171\n"
                "- Daviplata 3004141021\n\n"
                "📸 Envía la foto del comprobante aquí."
            )

            await ctx.bot.send_message(chat_id=cid, text=msg, parse_mode="Markdown")

        # ── CONTRAENTREGA ─────────────────────────────────────────────────────
        else:  # contraentrega
            est["fase"] = "esperando_comprobante"
            resumen["Pago"] = "Contra entrega"
            resumen["Valor Anticipo"] = 35000

            msg = (
                "🟡 Elegiste *CONTRAENTREGA*.\n\n"
                "Debes adelantar *35 000 COP* para el envío (se descuenta del total).\n\n"
                "💳 Cuentas disponibles:\n"
                "- Bancolombia 30300002233 (X100 SAS)\n"
                "- Nequi 3177171171\n"
                "- Daviplata 3004141021\n\n"
                "📸 Envía la foto del comprobante aquí."
            )

            await ctx.bot.send_message(chat_id=cid, text=msg, parse_mode="Markdown")

        estado_usuario[cid] = est  # Guarda cambios
        return


    # ------------------------------------------------------------------------
    # 📸 Recibir comprobante de pago
    # ------------------------------------------------------------------------
    if est.get("fase") == "esperando_comprobante" and update.message.photo:
        f = await update.message.photo[-1].get_file()
        tmp = os.path.join("temp", f"{cid}_proof.jpg")
        os.makedirs("temp", exist_ok=True)
        await f.download_to_drive(tmp)

        # OCR con Google Cloud Vision
        with io.open(tmp, "rb") as image_file:
            content = image_file.read()
        image = vision.Image(content=content)
        response = vision_client.text_detection(image=image)
        textos_detectados = response.text_annotations

        texto_extraido = textos_detectados[0].description if textos_detectados else ""
        print("🧾 TEXTO EXTRAÍDO:\n", texto_extraido)

        # Verificación básica del comprobante
        if not es_comprobante_valido(texto_extraido):
            await ctx.bot.send_message(
                chat_id=cid,
                text="⚠️ El comprobante no parece válido. Asegúrate de que sea legible y que diga 'Pago exitoso' o 'Transferencia realizada'."
            )
            os.remove(tmp)
            return

        # Si es válido, continuar flujo
        resumen = est["resumen"]
        registrar_orden(resumen)

        enviar_correo(
            est["correo"],
            f"Pago recibido {resumen['Número Venta']}",
            json.dumps(resumen, indent=2)
        )
        enviar_correo_con_adjunto(
            EMAIL_JEFE,
            f"Comprobante {resumen['Número Venta']}",
            json.dumps(resumen, indent=2),
            tmp
        )

        os.remove(tmp)

        await ctx.bot.send_message(
            chat_id=cid,
            text="✅ ¡Pago registrado exitosamente! Tu pedido está en proceso. 🚚"
        )

        reset_estado(cid)
        estado_usuario.pop(cid, None)
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

    # 🖼️ Intención global de imagen
    if menciona_imagen(txt):
        if est.get("fase") != "esperando_imagen":
            est["fase"] = "esperando_imagen"
            await update.message.reply_text(CLIP_INSTRUCTIONS, reply_markup=ReplyKeyboardRemove())
        return

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
                    text=f"Perfecto 🎯 ¿Qué talla deseas para el modelo *{modelo}* color *{colores[0]}*?\n👉 Tallas disponibles: {', '.join(tallas)}",
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


    # 🔒 Video de confianza si desconfía
    if any(frase in txt for frase in (
        "no me fio", "no confio", "es seguro", "como se que no me roban",
        "como se que no me estafan", "desconfio", "no creo", "estafa", "miedo a comprar"
    )):
        VIDEO_DRIVE_ID = "TU_ID_DEL_VIDEO_DE_CONFIANZA"
        video_url = f"https://drive.google.com/uc?id={VIDEO_DRIVE_ID}"

        await ctx.bot.send_chat_action(chat_id=cid, action=ChatAction.UPLOAD_VIDEO)
        await ctx.bot.send_video(
            chat_id=cid,
            video=video_url,
            caption=(
                "🔒 Entendemos perfectamente tu preocupación. "
                "Aquí te dejamos un video corto donde nuestros clientes reales comparten su experiencia. "
                "Somos una empresa seria y segura, ¡puedes confiar en nosotros! 😊👍"
            )
        )
        return


    if await manejar_precio(update, ctx, inv):
        return

    if await manejar_catalogo(update, ctx):
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

    # 1) Detectar palabras típicas primero (antes que IA)
    palabras_clave_flujo = [
        "catalogo", "catálogo", "ver catálogo", "ver catalogo",
        "imagen", "foto", "enviar imagen", "ver tallas",
        "quiero comprar", "hacer pedido", "comprar", "zapatos", "tenis",
        "pago", "contraentrega", "garantía", "garantia",
        "demora", "envío", "envio"
    ]

    if any(palabra in txt for palabra in palabras_clave_flujo):
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

# Función para manejar la solicitud de precio por referencia
PALABRAS_PRECIO = ['precio', 'vale', 'cuesta', 'valor', 'coste', 'precios', 'cuánto']

async def manejar_precio(update, ctx, inventario):
    cid = update.effective_chat.id
    mensaje = (update.message.text or "").lower()
    txt = normalize(mensaje)
    logging.debug(f"[manejar_precio] Mensaje recibido: {mensaje}")

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
        est = estado_usuario.get(cid, {})
        est["fase"] = "confirmar_compra"
        est["modelo_confirmado"] = primer_producto["modelo"]
        est["color_confirmado"] = primer_producto["color"]
        est["marca"] = primer_producto.get("marca", "sin marca")
        estado_usuario[cid] = est  # ✅ GUARDA el estado correctamente

        logging.debug(f"[manejar_precio] Guardado modelo: {primer_producto['modelo']}, color: {primer_producto['color']}")

        await ctx.bot.send_message(
            chat_id=cid,
            text=(
                f"Veo que estás interesado en nuestra referencia *{referencia}*:\n\n"
                f"{respuesta_final}"
                "¿Te gustaría proseguir con la compra?\n\n"
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

from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def responder_con_openai(mensaje_usuario):
    try:
        respuesta = await client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres un asesor de ventas de la tienda de zapatos deportivos 'X100🔥👟'. "
                        "Solo vendemos nuestra propia marca *X100* (no manejamos marcas como Skechers, Adidas, Nike, etc.). "
                        "Nuestros productos son 100% colombianos 🇨🇴 y hechos en Bucaramanga.\n\n"
                        "Tu objetivo principal es:\n"
                        "- Si preguntan por precio di, dime que referencia exacta buscas\n"
                        "- Siempre que puedas pedir la referencia del teni\n"
                        "- Pedir que envíe una imagen del zapato que busca 📸\n"
                        "Siempre que puedas, invita amablemente al cliente a enviarte el número de referencia o una imagen para agilizar el pedido.\n"
                        "Si el cliente pregunta por marcas externas, responde cálidamente explicando que solo manejamos X100.\n\n"
                        "Cuando no entiendas muy bien la intención, ofrece opciones como:\n"
                        "- '¿Me puedes enviar la referencia del modelo que te interesa? 📋✨'\n"
                        "- '¿Quieres enviarme una imagen para ayudarte mejor? 📸'\n\n"
                        "Responde de forma CÁLIDA, POSITIVA, BREVE (máximo 2 o 3 líneas), usando emojis amistosos 🎯👟🚀✨.\n"
                        "Actúa como un asesor de ventas que siempre busca ayudar al cliente y CERRAR la compra de manera rápida, amigable y eficiente."
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
        logging.error(f"Error al consultar OpenAI: {e}")
        return "Disculpa, estamos teniendo un inconveniente en este momento. ¿Puedes intentar de nuevo más tarde?"


# 4. Procesar mensaje de WhatsApp
async def procesar_wa(cid: str, body: str) -> dict:
    cid = str(cid)  # 🔐 Asegura que el ID sea string SIEMPRE
    texto = body.lower() if body else ""
    txt = texto if texto else ""

    class DummyCtx(SimpleNamespace):
        async def bot_send(self, chat_id, text, **kw): self.resp.append(text)
        async def bot_send_chat_action(self, chat_id, action, **kw): pass
        async def bot_send_video(self, chat_id, video, caption=None, **kw): self.resp.append(f"[VIDEO] {caption or ' '}]")

    # 👇 Define ctx primero
    ctx = DummyCtx(resp=[])

    # 👇 Ahora sí define ctx.bot correctamente
    ctx.bot = SimpleNamespace(
        send_message=ctx.bot_send,
        send_chat_action=ctx.bot_send_chat_action,
        send_video=ctx.bot_send_video
    )

    class DummyMsg(SimpleNamespace):
        def __init__(self, text, ctx, photo=None, voice=None, audio=None):
            self.text = text
            self.photo = photo
            self.voice = voice
            self.audio = audio
            self._ctx = ctx

        async def reply_text(self, text, **kw):
            self._ctx.resp.append(text)

    dummy_msg = DummyMsg(text=body, ctx=ctx, photo=None, voice=None, audio=None)
    dummy_update = SimpleNamespace(
        message=dummy_msg,
        effective_chat=SimpleNamespace(id=cid)
    )

    # 🧠 Revisa si el estado no existe o está vacío
    if cid not in estado_usuario or not estado_usuario[cid].get("fase"):
        reset_estado(cid)
        estado_usuario[cid] = {"fase": "inicio"}

    # 💬 Si es saludo o /start, siempre responde algo básico
    if texto in ["/start", "start", "hola", "buenas", "hey"]:
        logging.info("[BOT] Comando /start o saludo detectado.")
        reset_estado(cid)
        return {
            "type": "text",
            "text": "¡Bienvenido a *X100🔥👟*!\n\nSi tienes una foto puedes enviarla\nSi tienes número de referencia, envíamelo\nPuedes enviarme la foto del pedido\n¿Te gustaría ver unos videos de nuestras referencias?\nCuéntame sin problema 😀"
        }

    try:
        await responder(dummy_update, ctx)

        if ctx.resp:
            print(f"[DEBUG] BOT respondió correctamente: {ctx.resp}")
            return {"type": "text", "text": "\n".join(ctx.resp)}
        else:
            est = estado_usuario.get(cid, {})
            if est.get("fase") in ("esperando_pago", "esperando_comprobante"):
                print("[DEBUG] Fase crítica: el bot no respondió pero no se usará IA.")
                return {"type": "text", "text": "💬 Estoy esperando que confirmes tu método de pago o me envíes el comprobante. 📸"}

            print(f"[DEBUG] BOT no respondió nada, se usará IA para el mensaje: {body}")
            respuesta_ia = await responder_con_openai(body)
            return {"type": "text", "text": respuesta_ia or "🤖 Estoy teniendo problemas, pero ya estoy revisando..."}

    except Exception as e:
        print(f"🔥 Error interno en procesar_wa(): {e}")
        print(f"[DEBUG] Usando IA como fallback por error de bot en mensaje: {body}")
        try:
            respuesta_ia = await responder_con_openai(body)
            return {"type": "text", "text": respuesta_ia or "🤖 Estoy teniendo problemas, pero ya estoy revisando..."}
        except Exception as fallback_error:
            logging.error(f"[FALLBACK] También falló responder_con_openai: {fallback_error}")
            return {"type": "text", "text": "⚠️ Hubo un error inesperado. Por favor intenta de nuevo."}
@api.post("/venom")
async def venom_webhook(req: Request):
    """Webhook principal que recibe los mensajes de Venom y procesa imagen, audio o texto."""
    try:
        # 1️⃣ Leer JSON ------------------------------------------------------
        data = await req.json()
        cid = wa_chat_id(data.get("from", ""))
        body = data.get("body", "") or ""
        mtype = (data.get("type") or "").lower()
        mimetype = (data.get("mimetype") or "").lower()

        logging.info(f"📩 Mensaje recibido — CID: {cid} — Tipo: {mtype} — MIME: {mimetype}")

        # 2️⃣ IMAGEN ---------------------------------------------------------
        if mtype == "image" or mimetype.startswith("image"):
            try:
                b64_str = body.split(",", 1)[1] if "," in body else body
                img_bytes = base64.b64decode(b64_str + "===")
                img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                logging.info(f"✅ Imagen decodificada correctamente. Tamaño: {img.size}")
            except Exception as e:
                logging.error(f"❌ No pude leer la imagen: {e}")
                return JSONResponse({"type": "text", "text": "❌ No pude leer la imagen 😕"})

            # 🧠 Estado actual del usuario
            est = estado_usuario.get(cid, {})
            fase = est.get("fase", "")
            logging.info(f"🔍 Fase actual del usuario {cid}: {fase or 'NO DEFINIDA'}")

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
                        registrar_orden(resumen)

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

            # 4️⃣ CLIP --------------------------------------------------------
            else:
                try:
                    logging.info("[CLIP] 🚀 Iniciando identificación de modelo")

                    # 4.1️⃣ Cargar embeddings
                    embeddings_raw = cargar_embeddings_desde_cache()
                    logging.debug(f"[CLIP] Embeddings cargados: {len(embeddings_raw)} modelos")

                    embeddings: dict[str, list[list[float]]] = {}
                    for modelo, vecs in embeddings_raw.items():
                        if isinstance(vecs, list):
                            if len(vecs) == 512 and all(isinstance(x, (int, float)) for x in vecs):
                                embeddings[modelo] = [vecs]
                            else:
                                limpios = [v for v in vecs if isinstance(v, list) and len(v) == 512]
                                if limpios:
                                    embeddings[modelo] = limpios

                    # 4.2️⃣ Guardar imagen temporal
                    os.makedirs("temp", exist_ok=True)
                    path_img = f"temp/{cid}_img.jpg"
                    with open(path_img, "wb") as f:
                        f.write(img_bytes)

                    logging.debug(f"[CLIP] Imagen cliente tamaño: {img.size}")

                    # 4.3️⃣ Generar embedding cliente
                    emb_u = generar_embedding_imagen(img)
                    emb_u = torch.tensor(emb_u, dtype=torch.float32)
                    emb_u = torch.nn.functional.normalize(emb_u, dim=-1)
                    if emb_u.shape[0] != 512:
                        raise ValueError(f"Embedding cliente tamaño {emb_u.shape} ≠ 512")
                    logging.debug(f"[CLIP] Embedding cliente listo — Shape: {emb_u.shape}")
                    logging.info(f"[DEBUG] Embedding usuario (primeros 5): {emb_u[:5]}")

                    # 4.4️⃣ Comparar con embeddings existentes
                    mejor_sim, mejor_modelo = 0.0, None
                    for modelo, lista in embeddings.items():
                        for i, emb_ref in enumerate(lista):
                            try:
                                arr_ref = torch.tensor(emb_ref, dtype=torch.float32)
                                arr_ref = torch.nn.functional.normalize(arr_ref, dim=-1)
                                sim = torch.dot(emb_u, arr_ref).item()
                                logging.debug(f"[CLIP] Sim {modelo}[{i}]: {sim:.4f}")
                                if sim > mejor_sim:
                                    mejor_sim, mejor_modelo = sim, modelo
                            except Exception as e:
                                logging.warning(f"[CLIP] Error en {modelo}[{i}]: {e}")

                    logging.info(f"[DEBUG] Mejor modelo obtenido: {mejor_modelo} — Similitud: {mejor_sim:.4f}")
                    logging.info(f"🔍 Modelo detectado: {mejor_modelo} — Similitud: {mejor_sim:.4f}")

                    # 4.5️⃣ Respuesta final
                    if mejor_modelo and mejor_sim >= 0.85:
                        logging.info(f"[CLIP] 🎯 Mejor: {mejor_modelo} ({mejor_sim:.2f})")
                        p = mejor_modelo.split("_")
                        estado_usuario.setdefault(cid, reset_estado(cid))
                        estado_usuario[cid].update(
                            fase="imagen_detectada",
                            marca=p[0],
                            modelo=p[1] if len(p) > 1 else "Des.",
                            color="_".join(p[2:]) if len(p) > 2 else "Des."
                        )
                        return JSONResponse({
                            "type": "text",
                            "text": (
                                f"✅ La imagen coincide con *{mejor_modelo}* "
                                f"(confianza {mejor_sim:.2f})\n¿Continuamos? (SI/NO)"
                            )
                        })
                    else:
                        reset_estado(cid)
                        return JSONResponse({
                            "type": "text",
                            "text": (
                                "❌ No identifiqué un modelo con confianza suficiente. "
                                "Intenta otra foto."
                            )
                        })

                except Exception:
                    logging.exception("[CLIP] Error en identificación:")
                    return JSONResponse({
                        "type": "text",
                        "text": "⚠️ Ocurrió un error analizando la imagen."
                    })

        # 5️⃣ TEXTO ----------------------------------------------------------
        elif mtype == "chat":
            fase_actual = estado_usuario.get(cid, {}).get("fase", "")
            logging.info(f"💬 Texto recibido en fase: {fase_actual or 'NO DEFINIDA'}")
            reply = await procesar_wa(cid, body)
            return JSONResponse(reply)

        # 6️⃣ AUDIO ----------------------------------------------------------
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

        # 7️⃣ TIPO NO MANEJADO -----------------------------------------------
        else:
            logging.warning(f"🤷‍♂️ Tipo de mensaje no manejado: {mtype}")
            return JSONResponse({"type": "text", "text": f"⚠️ Tipo no manejado: {mtype}"})

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
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("lector:api", host="0.0.0.0", port=port)


