import os, requests, json

class LLMClient:
    def __init__(self, provider: str = None, model: str = None):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "openai")).lower()
        self.model = model or os.getenv("LLM_MODEL", "")
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")

    def send(self, prompt: str) -> dict:
        if self.provider == "openai":
            return self._send_openai(prompt)
        elif self.provider == "anthropic":
            return self._send_anthropic(prompt)
        else:
            raise RuntimeError(f"LLM provider não suportado: {self.provider}")

    def _send_openai(self, prompt: str) -> dict:
        if not self.openai_key:
            raise RuntimeError("OPENAI_API_KEY não configurada")
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openai_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": self.model or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "Você é um assistente que extrai e valida dados de notas fiscais brasileiras. Usei OCR (Tesseract com suporte a Português) para extrair os dados de uma nota fiscal, você extrai os dados da nota fiscal de forma normalizada em formato json"},
                {"role": "user", "content": prompt}
            ]
        }
        r = requests.post(url, headers=headers, data=json.dumps(data), timeout=60)
        if not r.ok:
            raise RuntimeError(f"Erro da OpenAI: {r.status_code} {r.text}")
        out = r.json()
        content = out["choices"][0]["message"]["content"]
        return {"provider": "openai", "model": data["model"], "content": content, "raw": out}

    def _send_anthropic(self, prompt: str) -> dict:
        if not self.anthropic_key:
            raise RuntimeError("ANTHROPIC_API_KEY não configurada")
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.anthropic_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        data = {
            "model": self.model or "claude-3-5-sonnet-latest",
            "max_tokens": 1000,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "system": "Você é um assistente que extrai e valida dados de notas fiscais."
        }
        r = requests.post(url, headers=headers, data=json.dumps(data), timeout=60)
        if not r.ok:
            raise RuntimeError(f"Erro da Anthropic: {r.status_code} {r.text}")
        out = r.json()
        content = ""
        for blk in out.get("content", []):
            if blk.get("type") == "text":
                content += blk.get("text", "")
        return {"provider": "anthropic", "model": data["model"], "content": content, "raw": out}
