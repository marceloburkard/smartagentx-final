# Invoice OCR + LLM (Streamlit + Supabase)

App em Python/Streamlit para:
- Upload de notas fiscais (imagens ou PDF)
- OCR com Tesseract
- Envio do texto para uma LLM via camada de abstração (OpenAI ou Anthropic, intercambiável)
- Persistência no Supabase via REST API
- Reprocessar etapas, editar manualmente o texto OCR, e exibir erros

## Estrutura
```
.
├─ app.py
├─ ocr.py
├─ llm_agent.py
├─ utils.py
├─ requirements.txt
├─ .env.example
└─ README.md
```

## Pré-requisitos
1. **Tesseract** instalado no SO.
   - Linux: `sudo apt-get install tesseract-ocr`
   - macOS (Homebrew): `brew install tesseract`
   - Windows: instalar binários do Tesseract e setar `TESSERACT_CMD` no `.env` se necessário.

2. **Supabase**:
   - Crie a tabela `invoices` (SQL abaixo).
   - Configure a REST API liberando acesso conforme seu modelo de segurança (ideal: service role em ambiente seguro).
   - Preencha o `.env` com `SUPABASE_URL` e `SUPABASE_API_KEY` (pode ser service role **apenas em backend seguro**).

3. **LLM** (opcional para testes de fluxo):
   - Fornecedor suportado: `openai` ou `anthropic` (via API).
   - Preencha `LLM_PROVIDER` e `LLM_MODEL` e a respectiva `*_API_KEY`.

### Tabela `invoices`
```sql
create table if not exists public.invoices (
  id uuid primary key default gen_random_uuid(),
  filename text not null,
  status text not null check (status in ('uploaded','ocr_done','llm_sent','error')),
  ocr_text text,
  llm_response jsonb,
  error text,
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now()
);

create index if not exists invoices_created_at_idx on public.invoices (created_at desc);
```

## Instalação
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edite .env com suas chaves/urls
```

## Rodando
```bash
streamlit run app.py
```

## Observações
- Logs são gravados em `logs/app.log` e também exibidos no app.
- É possível reprocessar OCR e LLM por item.
- Você pode editar manualmente o texto OCR e salvar antes de enviar para a LLM.

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
