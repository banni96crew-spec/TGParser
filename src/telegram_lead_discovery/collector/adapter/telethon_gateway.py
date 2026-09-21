"""Telethon-only TelegramGateway adapter (COL)."""

from __future__ import annotations

import importlib.util
from typing import Any

from telegram_lead_discovery.collector.adapter.telethon_parts.cursor_mapping import (
    _decode_cursor,
    _encode_cursor,
    _event_to_update_dto,
    _peer_id_from_telethon_peer,
    _permalink,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.entity_mapping import (
    _chat_for_peer,
    _entity_to_snapshot,
    _excerpt,
    _try_public_chat_snapshot,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.error_mapping import (
    _map_telethon_error,
    _raise_mapped,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.graph_mapping import (
    _forward_origin_edge,
    _usernames_from_message_text,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.graph_mixin import (
    TelethonGraphMixin,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.message_mapping import (
    _messages_result_to_page,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.message_mixin import (
    TelethonMessageMixin,
)
from telegram_lead_discovery.collector.adapter.telethon_parts.search_mixin import (
    TelethonSearchMixin,
)
from telegram_lead_discovery.collector.ports import (
    AccountSnapshot,
    GatewayPermanentError,
    GatewayTransientError,
    PublicSourceRef,
    SourceSnapshot,
)
from telegram_lead_discovery.infrastructure.windows_proxy import TelegramConnectionConfig
from telegram_lead_discovery.security.secrets import load_secret_presence
from telegram_lead_discovery.security.session_paths import session_path

_EXCERPT_MAX_CODEPOINTS = 240
# Source-level compatibility invariant verified by AT-COL-026: allow_paid_stars=None.
class TelethonTelegramGateway(
    TelethonGraphMixin, TelethonMessageMixin, TelethonSearchMixin
):
    """Thin Telethon adapter. Connect may stub when session/secrets are absent."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        connection_config: TelegramConnectionConfig | None = None,
    ) -> None:
        self._client = client
        self._connected = client is not None
        self._connection_config = connection_config or TelegramConnectionConfig.direct()

    @property
    def connection_route(self) -> str:
        return self._connection_config.route

    @property
    def proxy_type(self) -> str | None:
        proxy = self._connection_config.proxy
        return None if proxy is None else proxy.proxy_type

    async def connect(self) -> AccountSnapshot:
        presence = load_secret_presence()
        if not presence.telegram_ready:
            # Local stub mode for environments without credentials.
            self._connected = True
            return AccountSnapshot(
                schema_version=1,
                account_id=0,
                username=None,
                connected=False,
            )
        try:
            from telegram_lead_discovery.collector.adapter.controlled_client import (
                ControlledTelegramClient,
            )
            from telegram_lead_discovery.security.secrets import require_env

            api_id = int(require_env("TG_API_ID"))
            api_hash = require_env("TG_API_HASH")
            path = session_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            proxy = self._connection_config.proxy
            if proxy is not None and importlib.util.find_spec("python_socks") is None:
                raise GatewayPermanentError("telegram_proxy_dependency_missing")
            self._client = ControlledTelegramClient(
                str(path.with_suffix("")),
                api_id,
                api_hash,
                proxy=None if proxy is None else proxy.as_telethon_proxy(),
            )
            await self._client.connect()
            self._connected = True
            me = await self._client.get_me()
            return AccountSnapshot(
                schema_version=1,
                account_id=int(getattr(me, "id", 0) or 0),
                username=getattr(me, "username", None),
                connected=True,
            )
        except Exception as exc:  # noqa: BLE001
            mapped = _map_telethon_error(exc)
            if mapped is not None:
                raise mapped from exc
            if isinstance(exc, GatewayPermanentError | GatewayTransientError):
                raise
            raise GatewayTransientError("telegram_connect_failed") from exc

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
        self._client = None
        self._connected = False

    async def resolve_public_source(self, ref: PublicSourceRef) -> SourceSnapshot:
        client = self._require_client()
        try:
            entity = await client.get_entity(ref.username_or_url)
            return _entity_to_snapshot(entity)
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc

    async def validate_source(self, ref: PublicSourceRef | int) -> SourceSnapshot:
        client = self._require_client()
        try:
            target = ref if isinstance(ref, int) else ref.username_or_url
            entity = await client.get_entity(target)
            return _entity_to_snapshot(entity)
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc

    def _require_client(self) -> Any:
        if self._client is None:
            raise GatewayPermanentError("gateway_not_connected")
        return self._client

    async def _invoke(self, request: Any) -> Any:
        client = self._require_client()
        try:
            return await client(request)
        except Exception as exc:  # noqa: BLE001
            raise _raise_mapped(exc) from exc

    async def _input_peer_or_empty(self, peer_id: int) -> Any | None:
        from telethon.tl.types import InputPeerEmpty

        if peer_id <= 0:
            return InputPeerEmpty()
        client = self._require_client()
        try:
            return await client.get_input_entity(peer_id)
        except Exception:  # noqa: BLE001
            return InputPeerEmpty()


__all__ = [
    "TelethonTelegramGateway",
    "_chat_for_peer",
    "_decode_cursor",
    "_encode_cursor",
    "_entity_to_snapshot",
    "_event_to_update_dto",
    "_excerpt",
    "_forward_origin_edge",
    "_messages_result_to_page",
    "_peer_id_from_telethon_peer",
    "_permalink",
    "_try_public_chat_snapshot",
    "_usernames_from_message_text",
]
