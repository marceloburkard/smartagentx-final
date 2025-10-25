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

def extract_json_from_llm_response(response_text):
    """Extract JSON content from LLM response text, focusing on invoice data structure"""
    if not response_text:
        return None
    
    # If response_text is already a dict, check if it contains invoice data structure
    if isinstance(response_text, dict):
        # If it's a complex response with 'raw' field, extract the content
        if 'raw' in response_text and isinstance(response_text['raw'], dict):
            raw_content = response_text['raw']
            if 'choices' in raw_content and len(raw_content['choices']) > 0:
                message_content = raw_content['choices'][0].get('message', {}).get('content', '')
                return extract_invoice_json_from_content(message_content)
        
        # If it's a complex response with 'content' field, extract from content
        if 'content' in response_text:
            return extract_invoice_json_from_content(response_text['content'])
        
        # If it already looks like invoice data (has emitente, CNPJ_CPF, etc.), return it
        if any(key in response_text for key in ['emitente', 'CNPJ_CPF', 'itens', 'valores']):
            return response_text
        
        return response_text
    
    # If response_text is not a string, convert it
    if not isinstance(response_text, str):
        response_text = str(response_text)
    
    return extract_invoice_json_from_content(response_text)

def extract_invoice_json_from_content(content):
    """Extract invoice JSON from text content"""
    import re
    
    # Clean the text - remove common LLM prefixes/suffixes
    cleaned_text = content.strip()
    
    # Remove common prefixes that LLMs might add
    prefixes_to_remove = [
        "Aqui está a extração e normalização dos dados da nota fiscal em formato JSON:",
        "Aqui está o JSON:",
        "Segue o JSON:",
        "JSON:",
        "```json",
        "```",
        "Resposta:",
        "Resultado:"
    ]
    
    for prefix in prefixes_to_remove:
        if cleaned_text.lower().startswith(prefix.lower()):
            cleaned_text = cleaned_text[len(prefix):].strip()
    
    # Remove trailing ``` if present
    if cleaned_text.endswith("```"):
        cleaned_text = cleaned_text[:-3].strip()
    
    # Remove any text after the JSON (like "Observações:")
    json_end_pattern = r'\n\nObservações?:'
    cleaned_text = re.split(json_end_pattern, cleaned_text)[0]
    
    # Try to parse the cleaned text as JSON
    try:
        parsed_json = json.loads(cleaned_text)
        # Verify it looks like invoice data
        if isinstance(parsed_json, dict) and any(key in parsed_json for key in ['emitente', 'CNPJ_CPF', 'itens', 'valores']):
            return parsed_json
    except json.JSONDecodeError:
        pass
    
    # Look for JSON objects in the text (more robust pattern)
    json_pattern = r'\{(?:[^{}]|{[^{}]*})*\}'
    matches = re.findall(json_pattern, cleaned_text, re.DOTALL)
    
    if matches:
        # Try to parse the largest match (most likely to be the complete JSON)
        largest_match = max(matches, key=len)
        try:
            parsed_json = json.loads(largest_match)
            # Verify it looks like invoice data
            if isinstance(parsed_json, dict) and any(key in parsed_json for key in ['emitente', 'CNPJ_CPF', 'itens', 'valores']):
                return parsed_json
        except json.JSONDecodeError:
            # Try all matches
            for match in matches:
                try:
                    parsed_json = json.loads(match)
                    # Verify it looks like invoice data
                    if isinstance(parsed_json, dict) and any(key in parsed_json for key in ['emitente', 'CNPJ_CPF', 'itens', 'valores']):
                        return parsed_json
                except json.JSONDecodeError:
                    continue
    
    # If no valid invoice JSON found, return a structured error response
    return {"error": "Resposta não contém JSON válido de nota fiscal", "raw_response": content[:200] + "..." if len(content) > 200 else content}

st.set_page_config(page_title="Invoice OCR + LLM", layout="wide")

st.title("Invoice OCR + LLM")


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
            "Segue o texto OCR de uma nota fiscal emitida no Brasil de acordo com as regras vigentes. Extraia os principais campos (emitente, CNPJ/CPF, "
            "data, itens, valores, impostos) e retorne em JSON bem estruturado de acordo com o schema abaixo, com campos ausentes como null. "
            "Para campos de endereço, caso a informação não esteja presente no texto OCR ou seja incompleta ou seja inválida, retorne null. "
            "O seu retorno deve ser apenas o JSON, sem nenhum outro texto adicional. É extremamente importante que você retorne APENAS o JSON, sem nenhum outro texto adicional."
            "Use exatamente o formato definido no schema abaixo:\n\n"
            "JSON Schema:\n"
            "{\n"
            '  "$schema": "https://json-schema.org/draft/2020-12/schema",\n'
            '  "title": "NotaFiscalSchema",\n'
            '  "type": "object",\n'
            '  "properties": {\n'
            '    "estabelecimento": {\n'
            '      "type": "object",\n'
            '      "properties": {\n'
            '        "nome": { "type": "string" },\n'
            '        "cnpj": { "type": "string" },\n'
            '        "telefone": { "type": "string" },\n'
            '        "inscricao_estadual": { "type": "string" },\n'
            '        "endereco": {\n'
            '          "type": "object",\n'
            '          "properties": {\n'
            '            "logradouro": { "type": "string" },\n'
            '            "bairro": { "type": "string" },\n'
            '            "cidade": { "type": "string" },\n'
            '            "estado": { "type": "string" }\n'
            '          },\n'
            '          "required": ["logradouro", "bairro", "cidade", "estado"]\n'
            '        }\n'
            '      },\n'
            '      "required": ["nome", "cnpj", "telefone", "inscricao_estadual", "endereco"]\n'
            '    },\n'
            '    "nota_fiscal": {\n'
            '      "type": "object",\n'
            '      "properties": {\n'
            '        "tipo": { "type": "string" },\n'
            '        "numero": { "type": "string" },\n'
            '        "serie": { "type": "string" },\n'
            '        "data_emissao": { "type": "string", "format": "date-time" },\n'
            '        "chave_acesso": { "type": "string" },\n'
            '        "protocolo_autorizacao": { "type": "string" },\n'
            '        "consumidor": { "type": "string" }\n'
            '      },\n'
            '      "required": ["tipo", "numero", "serie", "data_emissao", "chave_acesso", "protocolo_autorizacao", "consumidor"]\n'
            '    },\n'
            '    "itens": {\n'
            '      "type": "array",\n'
            '      "items": {\n'
            '        "type": "object",\n'
            '        "properties": {\n'
            '          "codigo": { "type": ["string", "null"] },\n'
            '          "descricao": { "type": "string" },\n'
            '          "quantidade": { "type": "number" },\n'
            '          "valor_unitario": { "type": "number" },\n'
            '          "valor_total": { "type": "number" }\n'
            '        },\n'
            '        "required": ["descricao", "quantidade", "valor_unitario", "valor_total"]\n'
            '      }\n'
            '    },\n'
            '    "totais": {\n'
            '      "type": "object",\n'
            '      "properties": {\n'
            '        "valor_total": { "type": "number" },\n'
            '        "forma_pagamento": { "type": "string" },\n'
            '        "valor_pago": { "type": "number" }\n'
            '      },\n'
            '      "required": ["valor_total", "forma_pagamento", "valor_pago"]\n'
            '    }\n'
            '  },\n'
            '  "required": ["estabelecimento", "nota_fiscal", "itens", "totais"]\n'
            "}\n\n"
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
    # Agrupar invoices por filename e manter apenas o mais recente de cada arquivo
    unique_invoices = {}
    for inv in invoices:
        filename = inv.get('filename')
        if filename not in unique_invoices:
            unique_invoices[filename] = inv
        else:
            # Comparar timestamps para manter o mais recente
            current_created = inv.get('created_at', '')
            existing_created = unique_invoices[filename].get('created_at', '')
            if current_created > existing_created:
                unique_invoices[filename] = inv
    
    # Ordenar os invoices únicos por data de criação (mais recente primeiro)
    sorted_unique_invoices = sorted(unique_invoices.values(), 
                                   key=lambda x: x.get('created_at', ''), 
                                   reverse=True)
    
    for inv in sorted_unique_invoices:
        with st.expander(f"{inv.get('filename')} — status: {inv.get('status')} — id: {inv.get('id')}"):
            col1, col2, col3 = st.columns([2,2,1])

            with col1:
                st.caption("Texto OCR (editável)")
                key_text = f"ocr_text_{inv['id']}"
                text_val = inv.get("ocr_text") or ""
                new_text = st.text_area("Texto OCR",
                                        value=st.session_state.get(key_text, text_val),
                                        height=200,
                                        key=key_text,
                                        label_visibility="collapsed")
                if st.button("Salvar texto OCR", key=f"save_{inv['id']}"):
                    try:
                        update_invoice(inv["id"], ocr_text=new_text)
                        st.success("Texto salvo.")
                    except Exception as e:
                        st.error(f"Erro ao salvar texto: {e}")

            with col2:
                st.caption("Resposta LLM (visualização)")
                llm_resp = inv.get("llm_response")
                if llm_resp:
                    # Extract JSON content from LLM response
                    json_content = extract_json_from_llm_response(llm_resp)
                    if json_content:
                        st.json(json_content)
                    else:
                        st.info("Resposta LLM não contém JSON válido")
                else:
                    st.json({"info": "Sem resposta ainda"})

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

