import os
import time
from typing import Optional, Dict, Any, List
import httpx
from dotenv import load_dotenv

# Carrega o .env da raiz do projeto (4 níveis acima: services -> app -> backend -> raiz)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ENV_PATH = os.path.join(ROOT_DIR, ".env")
load_dotenv(ENV_PATH)

PLUGGY_BASE_URL = "https://api.pluggy.ai"


class PluggyClient:
    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        load_dotenv(ENV_PATH, override=True)
        self.client_id = (
            client_id
            or os.getenv("ClientIDpluggy")
            or os.getenv("PLUGGY_CLIENT_ID")
            or ""
        ).strip()
        self.client_secret = (
            client_secret
            or os.getenv("ClientSecretpluggy")
            or os.getenv("PLUGGY_CLIENT_SECRET")
            or ""
        ).strip()
        self._cached_api_key: Optional[str] = None
        self._api_key_expires_at: float = 0

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def get_api_key(self) -> str:
        """Gera ou reutiliza um apiKey JWT válido na Pluggy (/auth) exclusivamente no backend."""
        now = time.time()
        if self._cached_api_key and now < self._api_key_expires_at:
            return self._cached_api_key

        if not self.is_configured():
            raise ValueError("Credenciais da Pluggy (ClientIDpluggy / ClientSecretpluggy) não configuradas no servidor.")

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{PLUGGY_BASE_URL}/auth",
                json={
                    "clientId": self.client_id,
                    "clientSecret": self.client_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            api_key = data.get("apiKey")
            if not api_key:
                raise RuntimeError("Resposta da Pluggy não retornou 'apiKey'.")
            self._cached_api_key = api_key
            self._api_key_expires_at = now + 6600  # ~1h50m
            return api_key

    async def create_connect_token(self, item_id: Optional[str] = None, client_user_id: str = "user-1") -> str:
        """Gera um Connect Token temporário para o fluxo oficial Pluggy Connect no frontend."""
        api_key = await self.get_api_key()
        payload: Dict[str, Any] = {
            "options": {
                "clientUserId": client_user_id,
            }
        }
        if item_id:
            payload["itemId"] = item_id

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{PLUGGY_BASE_URL}/connect_token",
                headers={"X-API-KEY": api_key},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("accessToken", "")

    async def create_sandbox_item(self, connector_id: int = 2, user: str = "user-ok", password: str = "password-ok") -> Dict[str, Any]:
        """Cria uma conexão real no Pluggy Bank Sandbox (connectorId 2) para validação automatizada."""
        api_key = await self.get_api_key()
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                f"{PLUGGY_BASE_URL}/items",
                headers={"X-API-KEY": api_key},
                json={
                    "connectorId": connector_id,
                    "parameters": {"user": user, "password": password},
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def get_item(self, item_id: str) -> Dict[str, Any]:
        """Busca detalhes e estado de saúde/consentimento de um Item conectado."""
        api_key = await self.get_api_key()
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{PLUGGY_BASE_URL}/items/{item_id}",
                headers={"X-API-KEY": api_key},
            )
            resp.raise_for_status()
            return resp.json()

    async def delete_item(self, item_id: str) -> bool:
        """Revoga e exclui um Item na Pluggy (direito de revogação LGPD / Open Finance)."""
        api_key = await self.get_api_key()
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.delete(
                f"{PLUGGY_BASE_URL}/items/{item_id}",
                headers={"X-API-KEY": api_key},
            )
            return resp.status_code in (200, 204, 404)

    async def get_accounts(self, item_id: str) -> List[Dict[str, Any]]:
        """Lista contas bancárias e cartões de crédito vinculados ao Item."""
        api_key = await self.get_api_key()
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{PLUGGY_BASE_URL}/accounts",
                params={"itemId": item_id},
                headers={"X-API-KEY": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])

    async def get_transactions_v2(
        self,
        account_id: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        max_pages: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Busca transações utilizando o endpoint oficial atual GET /v2/transactions com paginação por cursor,
        evitando o endpoint legado /transactions (HTTP 410 Gone).
        """
        api_key = await self.get_api_key()
        all_results: List[Dict[str, Any]] = []
        params: Dict[str, Any] = {"accountId": account_id}
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to

        next_cursor: Optional[str] = None
        page_count = 0

        async with httpx.AsyncClient(timeout=25.0) as client:
            while page_count < max_pages:
                req_params = dict(params)
                if next_cursor:
                    req_params["cursor"] = next_cursor
                resp = await client.get(
                    f"{PLUGGY_BASE_URL}/v2/transactions",
                    params=req_params,
                    headers={"X-API-KEY": api_key},
                )
                resp.raise_for_status()
                data = resp.json()
                batch = data.get("results", [])
                all_results.extend(batch)
                next_cursor = data.get("next")
                page_count += 1
                if not next_cursor or not batch:
                    break

        return all_results

    async def get_bills(self, account_id: str) -> List[Dict[str, Any]]:
        """Busca faturas fechadas/atuais de uma conta de cartão de crédito."""
        api_key = await self.get_api_key()
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{PLUGGY_BASE_URL}/bills",
                params={"accountId": account_id},
                headers={"X-API-KEY": api_key},
            )
            if resp.status_code == 200:
                return resp.json().get("results", [])
            return []

    async def list_connectors(self, name: Optional[str] = None, sandbox: bool = True) -> List[Dict[str, Any]]:
        """Lista conectores disponíveis na Pluggy."""
        api_key = await self.get_api_key()
        params: Dict[str, Any] = {"sandbox": str(sandbox).lower()}
        if name:
            params["name"] = name
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{PLUGGY_BASE_URL}/connectors",
                params=params,
                headers={"X-API-KEY": api_key},
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
