"""CRM adapters. The mock store is always written. HubSpot and GoHighLevel mirror it."""

from __future__ import annotations

import os
from typing import Protocol

import httpx

from app import db


def split_name(name: str | None) -> tuple[str, str]:
    if not name:
        return "", ""
    first, _, last = name.strip().partition(" ")
    return first, last


def hubspot_properties(lead: dict) -> dict:
    first, last = split_name(lead.get("name"))
    return {
        "email": lead.get("email") or "",
        "firstname": first,
        "lastname": last,
        "company": lead.get("company") or "",
        "lifecyclestage": "lead",
        "hs_lead_status": "NEW",
    }


def highlevel_payload(lead: dict) -> dict:
    first, last = split_name(lead.get("name"))
    return {
        "email": lead.get("email") or "",
        "firstName": first,
        "lastName": last,
        "name": lead.get("name") or "",
        "companyName": lead.get("company") or "",
        "source": "Lane inbox triage",
        "tags": ["lane", lead.get("category") or "lead"],
    }


def _push_hubspot(lead: dict) -> bool:
    token = os.environ.get("HUBSPOT_TOKEN", "").strip()
    if not token:
        return False
    response = httpx.post(
        "https://api.hubapi.com/crm/v3/objects/contacts",
        headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
        json={"properties": hubspot_properties(lead)},
        timeout=20,
    )
    response.raise_for_status()
    return True


def _push_highlevel(lead: dict) -> bool:
    token = os.environ.get("GHL_API_KEY", "").strip()
    location = os.environ.get("GHL_LOCATION_ID", "").strip()
    if not token or not location:
        return False
    payload = highlevel_payload(lead)
    payload["locationId"] = location
    response = httpx.post(
        "https://services.leadconnectorhq.com/contacts/",
        headers={
            "authorization": f"Bearer {token}",
            "version": "2021-07-28",
            "content-type": "application/json",
        },
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    return True


class CrmAdapter(Protocol):
    name: str

    def upsert_contact(self, lead: dict) -> dict | None:
        """Create or update one contact. Return a stored row for the local adapter."""


class MockCrm:
    """SQLite stand-in so the desk works before a client connects a CRM."""

    name = "mock"

    def upsert_contact(self, lead: dict) -> dict:
        return db.upsert_lead(lead)


class HubSpotCrm:
    """HubSpot CRM v3 contacts. Uses the same property map a private app expects."""

    name = "hubspot"

    def upsert_contact(self, lead: dict) -> None:
        _push_hubspot(lead)


class GoHighLevelCrm:
    name = "gohighlevel"

    def upsert_contact(self, lead: dict) -> None:
        _push_highlevel(lead)


def active_adapters() -> list[CrmAdapter]:
    adapters: list[CrmAdapter] = [MockCrm()]
    if os.environ.get("HUBSPOT_TOKEN", "").strip():
        adapters.append(HubSpotCrm())
    if os.environ.get("GHL_API_KEY", "").strip() and os.environ.get("GHL_LOCATION_ID", "").strip():
        adapters.append(GoHighLevelCrm())
    return adapters


def destination_label() -> str:
    return "+".join(adapter.name for adapter in active_adapters())


def store_lead(lead: dict) -> dict:
    """Write the mock CRM, then mirror to whichever remote adapters are configured."""
    remote: list[str] = []
    errors: list[str] = []
    for adapter in active_adapters():
        if adapter.name == "mock":
            continue
        try:
            adapter.upsert_contact(lead)
            remote.append(adapter.name)
        except Exception as exc:
            errors.append(f"{adapter.name}: {exc}")
    stored = MockCrm().upsert_contact({**lead, "destination": "+".join(["mock", *remote])})
    if errors:
        stored["remote_errors"] = errors
    return stored
