import os
import io
import json
import logging
from PIL import Image
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

import torch
from transformers import CLIPProcessor, CLIPModel
from torch.nn.functional import normalize

# Configuración
logging.basicConfig(level=logging.INFO)
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
FOLDER_ID = '1OXHjSG82RO9KGkNIZIRVusFpFhZlujQE'

# 🔐 Cargar credenciales desde variable de entorno (Render)
creds_info = json.loads(os.environ["GOOGLE_CREDS_JSON"])
creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)

# Cargar modelo CLIP
clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
clip_model.eval()
clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

# Usar CPU (en Render no hay GPU por defecto)
device = "cpu"
clip_model.to(device)

def generar_embedding(image: Image.Image):
    inputs = clip_processor(images=image, return_tensors="pt").to(device)
    with torch.no_grad():
        emb = clip_model.get_image_features(**inputs)
        emb = normalize(emb, dim=-1)
    return emb[0].cpu().numpy().tolist()

def cargar_servicio_drive():
    return build('drive', 'v3', credentials=creds)

def listar_carpetas(service, folder_id):
    resultados = service.files().list(
        q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed = false",
        fields="files(id, name)").execute()
    return resultados.get('files', [])

def listar_imagenes(service, folder_id):
    resultados = service.files().list(
        q=f"'{folder_id}' in parents and mimeType contains 'image/' and trashed = false",
        fields="files(id, name)").execute()
    return resultados.get('files', [])

def descargar_imagen(service, file_id):
    request = service.files().get_media(fileId=file_id)
    with open("/tmp/tmpimg.jpg", "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return Image.open("/tmp/tmpimg.jpg").convert("RGB")

def main():
    service = cargar_servicio_drive()
    carpetas = listar_carpetas(service, FOLDER_ID)
    logging.info(f"📦 Se encontraron {len(carpetas)} carpetas de modelos.")

    # Guardar incrementalmente
    os.makedirs("/var/data", exist_ok=True)
    ruta_embeds = "/var/data/embeddings.json"
    embeddings = {}

    for carpeta in carpetas:
        modelo = carpeta["name"]
        carpeta_id = carpeta["id"]
        logging.info(f"📁 Modelo: {modelo}")
        imagenes = listar_imagenes(service, carpeta_id)

        modelo_embeddings = []
        for img in imagenes:
            try:
                logging.info(f"   ⬇️ Procesando imagen: {img['name']}")
                imagen = descargar_imagen(service, img["id"])
                emb = generar_embedding(imagen)
                modelo_embeddings.append(emb)
                del imagen  # 🔥 Liberar imagen
            except Exception as e:
                logging.warning(f"⚠️ Error con {img['name']}: {e}")

        if modelo_embeddings:
            embeddings[modelo] = modelo_embeddings

        # 🔃 Guardar parcialmente para evitar pérdida por corte
        with open(ruta_embeds, "w") as f:
            json.dump(embeddings, f)

    logging.info("✅ embeddings.json guardado exitosamente.")

if __name__ == "__main__":
    main()
