from __future__ import annotations

import base64
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import TellerConfig


def _redact_api_path(path: str) -> str:
    path = re.sub(r"/accounts/[^/?]+", "/accounts/<account_id>", path)
    path = re.sub(r"/transactions/[^/?]+", "/transactions/<transaction_id>", path)
    return path


class TellerAPIError(RuntimeError):
    def __init__(
        self,
        *,
        status: int,
        path: str,
        code: str | None,
        teller_message: str | None,
    ):
        self.status = status
        self.path = _redact_api_path(path)
        self.code = code
        self.teller_message = teller_message
        message_parts = [f"Teller API HTTP {status}", self.path]
        if code:
            message_parts.append(code)
        if teller_message:
            message_parts.append(teller_message)
        super().__init__(": ".join(message_parts))


@dataclass(frozen=True)
class TellerClient:
    config: TellerConfig
    api_base_url: str = "https://api.teller.io"

    def _ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        if self.config.environment in {"development", "production"}:
            if not self.config.cert_path or not self.config.cert_key_path:
                raise RuntimeError(
                    "Teller development/production API requests require "
                    "TELLER_CERT_PATH and TELLER_CERT_KEY_PATH"
                )
            context.load_cert_chain(
                certfile=self.config.cert_path,
                keyfile=self.config.cert_key_path,
            )
        elif self.config.cert_path and self.config.cert_key_path:
            context.load_cert_chain(
                certfile=self.config.cert_path,
                keyfile=self.config.cert_key_path,
            )
        return context

    def _request(
        self,
        path: str,
        *,
        access_token: str | None = None,
        query: dict[str, str | int | None] | None = None,
    ) -> Any:
        url = self.api_base_url + path
        if query:
            clean_query = {key: value for key, value in query.items() if value is not None}
            if clean_query:
                url += "?" + urllib.parse.urlencode(clean_query)

        headers = {
            "Accept": "application/json",
            "User-Agent": "budget-teller-oracle/0.1",
        }
        if self.config.api_version:
            headers["Teller-Version"] = self.config.api_version
        if access_token:
            auth = base64.b64encode(f"{access_token}:".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {auth}"

        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, context=self._ssl_context(), timeout=45) as response:
                body = response.read()
                if not body:
                    return None
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode("utf-8", errors="replace")
            code = None
            teller_message = None
            try:
                parsed = json.loads(raw_body)
                error = parsed.get("error") or {}
                code = error.get("code")
                teller_message = error.get("message")
            except json.JSONDecodeError:
                teller_message = raw_body[:500] if raw_body else exc.reason
            raise TellerAPIError(
                status=exc.code,
                path=path,
                code=code,
                teller_message=teller_message,
            ) from exc

    def list_institutions(self) -> list[dict[str, Any]]:
        request = urllib.request.Request(
            self.api_base_url + "/institutions",
            headers={"Accept": "application/json", "User-Agent": "budget-teller-oracle/0.1"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))

    def list_accounts(self, access_token: str) -> list[dict[str, Any]]:
        return self._request("/accounts", access_token=access_token)

    def list_transactions(
        self,
        access_token: str,
        account_id: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        count: int = 500,
    ) -> list[dict[str, Any]]:
        transactions: list[dict[str, Any]] = []
        from_id: str | None = None

        for _ in range(100):
            for attempt in range(4):
                try:
                    page = self._request(
                        f"/accounts/{urllib.parse.quote(account_id)}/transactions",
                        access_token=access_token,
                        query={
                            "start_date": start_date,
                            "end_date": end_date,
                            "count": count,
                            "from_id": from_id,
                        },
                    )
                    break
                except TellerAPIError as exc:
                    if exc.status not in {502, 504} or attempt == 3:
                        raise
                    time.sleep(5 * (attempt + 1))
            if not page:
                break
            transactions.extend(page)
            if len(page) < count:
                break
            from_id = page[-1].get("id")
            if not from_id:
                break

        return transactions
