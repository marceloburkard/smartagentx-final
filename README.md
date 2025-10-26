# Invoice OCR + LLM (Streamlit + Supabase)

App em Python/Streamlit para:
- Upload de notas fiscais (imagens ou PDF)
- OCR com Tesseract (suporte completo a Português, otimizado para documentos estruturados)
- Envio do texto para uma LLM via camada de abstração (OpenAI ou Anthropic, intercambiável)
- Persistência no Supabase via REST API
- Reprocessar etapas, editar manualmente o texto OCR, e exibir erros

## Estrutura
```
.
├─ app.py               # Aplicação principal Streamlit
├─ ocr.py              # Módulo de OCR com Tesseract
├─ llm_agent.py        # Cliente LLM (OpenAI/Anthropic)
├─ utils.py            # Funções utilitárias
├─ requirements.txt    # Dependências Python
├─ packages.txt        # Dependências do sistema (Tesseract)
├─ env.example         # Exemplo de arquivo de configuração
└─ README.md           # Documentação
```

## Pré-requisitos

### 1. **Python 3.8+**
Certifique-se de ter Python 3.8 ou superior instalado com pip.

### 2. **Tesseract OCR**

O Tesseract precisa ser instalado no sistema operacional. Escolha o método de instalação para seu sistema:

#### **Windows**
1. Baixe o instalador do Tesseract:
   - Link: https://github.com/UB-Mannheim/tesseract/wiki
   - Recomendado: `tesseract-ocr-w64-setup-5.3.3.20231005.exe` (ou versão mais recente)

2. Execute o instalador e **marque a opção para instalar dados de idioma adicional**
   - Durante a instalação, selecione **Portuguese** (por) nos idiomas adicionais

3. Após a instalação, anote o caminho de instalação (geralmente `C:\Program Files\Tesseract-OCR`)

4. Configure o caminho no arquivo `.env`:
   ```env
   TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
   ```

5. **Alternativa**: Adicione o Tesseract ao PATH do Windows:
   - Painel de Controle → Sistema → Configurações Avançadas → Variáveis de Ambiente
   - Adicione `C:\Program Files\Tesseract-OCR` à variável PATH
   - Se fizer isso, pode deixar `TESSERACT_CMD` vazio no `.env`

#### **macOS**
```bash
# Instalar Tesseract com Homebrew
brew install tesseract tesseract-lang

# Verificar instalação
tesseract --version
tesseract --list-langs  # Deve mostrar 'por' na lista
```

**Nota**: O `TESSERACT_CMD` não precisa ser configurado no macOS se usar Homebrew.

#### **Linux (Ubuntu/Debian)**
```bash
# Atualizar repositórios
sudo apt-get update

# Instalar Tesseract e pacote de idioma Português
sudo apt-get install tesseract-ocr tesseract-ocr-por

# Verificar instalação
tesseract --version
tesseract --list-langs  # Deve mostrar 'por' na lista
```

**Nota**: O `TESSERACT_CMD` não precisa ser configurado no Linux se usar apt-get.

#### **Linux (Fedora/RHEL/CentOS)**
```bash
# Instalar Tesseract
sudo dnf install tesseract tesseract-langpack-por

# Verificar instalação
tesseract --version
tesseract --list-langs
```

### 3. **Supabase**
- Crie a tabela `invoices` (SQL abaixo).
- Configure a REST API liberando acesso conforme seu modelo de segurança (ideal: service role em ambiente seguro).
- Preencha o `.env` com `SUPABASE_URL` e `SUPABASE_API_KEY` (pode ser service role **apenas em backend seguro**).

### 4. **LLM** (opcional para testes de fluxo)
   - Fornecedor suportado: `openai` ou `anthropic` (via API).
   - Preencha `LLM_PROVIDER` e `LLM_MODEL` e a respectiva `*_API_KEY`.

### Tabela `invoices`
```sql
create table if not exists public.invoices (
  id uuid primary key default gen_random_uuid(),
  filename text not null,
  status text not null check (status in ('uploaded','ocr_done','llm_sent','error')),
  ocr_text text,
  image_data text,  -- Base64 encoded image for display in UI
  image_mime_type text,  -- MIME type (image/jpeg, image/png, application/pdf, etc)
  image_filename text,  -- Original filename
  image_path text,  -- DEPRECATED: kept for backwards compatibility
  llm_response jsonb,
  error text,
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now()
);

create index if not exists invoices_created_at_idx on public.invoices (created_at desc);
```

**Note**: If you already have an existing `invoices` table, add the new columns with:
```sql
alter table public.invoices add column if not exists image_data text;
alter table public.invoices add column if not exists image_mime_type text;
alter table public.invoices add column if not exists image_filename text;
```

## Instalação

### 1. Clone o repositório
```bash
git clone <seu-repositorio>
cd smartagentx-final
```

### 2. Crie e ative o ambiente virtual

**macOS/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (Command Prompt):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Instale as dependências Python
```bash
pip install -r requirements.txt
```

### 4. Configure as variáveis de ambiente
```bash
# Copie o arquivo de exemplo
cp env.example .env

# Edite o arquivo .env com suas credenciais
# - Supabase URL e API Key
# - OpenAI ou Anthropic API Key
# - TESSERACT_CMD (apenas Windows ou instalações customizadas)
```

**Exemplo de `.env` configurado:**
```env
SUPABASE_URL=https://abcdefgh.supabase.co
SUPABASE_API_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_TABLE=invoices

LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-abc123...
LLM_MODEL=gpt-4o-mini

# Apenas para Windows:
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

### 5. Configure o banco de dados Supabase
Execute o SQL abaixo no SQL Editor do Supabase (veja seção "Tabela invoices" abaixo).

## Rodando

**Ative o ambiente virtual (se não estiver ativo):**
```bash
# macOS/Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

**Execute o aplicativo:**
```bash
streamlit run app.py
```

O aplicativo abrirá automaticamente no seu navegador em `http://localhost:8501`

## Troubleshooting

### ❌ Erro: "TesseractNotFoundError"

**Causa**: Tesseract não está instalado ou não foi encontrado.

**Solução**:
1. Verifique se o Tesseract está instalado:
   ```bash
   tesseract --version
   ```

2. Se não estiver instalado, siga as instruções de instalação acima para seu sistema operacional.

3. **Windows**: Se instalado mas ainda dá erro, configure o caminho no `.env`:
   ```env
   TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
   ```

### ❌ Erro: "português não encontrado" ou "por is not available"

**Causa**: Pacote de idioma Português não está instalado.

**Solução**:

**Windows**: Reinstale o Tesseract e marque a opção "Portuguese" durante a instalação.

**macOS**:
```bash
brew install tesseract-lang
```

**Linux**:
```bash
sudo apt-get install tesseract-ocr-por
```

**Verificar idiomas instalados**:
```bash
tesseract --list-langs
```
Deve aparecer "por" na lista.

### ❌ Erro de conexão com Supabase

**Causa**: Credenciais incorretas ou problema de rede.

**Solução**:
1. Verifique se `SUPABASE_URL` e `SUPABASE_API_KEY` estão corretos no `.env`
2. Teste a conexão no navegador: abra `SUPABASE_URL` + `/rest/v1/invoices` (deve retornar JSON ou erro de autenticação)
3. Verifique se a tabela `invoices` foi criada no Supabase

### ❌ Erro com LLM (OpenAI/Anthropic)

**Causa**: API key inválida ou expirada.

**Solução**:
1. Verifique se a API key está correta no `.env`
2. Teste a chave diretamente na plataforma (OpenAI ou Anthropic)
3. Verifique se há créditos disponíveis na conta

### ⚠️ OCR com baixa qualidade

**Dicas**:
- Use imagens com boa resolução (mínimo 300 DPI para documentos escaneados)
- Certifique-se de que o texto está legível na imagem original
- Evite imagens muito escuras ou com muito brilho
- Para PDFs, use resolução de 300 DPI ou superior

## Deploy no Streamlit Cloud

Este projeto está pronto para deploy no Streamlit Cloud sem nenhuma configuração adicional!

### Passos para Deploy:

1. **Faça push do código para GitHub**:
   ```bash
   git add .
   git commit -m "Setup complete"
   git push origin main
   ```

2. **Acesse o Streamlit Cloud**:
   - Vá para https://share.streamlit.io
   - Faça login com sua conta GitHub
   - Clique em "New app"

3. **Configure o app**:
   - Repository: selecione seu repositório
   - Branch: `main` (ou sua branch principal)
   - Main file path: `app.py`

4. **Configure as variáveis de ambiente (Secrets)**:
   - Clique em "Advanced settings" → "Secrets"
   - Cole o conteúdo do seu arquivo `.env`:
   ```toml
   SUPABASE_URL = "https://seu-projeto.supabase.co"
   SUPABASE_API_KEY = "sua-api-key-aqui"
   SUPABASE_TABLE = "invoices"
   
   LLM_PROVIDER = "openai"
   OPENAI_API_KEY = "sk-proj-sua-chave-aqui"
   LLM_MODEL = "gpt-4o-mini"
   ```
   
   **Nota**: Não precisa configurar `TESSERACT_CMD` no Streamlit Cloud!

5. **Deploy**:
   - Clique em "Deploy!"
   - O Streamlit Cloud irá:
     - Instalar as dependências Python do `requirements.txt`
     - Instalar Tesseract e idioma Português do `packages.txt`
     - Iniciar o aplicativo automaticamente

6. **Pronto!** 🎉
   - Seu app estará disponível em `https://seu-app.streamlit.app`

### Arquivos Importantes para Deploy:

- ✅ `requirements.txt` - Dependências Python
- ✅ `packages.txt` - Dependências do sistema (Tesseract)
- ✅ `app.py` - Aplicativo principal
- ✅ `.streamlit/config.toml` (opcional) - Configurações do Streamlit

### O que o Streamlit Cloud faz automaticamente:

1. **Instala Tesseract OCR** com pacote de idioma Português
2. **Instala poppler-utils** para processamento de PDF
3. **Instala todas as dependências Python**
4. **Configura as variáveis de ambiente** dos Secrets

## Observações
- Logs são gravados em `logs/app.log` e também exibidos no app.
- É possível reprocessar OCR e LLM por item.
- Você pode editar manualmente o texto OCR e salvar antes de enviar para a LLM.
- **Tesseract OCR**: 
  - Usa Tesseract com suporte completo a Português (`por` language pack)
  - Excelente para documentos estruturados como notas fiscais brasileiras
  - Preserva layout e estrutura tabular
  - Funciona perfeitamente no Streamlit Cloud via `packages.txt`
- **Armazenamento de Imagens**: Arquivos são convertidos para base64 e armazenados no Supabase, garantindo compatibilidade com Streamlit Cloud (sem necessidade de armazenamento local).
- **Visualização de Imagens**: As imagens originais podem ser visualizadas no modal "Visualizar/Editar OCR" (imagens apenas, PDFs não são exibidos).

## Licença

Este projeto está licenciado sob a **Licença MIT** - veja o arquivo [LICENSE](LICENSE) para detalhes.

### Resumo da Licença MIT

Esta licença permite que você:
- ✅ Use o software comercialmente
- ✅ Modifique o código
- ✅ Distribua o software
- ✅ Use em projetos privados
- ✅ Sublicencie

**Única condição**: Incluir o aviso de copyright e a licença em todas as cópias ou partes substanciais do software.
