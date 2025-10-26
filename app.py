import os, io, json, traceback, datetime, uuid, time, base64
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
    fields["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
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

# CSS customizado para modificar largura dos modais
st.markdown("""
<style>
/* Modificar largura dos modais para 90% da tela */
div[data-testid="stDialog"] {
    width: 90% !important;
    max-width: 90% !important;
}

/* Ajustar o conteúdo interno do modal */
div[data-testid="stDialog"] > div {
    width: 100% !important;
    max-width: 100% !important;
}

/* Garantir que o modal seja responsivo */
@media (max-width: 768px) {
    div[data-testid="stDialog"] {
        width: 95% !important;
        max-width: 95% !important;
    }
}
</style>
""", unsafe_allow_html=True)

st.title("Invoice OCR + LLM")


st.subheader("Upload de notas fiscais")
st.info("ℹ️ **Processamento Automático**: Após o upload, o OCR e análise por LLM serão executados automaticamente. Acompanhe o progresso abaixo.")
uploaded_files = st.file_uploader("Selecione imagens ou PDFs", type=[e.strip(".") for e in SUPPORTED_DOC_EXT], accept_multiple_files=True)

# Initialize session state for tracking uploaded files
if "uploaded_filenames" not in st.session_state:
    st.session_state.uploaded_filenames = {}
if "files_cache" not in st.session_state:
    st.session_state.files_cache = {}
if "processed_files" not in st.session_state:
    st.session_state.processed_files = set()

if uploaded_files:
    for f in uploaded_files:
        try:
            # Check if this file was already uploaded (avoid duplicates)
            if f.name not in st.session_state.uploaded_filenames:
                # Read file bytes first
                file_bytes = f.read()
                
                # Convert to base64 for storage in database
                file_base64 = base64.b64encode(file_bytes).decode('utf-8')
                
                # Create invoice record
                inv = create_invoice(f.name)
                invoice_id = inv["id"]
                
                # Get file extension and MIME type
                file_extension = os.path.splitext(f.name)[1].lower()
                mime_types = {
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.png': 'image/png',
                    '.gif': 'image/gif',
                    '.bmp': 'image/bmp',
                    '.webp': 'image/webp',
                    '.tiff': 'image/tiff',
                    '.pdf': 'application/pdf'
                }
                mime_type = mime_types.get(file_extension, 'application/octet-stream')
                
                # Update invoice with base64 image data
                update_invoice(invoice_id, 
                              image_data=file_base64,
                              image_mime_type=mime_type,
                              image_filename=f.name)
                
                # Store mapping and cache
                st.session_state.uploaded_filenames[f.name] = invoice_id
                st.session_state.files_cache[invoice_id] = file_bytes
                
                st.success(f"✅ Arquivo registrado: {f.name}")
                logger.info(f"Arquivo {f.name} registrado com ID {invoice_id}, armazenado em base64 ({len(file_base64)} chars)")
                
                # AUTOMATIC PROCESSING: OCR + LLM
                if invoice_id not in st.session_state.processed_files:
                    st.info(f"🔄 Processamento automático iniciado para: {f.name}")
                    
                    # Step 1: Run OCR
                    with st.status(f"📄 Processando {f.name}...", expanded=True) as status:
                        st.write("⏳ Executando OCR...")
                        try:
                            text = run_ocr(file_bytes, f.name)
                            update_invoice(invoice_id, status="ocr_done", ocr_text=text, error=None)
                            st.write("✅ OCR concluído!")
                            logger.info(f"OCR automático concluído para {f.name}")
                            
                            # Step 2: Send to LLM
                            st.write("⏳ Enviando para LLM...")
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
                            st.write("✅ Processamento LLM concluído!")
                            logger.info(f"LLM automático concluído para {f.name}")
                            
                            # Mark as processed
                            st.session_state.processed_files.add(invoice_id)
                            
                            status.update(label=f"✅ {f.name} - Processamento completo!", state="complete")
                            
                        except Exception as e:
                            tb = traceback.format_exc()
                            logger.error(tb)
                            update_invoice(invoice_id, status="error", error=str(e))
                            status.update(label=f"❌ {f.name} - Erro no processamento", state="error")
                            st.error(f"Erro ao processar: {e}")
                
            else:
                # File already uploaded, just re-cache it
                invoice_id = st.session_state.uploaded_filenames[f.name]
                if invoice_id not in st.session_state.files_cache:
                    # Re-read and cache if not in cache
                    file_bytes = f.read()
                    st.session_state.files_cache[invoice_id] = file_bytes
                    logger.info(f"Arquivo {f.name} re-cacheado com ID {invoice_id}")
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

# Funções para modalboxes usando st.dialog
@st.dialog("📝 Editar Texto OCR")
def show_ocr_dialog(invoice_id: str, filename: str, current_text: str, image_data: str = None, image_mime_type: str = None):
    """Modalbox para editar texto OCR"""
    st.markdown(f"**Arquivo:** {filename}")
    st.markdown("---")
    
    # Criar duas colunas: uma para a imagem e outra para o texto OCR
    col_image, col_text = st.columns([1, 1])
    
    with col_image:
        st.markdown("**Imagem Original:**")
        if image_data:
            # Decode base64 and display
            try:
                # Check if it's a PDF or image
                if image_mime_type and 'pdf' in image_mime_type.lower():
                    st.info("📄 Arquivo PDF - visualização não disponível no modal")
                    st.caption(f"Tipo: {image_mime_type}")
                else:
                    # Decode base64 to bytes
                    image_bytes = base64.b64decode(image_data)
                    # Display image from bytes
                    st.image(image_bytes, caption=filename, use_column_width=True)
                    st.caption(f"Tipo: {image_mime_type or 'Desconhecido'}")
            except Exception as e:
                st.error(f"❌ Erro ao decodificar imagem: {e}")
                logger.error(f"Erro ao decodificar imagem base64: {e}")
        else:
            st.info("🖼️ Imagem não encontrada (arquivo foi enviado antes da atualização do sistema)")
    
    with col_text:
        st.markdown("**Texto OCR (editável):**")
        key_text = f"ocr_text_{invoice_id}"
        new_text = st.text_area("",
                                value=current_text,
                                height=400,
                                key=key_text,
                                label_visibility="collapsed",
                                placeholder="Digite ou edite o texto OCR aqui...")
    
    st.markdown("---")
    
    col_save, col_close, col_space = st.columns([1, 1, 2])
    
    with col_save:
        if st.button("💾 Salvar Alterações", type="primary"):
            try:
                update_invoice(invoice_id, ocr_text=new_text)
                st.success("✅ Texto salvo com sucesso!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Erro ao salvar texto: {e}")
    
    with col_close:
        if st.button("❌ Cancelar", key=f"close_ocr_{invoice_id}"):
            st.stop()

@st.dialog("🤖 Resposta do LLM")
def show_llm_dialog(filename: str, llm_response):
    """Modalbox para visualizar resposta LLM"""
    st.markdown(f"**Arquivo:** {filename}")
    st.markdown("---")
    
    if llm_response:
        # Extract JSON content from LLM response
        json_content = extract_json_from_llm_response(llm_response)
        if json_content:
            st.markdown("**Dados extraídos:**")
            st.json(json_content)
        else:
            st.info("⚠️ Resposta LLM não contém JSON válido")
            st.markdown("**Resposta bruta:**")
            st.text_area("", value=str(llm_response), height=200, disabled=True)
    else:
        st.info("ℹ️ Sem resposta LLM ainda")
    
    st.markdown("---")
    
    if st.button("❌ Fechar", key=f"close_llm_{filename}"):
        st.stop()

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
    
    # Criar tabela com cabeçalhos
    st.subheader("Arquivos Processados")
    st.caption("📎 = arquivo em cache (pronto para OCR) | 📄 = arquivo não está em cache")
    
    # Cabeçalhos da tabela
    col1, col2, col3, col4 = st.columns([4, 2, 2, 2])
    
    with col1:
        st.markdown("**Nome do Arquivo**")
    with col2:
        st.markdown("**Status**")
    with col3:
        st.markdown("**Data de Criação**")
    with col4:
        st.markdown("**Ações**")
    
    st.divider()
    
    # Exibir cada invoice em uma linha da tabela
    for inv in sorted_unique_invoices:
        col1, col2, col3, col4 = st.columns([4, 2, 2, 2])
        
        with col1:
            filename = inv.get('filename', 'N/A')
            # Check if file is in cache
            is_cached = inv["id"] in st.session_state.get("files_cache", {})
            cache_indicator = "📎" if is_cached else "📄"
            st.write(f"{cache_indicator} {filename}")
        
        with col2:
            status = inv.get('status', 'N/A')
            if status == 'error':
                st.error(status)
            elif status == 'llm_sent':
                st.success(status)
            elif status == 'ocr_done':
                st.info(status)
            else:
                st.write(status)
        
        with col3:
            created_at = inv.get('created_at', '')
            if created_at:
                # Formatar data para exibição mais amigável
                try:
                    dt = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    st.write(dt.strftime('%d/%m/%Y %H:%M'))
                except:
                    st.write(created_at[:16])  # Mostrar apenas parte da data
            else:
                st.write('N/A')
        
        with col4:
            # Usar expander para as ações
            with st.expander("⚙️ Ações", expanded=False):
                file_cache = st.session_state.get("files_cache", {}).get(inv["id"])
                
                # Botão para visualizar/editar OCR
                if st.button("📝 Visualizar/Editar OCR", key=f"view_ocr_{inv['id']}", use_container_width=True):
                    text_val = inv.get("ocr_text") or ""
                    image_data = inv.get("image_data")
                    image_mime_type = inv.get("image_mime_type")
                    show_ocr_dialog(inv["id"], inv.get('filename', 'N/A'), text_val, image_data, image_mime_type)
                
                # Botão para visualizar resposta LLM (se disponível)
                if inv.get("llm_response"):
                    if st.button("🤖 Ver Resposta LLM", key=f"view_llm_{inv['id']}", use_container_width=True):
                        llm_resp = inv.get("llm_response")
                        show_llm_dialog(inv.get('filename', 'N/A'), llm_resp)
                
                # Botão para executar OCR
                if st.button("🔄 Executar OCR", key=f"run_ocr_{inv['id']}", use_container_width=True):
                    # Debug: log cache status
                    logger.info(f"OCR solicitado para invoice {inv['id']}, arquivo: {inv.get('filename')}")
                    logger.info(f"Cache disponível: {file_cache is not None}, Tamanho: {len(file_cache) if file_cache else 0} bytes")
                    
                    if file_cache is None:
                        st.error("⚠️ Arquivo não está em cache. Por favor, faça upload do arquivo novamente usando o campo acima.")
                        st.info("💡 **Dica**: Mantenha o arquivo selecionado no campo de upload enquanto processa.")
                    else:
                        with st.spinner("Processando OCR..."):
                            try:
                                text = run_ocr(file_cache, inv["filename"])
                                update_invoice(inv["id"], status="ocr_done", ocr_text=text, error=None)
                                st.success(f"✅ OCR concluído: {inv['filename']}")
                                st.balloons()
                                # Wait a moment for user to see the message
                                time.sleep(1)
                                st.rerun()
                            except Exception as e:
                                tb = traceback.format_exc()
                                logger.error(tb)
                                update_invoice(inv["id"], status="error", error=str(e))
                                st.error(f"❌ OCR falhou: {e}")
                
                # Botão para enviar para LLM
                if st.button("🚀 Enviar para LLM", key=f"send_llm_{inv['id']}", use_container_width=True):
                    text_val = inv.get("ocr_text") or ""
                    if not text_val:
                        st.warning("⚠️ Texto OCR vazio. Execute o OCR primeiro.")
                    else:
                        with st.spinner("Enviando para LLM..."):
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
                                    f"Texto OCR:\n{text_val}"
                                )
                                resp = client.send(prompt)
                                update_invoice(inv["id"], status="llm_sent", llm_response=resp, error=None)
                                st.success("✅ Envio para LLM concluído!")
                                # Wait a moment for user to see the message
                                time.sleep(1)
                                st.rerun()
                            except Exception as e:
                                tb = traceback.format_exc()
                                logger.error(tb)
                                update_invoice(inv["id"], status="error", error=str(e))
                                st.error(f"❌ LLM falhou: {e}")
        
        
        # Exibir erro se houver
        err = inv.get("error")
        if err:
            st.error(f"Erro registrado: {err}")
        
        st.divider()

