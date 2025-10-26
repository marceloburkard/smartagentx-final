import io, os
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
from pdf2image import convert_from_bytes

# Configure Tesseract command path (for local development)
# Streamlit Cloud will use the system tesseract from packages.txt
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

SUPPORTED_IMG_EXT = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}
SUPPORTED_DOC_EXT = {".pdf"} | SUPPORTED_IMG_EXT

def _preprocess_image_for_tesseract(img: Image.Image) -> Image.Image:
    """
    Light preprocessing for Tesseract OCR
    Tesseract works best with minimal preprocessing on good quality images
    """
    # Convert to RGB if not already
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    # Very light sharpening to help with slightly blurry receipts
    enhancer = ImageEnhance.Sharpness(img)
    img = enhancer.enhance(1.2)
    
    # Slight contrast boost for faded thermal paper
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.1)
    
    return img

def _ocr_pil_image(img: Image.Image) -> str:
    """
    Extract text from PIL Image using Tesseract OCR optimized for Portuguese receipts
    """
    # Light preprocessing
    img = _preprocess_image_for_tesseract(img)
    
    # Tesseract configuration for receipts:
    # --psm 6: Assume a single uniform block of text (good for receipts)
    # --psm 4: Alternative - assume single column of text
    # -l por: Portuguese language (with fallback to eng for numbers/symbols)
    # --oem 3: Use both legacy and LSTM OCR engines
    
    # Try Portuguese first, then Portuguese+English combined
    custom_config = r'--oem 3 --psm 6 -l por'
    
    try:
        text = pytesseract.image_to_string(img, config=custom_config)
        
        # If result is very short or empty, try with combined languages
        if len(text.strip()) < 50:
            custom_config = r'--oem 3 --psm 6 -l por+eng'
            text = pytesseract.image_to_string(img, config=custom_config)
        
        return text
    except Exception as e:
        # Fallback to default configuration
        return pytesseract.image_to_string(img)

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
