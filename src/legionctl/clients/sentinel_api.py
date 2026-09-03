from __future__ import annotations

import json
import logging
import ssl
import uuid
from typing import Any, Literal, TypeVar
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, ValidationError

from legionctl import __version__
from legionctl.constants import (
    API_PREFIX,
    CONNECT_TIMEOUT_SECONDS,
    IDEMPOTENT_READ_RETRIES,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_SCAN_DURATION_SECONDS,
    READ_TIMEOUT_SECONDS,
    WRITE_TIMEOUT_SECONDS,
)
from legionctl.errors import (
    AuthenticationError,
    CredentialError,
    LegionError,
    MalformedResponseError,
    NodeUnreachableError,
    NodeValidationError,
    TlsError,
    UsageError,
    map_http_status,
)
from legionctl.models.node_api import (
    ConfigResponse,
    HealthResponse,
    InfoResponse,
    RebootRequest,
    RebootResponse,
    RecentEventsResponse,
    RulesActivationResponse,
    RulesRejectionResponse,
    RulesResponse,
    ScanRequest,
    ScanResponse,
    TestAlertRequest,
    TestAlertResponse,
)
from legionctl.models.profile import Profile
from legionctl.redaction import redact_secrets
from legionctl.services.credentials import CredentialStore

logger = logging.getLogger("legionctl.clients.sentinel_api")

T = TypeVar("T", bound=BaseModel)


def build_api_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/") + "/"
    if base.rstrip("/").endswith(API_PREFIX):
        root = base
    else:
        root = urljoin(base, API_PREFIX.lstrip("/") + "/")
    return urljoin(root, path.lstrip("/"))


def map_transport_error(exc: BaseException) -> LegionError:
    message = str(exc).lower()
    name = type(exc).__name__.lower()
    cause = exc.__cause__ or exc.__context__
    cause_name = type(cause).__name__.lower() if cause is not None else ""
    cause_message = str(cause).lower() if cause is not None else ""
    combined = f"{name} {message} {cause_name} {cause_message}"
    if isinstance(exc, ssl.SSLError) or isinstance(cause, ssl.SSLError):
        return TlsError("TLS verification failed")
    if any(token in combined for token in ("certificate", "ssl", "tls", "certverify")):
        return TlsError("TLS verification failed")
    if "timeout" in name or "timeout" in message or isinstance(exc, httpx.TimeoutException):
        return NodeUnreachableError("Sentinel node timed out")
    return NodeUnreachableError("Sentinel node is unreachable")


def _is_retryable(exc: LegionError) -> bool:
    if isinstance(exc, (AuthenticationError, CredentialError, TlsError, UsageError)):
        return False
    if isinstance(exc, NodeUnreachableError):
        return True
    if isinstance(exc, MalformedResponseError):
        return False
    if isinstance(exc, NodeValidationError):
        return False
    return isinstance(exc, LegionError) and "HTTP 5" in str(exc)


class SentinelApiClient:
    """Async HTTPS client for a single Sentinel node's REST API."""

    def __init__(
        self,
        base_url: str,
        sentinel_id: str,
        credentials: CredentialStore,
        *,
        connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
        read_timeout: float = READ_TIMEOUT_SECONDS,
        write_timeout: float = WRITE_TIMEOUT_SECONDS,
        read_retries: int = IDEMPOTENT_READ_RETRIES,
        max_request_bytes: int = MAX_REQUEST_BYTES,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        max_scan_duration_seconds: int = MAX_SCAN_DURATION_SECONDS,
        verify: bool | str = True,
        insecure_skip_tls_verify: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url:
            raise UsageError("base_url is required")
        if not sentinel_id:
            raise UsageError("sentinel_id is required")
        self._base_url = base_url
        self._sentinel_id = sentinel_id
        self._credentials = credentials
        self._read_retries = read_retries
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._max_scan_duration_seconds = max_scan_duration_seconds
        self._verify: bool | str = False if insecure_skip_tls_verify else verify
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=write_timeout,
            pool=read_timeout,
        )
        self._client = client
        self._owns_client = client is None

    @property
    def sentinel_id(self) -> str:
        return self._sentinel_id

    @property
    def timeout(self) -> httpx.Timeout:
        return self._timeout

    @property
    def tls_verify(self) -> bool | str:
        return self._verify

    async def __aenter__(self) -> SentinelApiClient:
        await self._ensure_client()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_info(self) -> InfoResponse:
        return await self._get("info", InfoResponse)

    async def get_health(self) -> HealthResponse:
        return await self._get("health", HealthResponse)

    async def get_config(self) -> ConfigResponse:
        return await self._get("config", ConfigResponse)

    async def get_rules(self) -> RulesResponse:
        return await self._get("rules", RulesResponse)

    async def put_rules(
        self,
        profile: Profile,
        *,
        idempotency_key: str | None = None,
    ) -> RulesActivationResponse:
        payload = json.loads(profile.model_dump_json())
        response = await self._send(
            "PUT",
            "rules",
            json_body=payload,
            retry=False,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )
        if response.status_code == 422:
            raise self._rejection_error(response)
        self._raise_for_status(response)
        parsed = self._parse_json(response)
        if isinstance(parsed, dict) and parsed.get("status") == "rejected":
            raise self._rejection_error(response)
        return self._validate_model(parsed, RulesActivationResponse)

    async def test_alert(
        self,
        *,
        message: str = "Legion test alert",
        include_health_summary: bool = True,
        idempotency_key: str | None = None,
    ) -> TestAlertResponse:
        body = TestAlertRequest(
            message=message,
            include_health_summary=include_health_summary,
        )
        return await self._post(
            "commands/test-alert",
            TestAlertResponse,
            json_body=json.loads(body.model_dump_json()),
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )

    async def scan(
        self,
        *,
        action: Literal["start", "stop"],
        technology: Literal["wifi", "ble", "bt_classic"],
        duration_seconds: int,
    ) -> ScanResponse:
        if action == "start" and duration_seconds > self._max_scan_duration_seconds:
            raise UsageError(
                f"scan duration must be <= {self._max_scan_duration_seconds} seconds"
            )
        try:
            body = ScanRequest(
                action=action,
                technology=technology,
                duration_seconds=duration_seconds,
            )
        except ValidationError as exc:
            raise UsageError("invalid scan request") from exc
        return await self._post(
            "commands/scan",
            ScanResponse,
            json_body=json.loads(body.model_dump_json()),
        )

    async def reboot(self, *, reason: str = "operator_requested") -> RebootResponse:
        body = RebootRequest(reason=reason)
        return await self._post(
            "commands/reboot",
            RebootResponse,
            json_body=json.loads(body.model_dump_json()),
            allow_empty=True,
        )

    async def recent_events(self, *, limit: int = 100) -> RecentEventsResponse:
        if limit < 1:
            raise UsageError("limit must be at least 1")
        return await self._get("events/recent", RecentEventsResponse, params={"limit": limit})

    async def _get(
        self,
        path: str,
        model: type[T],
        *,
        params: dict[str, Any] | None = None,
    ) -> T:
        response = await self._send("GET", path, params=params, retry=True)
        self._raise_for_status(response)
        return self._validate_model(self._parse_json(response), model)

    async def _post(
        self,
        path: str,
        model: type[T],
        *,
        json_body: dict[str, Any],
        idempotency_key: str | None = None,
        allow_empty: bool = False,
    ) -> T:
        response = await self._send(
            "POST",
            path,
            json_body=json_body,
            retry=False,
            idempotency_key=idempotency_key,
        )
        self._raise_for_status(response)
        if allow_empty and not response.content:
            return model()
        return self._validate_model(self._parse_json(response), model)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        retry: bool,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        attempts = 1 + self._read_retries if retry else 1
        last_error: LegionError | None = None
        for attempt in range(attempts):
            try:
                response = await self._send_once(
                    method,
                    path,
                    json_body=json_body,
                    params=params,
                    idempotency_key=idempotency_key,
                )
            except LegionError as exc:
                last_error = exc
                if not retry or attempt >= attempts - 1 or not _is_retryable(exc):
                    raise
                continue
            if response.status_code >= 500 and retry and attempt < attempts - 1:
                last_error = map_http_status(
                    response.status_code,
                    f"HTTP {response.status_code}",
                )
                continue
            return response
        assert last_error is not None
        raise last_error

    async def _send_once(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None,
        params: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> httpx.Response:
        token = self._bearer_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        content: bytes | None = None
        if json_body is not None:
            content = json.dumps(json_body).encode("utf-8")
            if len(content) > self._max_request_bytes:
                raise UsageError("request body exceeds size limit")
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        url = build_api_url(self._base_url, path)
        client = await self._ensure_client()
        logger.debug("%s %s", method, url)
        try:
            response = await client.request(
                method,
                url,
                content=content,
                params=params,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise map_transport_error(exc) from exc
        self._enforce_response_size(response)
        return response

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                verify=self._verify,
                follow_redirects=False,
                headers={"User-Agent": f"legionctl/{__version__}"},
            )
            self._owns_client = True
        return self._client

    def _bearer_token(self) -> str:
        token = self._credentials.get_token(self._sentinel_id)
        if not token:
            raise CredentialError(f"no bearer token stored for {self._sentinel_id}")
        return token

    def _enforce_response_size(self, response: httpx.Response) -> None:
        length_header = response.headers.get("Content-Length")
        if length_header:
            try:
                if int(length_header) > self._max_response_bytes:
                    raise MalformedResponseError("Sentinel response exceeds size limit")
            except ValueError:
                pass
        if len(response.content) > self._max_response_bytes:
            raise MalformedResponseError("Sentinel response exceeds size limit")

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        message = f"HTTP {response.status_code}"
        payload = None
        if response.content:
            try:
                payload = response.json()
            except json.JSONDecodeError:
                payload = None
        if isinstance(payload, dict):
            raw = payload.get("message") or payload.get("error") or payload.get("detail")
            if isinstance(raw, str) and raw.strip():
                message = redact_secrets(raw.strip())
        raise map_http_status(response.status_code, message)

    def _parse_json(self, response: httpx.Response) -> Any:
        if not response.content:
            raise MalformedResponseError("Sentinel response was empty")
        try:
            return json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedResponseError("Sentinel response was not valid JSON") from exc

    def _validate_model(self, payload: Any, model: type[T]) -> T:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise MalformedResponseError("Sentinel response failed schema validation") from exc

    def _rejection_error(self, response: httpx.Response) -> NodeValidationError:
        try:
            payload = self._parse_json(response)
            rejection = RulesRejectionResponse.model_validate(payload)
        except (MalformedResponseError, ValidationError):
            return NodeValidationError("Sentinel rejected the profile")
        details = [f"{item.path}: {item.message}" for item in rejection.errors]
        message = "; ".join(details) if details else "Sentinel rejected the profile"
        return NodeValidationError(redact_secrets(message), errors=details)
