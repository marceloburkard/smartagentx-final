import os, io, json, traceback, datetime
import streamlit as st
import requests
from dotenv import load_dotenv

from utils import setup_logger
from ocr import run_ocr, SUPPORTED_DOC_EXT
from llm_agent import LLMClient

load_dotenv()
logger = setup_logger()

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY", "")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "invoices")

REST_URL = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"

HEADERS = {
    "apikey": SUPABASE_API_KEY,
    "Authorization": f"Bearer {SUPABASE_API_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

def _ensure_config():
    """Ensure required configuration is present"""
    if not SUPABASE_URL or not SUPABASE_API_KEY:
        raise RuntimeError("Configure SUPABASE_URL e SUPABASE_API_KEY no .env")

def create_invoice(filename: str):
    """Create a new invoice record using Supabase REST API"""
    _ensure_config()
    payload = {
        "filename": filename,
        "status": "uploaded"
    }
    try:
        response = requests.post(REST_URL, headers=HEADERS, data=json.dumps(payload), timeout=30)
        if not response.ok:
            raise RuntimeError(f"Erro ao criar invoice: {response.status_code} {response.text}")
        result = response.json()
        if result and len(result) > 0:
            return result[0]
        else:
            raise RuntimeError("No data returned from insert operation")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Erro de conexão ao criar invoice: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Erro ao criar invoice: {str(e)}")

def update_invoice(invoice_id: str, **fields):
    """Update an existing invoice record using Supabase REST API"""
    _ensure_config()
    fields["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    url = f"{REST_URL}?id=eq.{invoice_id}"
    try:
        response = requests.patch(url, headers=HEADERS, data=json.dumps(fields), timeout=30)
        if not response.ok:
            raise RuntimeError(f"Erro ao atualizar invoice: {response.status_code} {response.text}")
        result = response.json()
        if result and len(result) > 0:
            return result[0]
        else:
            return None
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Erro de conexão ao atualizar invoice: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Erro ao atualizar invoice: {str(e)}")

def list_invoices(limit: int = 100):
    """List invoices ordered by creation date using Supabase REST API"""
    _ensure_config()
    url = f"{REST_URL}?select=*&order=created_at.desc&limit={limit}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        if not response.ok:
            raise RuntimeError(f"Erro ao listar invoices: {response.status_code} {response.text}")
        result = response.json()
        return result if result else []
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Erro de conexão ao listar invoices: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Erro ao listar invoices: {str(e)}")

st.set_page_config(page_title="Invoice OCR + LLM", layout="wide")

st.title("Invoice OCR + LLM")

with st.sidebar:
    st.subheader("Config")
    st.write("Provedor LLM e modelo podem ser ajustados no .env")
    if st.button("Atualizar lista"):
        st.session_state["_refresh"] = True

st.subheader("Upload de notas fiscais")
uploaded_files = st.file_uploader("Selecione imagens ou PDFs", type=[e.strip(".") for e in SUPPORTED_DOC_EXT], accept_multiple_files=True)

if uploaded_files:
    for f in uploaded_files:
        try:
            inv = create_invoice(f.name)
            st.success(f"Arquivo registrado: {f.name}")
            st.session_state.setdefault("files_cache", {})[inv["id"]] = f.read()
        except Exception as e:
            err = f"Falha ao registrar {f.name}: {e}"
            logger.exception(err)
            st.error(err)

st.divider()
st.subheader("Processamento")

def do_ocr(invoice_id: str, file_bytes: bytes, filename: str):
    try:
        text = run_ocr(file_bytes, filename)
        update_invoice(invoice_id, status="ocr_done", ocr_text=text, error=None)
        st.success(f"OCR ok: {filename}")
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(tb)
        update_invoice(invoice_id, status="error", error=str(e))
        st.error(f"OCR falhou: {e}")

def do_llm(invoice_id: str, text: str):
    try:
        client = LLMClient()
        prompt = (
            "Segue o texto OCR de uma nota fiscal. Extraia os principais campos (emitente, CNPJ/CPF,"
            " data, itens, valores, impostos) e retorne em JSON bem estruturado, com campos ausentes como null."
            "\n\n"
            f"Texto OCR:\n{text}"
        )
        resp = client.send(prompt)
        update_invoice(invoice_id, status="llm_sent", llm_response=resp, error=None)
        st.success("Envio para LLM ok")
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(tb)
        update_invoice(invoice_id, status="error", error=str(e))
        st.error(f"LLM falhou: {e}")

try:
    invoices = list_invoices(limit=200)
except Exception as e:
    st.error(f"Erro ao listar invoices: {e}")
    invoices = []

if not invoices:
    st.info("Nenhum registro ainda.")
else:
    for inv in invoices:
        with st.expander(f"{inv.get('filename')} — status: {inv.get('status')} — id: {inv.get('id')}"):
            col1, col2, col3 = st.columns([2,2,1])

            with col1:
                st.caption("Texto OCR (editável)")
                key_text = f"ocr_text_{inv['id']}"
                text_val = inv.get("ocr_text") or ""
                new_text = st.text_area("",
                                        value=st.session_state.get(key_text, text_val),
                                        height=200,
                                        key=key_text)
                if st.button("Salvar texto OCR", key=f"save_{inv['id']}"):
                    try:
                        update_invoice(inv["id"], ocr_text=new_text)
                        st.success("Texto salvo.")
                    except Exception as e:
                        st.error(f"Erro ao salvar texto: {e}")

            with col2:
                st.caption("Resposta LLM (visualização)")
                llm_resp = inv.get("llm_response")
                st.json(llm_resp or {"info": "Sem resposta ainda"})

            with col3:
                st.caption("Ações")
                file_cache = st.session_state.get("files_cache", {}).get(inv["id"])
                if st.button("Rodar OCR", key=f"ocr_{inv['id']}"):
                    if file_cache is None:
                        st.warning("Arquivo não está em cache nesta sessão. Refaça o upload para OCR imediato.")
                    else:
                        do_ocr(inv["id"], file_cache, inv["filename"])

                if st.button("Enviar LLM", key=f"llm_{inv['id']}"):
                    if not new_text:
                        st.warning("Texto OCR vazio.")
                    else:
                        do_llm(inv["id"], new_text)

                if st.button("Reprocessar OCR", key=f"reocr_{inv['id']}"):
                    if file_cache is None:
                        st.warning("Arquivo não está em cache nesta sessão. Refaça o upload para reprocessar OCR.")
                    else:
                        do_ocr(inv["id"], file_cache, inv["filename"])

                if st.button("Reprocessar LLM", key=f"rellm_{inv['id']}"):
                    if not new_text:
                        st.warning("Texto OCR vazio.")
                    else:
                        do_llm(inv["id"], new_text)

            err = inv.get("error")
            if err:
                st.error(f"Erro registrado: {err}")

st.divider()
st.subheader("Logs")
try:
    with open("logs/app.log", "r", encoding="utf-8") as fh:
        st.code(fh.read()[-4000:], language="text")
except FileNotFoundError:
    st.write("Sem logs ainda.")
