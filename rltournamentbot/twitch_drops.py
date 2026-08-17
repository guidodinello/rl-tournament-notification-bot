import dataclasses

import aiohttp

from .logger import get_logger
from .models import Tournament

logger = get_logger(__name__)

TWITCH_GQL_URL = "https://gql.twitch.tv/gql"
# Public web client ID used by Twitch's own web player for unauthenticated
# GraphQL queries. Undocumented but stable in practice -- see
# TwitchDropsMiner (https://github.com/DevilXD/TwitchDropsMiner) for prior art.
TWITCH_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"

_HEADERS = {"Client-Id": TWITCH_CLIENT_ID, "Content-Type": "application/json"}

_RESOLVE_CHANNEL_ID_QUERY = {
    "operationName": "ChannelPointsContext",
    "sha256Hash": "374314de591e69925fce3ddc2bcf085796f56ebb8cad67a0daa3165c03adc345",
}

_AVAILABLE_DROPS_QUERY = {
    "operationName": "DropsHighlightService_AvailableDrops",
    "sha256Hash": "782dad0f032942260171d2d80a654f88bdd0c5a9dddc392e9bc92218a0f42d20",
}


class TwitchDropsUnavailable(Exception):
    """Raised when the Twitch GraphQL check fails (network/schema error).

    Distinct from a clean "no active campaign" result, which is a normal
    outcome and returns None rather than raising.
    """


async def _gql(session: aiohttp.ClientSession, query: dict, variables: dict) -> dict:
    payload = {
        "operationName": query["operationName"],
        "variables": variables,
        "extensions": {
            "persistedQuery": {"version": 1, "sha256Hash": query["sha256Hash"]},
        },
    }
    async with session.post(TWITCH_GQL_URL, json=payload, headers=_HEADERS) as resp:
        resp.raise_for_status()
        return await resp.json()


async def _resolve_channel_id(session: aiohttp.ClientSession, channel_login: str) -> str | None:
    data = await _gql(session, _RESOLVE_CHANNEL_ID_QUERY, {"channelLogin": channel_login})
    community = data.get("data", {}).get("community")
    if community is None:
        return None
    return community["id"]


async def get_active_drop_campaign(
    session: aiohttp.ClientSession, channel_login: str
) -> str | None:
    try:
        channel_id = await _resolve_channel_id(session, channel_login)
        if channel_id is None:
            return None

        data = await _gql(session, _AVAILABLE_DROPS_QUERY, {"channelID": channel_id})
        campaigns = data["data"]["channel"]["viewerDropCampaigns"]
        if not campaigns:
            return None
        return campaigns[0]["name"]
    except TwitchDropsUnavailable:
        raise
    except Exception as e:
        raise TwitchDropsUnavailable(f"Twitch drops check failed for {channel_login!r}: {e}") from e


async def enrich_with_drops(
    tournaments: list[Tournament], session: aiohttp.ClientSession
) -> tuple[list[Tournament], int]:
    enriched: list[Tournament] = []
    failures = 0

    for t in tournaments:
        if not t.twitch_channels:
            enriched.append(t)
            continue

        try:
            campaign = await get_active_drop_campaign(session, t.twitch_channels[0])
            enriched.append(dataclasses.replace(t, drops_campaign=campaign))
        except TwitchDropsUnavailable:
            logger.warning("Twitch drops check failed for %s", t.name, exc_info=True)
            failures += 1
            enriched.append(t)

    return enriched, failures
