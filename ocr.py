import io, os
from PIL import Image
import pytesseract
from pdf2image import convert_from_bytes

TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

SUPPORTED_IMG_EXT = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}
SUPPORTED_DOC_EXT = {".pdf"} | SUPPORTED_IMG_EXT

def _ocr_pil_image(img: Image.Image) -> str:
    config = "--psm 6"
    return pytesseract.image_to_string(img, config=config)

def _open_image_from_bytes(b: bytes) -> Image.Image:
    return Image.open(io.BytesIO(b)).convert("RGB")

def run_ocr(file_bytes: bytes, filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        pages = convert_from_bytes(file_bytes, dpi=300)
        texts = []
        for page in pages:
            texts.append(_ocr_pil_image(page))
        return "\n\n".join(texts).strip()
    else:
        img = _open_image_from_bytes(file_bytes)
        return _ocr_pil_image(img).strip()
