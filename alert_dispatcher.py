"""
alert_dispatcher.py — Broadcast approved disaster alerts to all channels (Layer 4).

Triggered when a human approves a drafted alert via the
POST /api/v1/alerts/{id}/approve endpoint (Layer 3).

Dispatch flow:
  1. Fetch the approved alert document from Mongo (Layer 3's alerts collection).
  2. Convert the alert's geo context into an AffectedRegion.
  3. Reuse webhooks.py's filter_sessions_by_region() to get affected users
     (no duplicated region-matching logic).
  4. For each matched user session, fan out to their preferred channel:
     - WhatsApp → Meta WhatsApp Cloud API (whatsapp_webhook.send_whatsapp_message)
     - SMS      → Twilio Programmable SMS (sms_webhook.send_sms)
  5. Record per-channel delivery status back into the alert document's
     delivery_status array in Mongo (auditable record).

Out of scope (no budget / no telco access):
  - Cell Broadcast (CBAS) — requires government / telco infrastructure
  - VHF / CSC integration — requires radio hardware and licensing
  Both are intentionally skipped; a comment marks them so future contributors
  know these channels can't be faked with a free API.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("weathergpt.alert_dispatcher")


class AlertDispatcher:
    """
    Fans out a human-approved alert to all registered user sessions
    via their preferred communication channel.
    """

    def __init__(self):
        # Twilio client only needed for SMS now (WhatsApp uses Meta Cloud API)
        self._twilio_client = None
        TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
        TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
        if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
            try:
                from twilio.rest import Client as TwilioClient
                self._twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                logger.info("Twilio client initialized for SMS alert dispatch")
            except Exception:
                logger.warning("Twilio client could not be initialised — SMS dispatch will fail gracefully")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def dispatch_approved_alert(self, alert_id: str) -> Dict[str, Any]:
        """
        Dispatch an approved alert to all affected users.

        Called from main.py's POST /api/v1/alerts/{id}/approve handler
        after the alert is marked approved in Mongo.

        Returns a summary dict: total_users, sent, failed, per_user_status.
        """
        from db.mongo import get_mongo_manager
        from webhooks import (
            AffectedRegion,
            BroadcastResponse,  # noqa: F401 — confirms shape
            filter_sessions_by_region,
            get_active_sessions,
        )

        mongo = get_mongo_manager()
        if mongo._db is None:
            await mongo.initialize()

        alert_doc = await mongo.get_alert_by_id(alert_id)
        if not alert_doc:
            logger.error("Alert %s not found in Mongo", alert_id)
            return {"error": "alert_not_found", "alert_id": alert_id}

        if alert_doc.get("delivery_status") != "approved":
            logger.warning("Alert %s is not approved (status=%s) — skipping dispatch",
                           alert_id, alert_doc.get("delivery_status"))
            return {"error": "not_approved", "alert_id": alert_id}

        # Build the GeoPoint region from the alert's location
        lat = alert_doc.get("latitude")
        lon = alert_doc.get("longitude")
        if lat is None or lon is None:
            logger.warning("Alert %s has no lat/lon — cannot do region filtering", alert_id)
            region = None
        else:
            radius_km = float(os.getenv("ALERT_POLL_RADIUS_KM", "2000"))
            region = AffectedRegion(
                centre={"lat": lat, "lon": lon},
                radius_km=radius_km,
            )

        # Get the script text (may already be localized)
        script_text = alert_doc.get("script_text", "")
        if not script_text:
            logger.warning("Alert %s has no script_text — skipping", alert_id)
            return {"error": "no_script", "alert_id": alert_id}

        # ---- Step 3: reuse webhooks.py region filtering ----
        if region:
            matched_sessions = filter_sessions_by_region(region)
        else:
            matched_sessions = get_active_sessions()

        logger.info(
            "Dispatching approved alert %s to %d matched sessions",
            alert_id, len(matched_sessions),
        )

        # ---- Step 4: fan-out with bounded concurrency ----
        max_concurrency = int(os.getenv("MAX_DISPATCH_CONCURRENCY", "20"))
        semaphore = asyncio.Semaphore(max_concurrency)

        results = await asyncio.gather(
            *[self._dispatch_guarded(s, alert_doc, script_text, semaphore) for s in matched_sessions]
        )

        sent = sum(1 for r in results if r["success"])
        failed = sum(1 for r in results if not r["success"])

        # ---- Step 5: record delivery status back into Mongo ----
        await mongo.record_delivery_results(alert_id, results)

        logger.info(
            "Alert %s dispatch complete: sent=%d failed=%d total=%d",
            alert_id, sent, failed, len(matched_sessions),
        )

        return {
            "alert_id": alert_id,
            "total_users": len(matched_sessions),
            "sent": sent,
            "failed": failed,
            "per_user_status": results,
        }

    # ------------------------------------------------------------------
    # Per-user dispatch
    # ------------------------------------------------------------------

    async def _dispatch_to_user(
        self,
        session: "UserSession",
        alert_doc: Dict[str, Any],
        script_text: str,
    ) -> Dict[str, Any]:
        """Dispatch the alert to a single user via their registered channel."""
        channel = session.channel
        address = session.address

        if channel == "sms":
            from sms_webhook import send_sms
            success = await send_sms(address, script_text)
            return {
                "user_id": session.user_id,
                "channel": "sms",
                "address": address,
                "success": success,
                "detail": None if success else "Twilio API error",
                "dispatched_at": datetime.now(timezone.utc).isoformat(),
            }

        elif channel == "whatsapp":
            from whatsapp_webhook import send_whatsapp_message
            success = await send_whatsapp_message(address, script_text)
            return {
                "user_id": session.user_id,
                "channel": "whatsapp",
                "address": address,
                "success": success,
                "detail": None if success else "Meta WhatsApp Cloud API error",
                "dispatched_at": datetime.now(timezone.utc).isoformat(),
            }

        elif channel == "voice":
            # For voice/SMS-only users without WhatsApp, we still attempt SMS
            # as a fallback since they have a phone number.
            logger.info("Voice channel user %s — dispatching via SMS fallback", session.user_id)
            from sms_webhook import send_sms
            success = await send_sms(address, script_text)
            return {
                "user_id": session.user_id,
                "channel": "sms_fallback",
                "address": address,
                "success": success,
                "detail": None if success else "SMS fallback failed",
                "dispatched_at": datetime.now(timezone.utc).isoformat(),
            }

        elif channel == "cbas":
            # Cell Broadcast (CBAS) — government / telco infrastructure required.
            # This stub preserves the channel architecture so it can be enabled
            # when telco partnerships are available. The dispatch logic
            # (geofence-based broadcast to all phones in a geographic cell)
            # would be implemented via a telco-provided CMAS/DTISG API.
            #
            # Not currently implemented due to budget constraints for
            # telco API access. This stub records the intent and returns
            # a structured failure so the audit trail shows the channel
            # was attempted.
            logger.info(
                "CBAS dispatch requested for user %s — telco infrastructure "
                "not available (budget constraint)", session.user_id,
            )
            return {
                "user_id": session.user_id,
                "channel": "cbas",
                "address": address,
                "success": False,
                "detail": (
                    "CBAS dispatch stub: requires telco CMAS/DTISG API access. "
                    "Architecture is ready — integration pending funding."
                ),
                "dispatched_at": datetime.now(timezone.utc).isoformat(),
            }

        elif channel == "vhf_csc":
            # VHF / CSC (Common Service Center) radio broadcast — requires
            # radio hardware and government licensing. This stub preserves
            # the channel in the architecture for future integration with
            # All India Radio or state disaster management VHF networks.
            #
            # Not currently implemented — no budget for radio hardware or
            # licensing. The alert payload is already formatted for
            # short broadcast (≤60 words) so it can be handed off to an
            # operator when hardware is available.
            logger.info(
                "VHF/CSC dispatch requested for user %s — radio hardware "
                "and licensing not available (budget constraint)", session.user_id,
            )
            return {
                "user_id": session.user_id,
                "channel": "vhf_csc",
                "address": address,
                "success": False,
                "detail": (
                    "VHF/CSC dispatch stub: requires radio hardware and "
                    "government licensing. Architecture is ready — integration "
                    "pending funding for VHF equipment and operator licensing."
                ),
                "dispatched_at": datetime.now(timezone.utc).isoformat(),
            }

        else:
            logger.warning("Unknown channel=%s for user=%s", channel, session.user_id)
            # CBAS (Cell Broadcast) and VHF/CSC are handled by their own
            # dedicated branches above. Unknown channels are logged as errors.
            # See k8s/00-secrets.yaml for notes on out-of-scope channels.
            return {
                "user_id": session.user_id,
                "channel": channel,
                "address": address,
                "success": False,
                "detail": "unsupported channel (CBAS/VHF/CSC out of scope — requires telco access)",
                "dispatched_at": datetime.now(timezone.utc).isoformat(),
            }

    async def _dispatch_guarded(
        self,
        session: "UserSession",
        alert_doc: Dict[str, Any],
        script_text: str,
        semaphore: asyncio.Semaphore,
    ) -> Dict[str, Any]:
        """Wrap _dispatch_to_user with a semaphore for bounded concurrency."""
        async with semaphore:
            try:
                return await self._dispatch_to_user(session, alert_doc, script_text)
            except Exception as exc:
                logger.exception("Dispatch to %s failed: %s", session.user_id, exc)
                return {
                    "user_id": session.user_id,
                    "channel": session.channel,
                    "address": session.address,
                    "success": False,
                    "detail": str(exc),
                    "dispatched_at": datetime.now(timezone.utc).isoformat(),
                }


# ---------------------------------------------------------------------------
# Module-level singleton + helper
# ---------------------------------------------------------------------------

_dispatcher: Optional[AlertDispatcher] = None


def get_alert_dispatcher() -> AlertDispatcher:
    """Get or create the singleton AlertDispatcher."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = AlertDispatcher()
    return _dispatcher


async def dispatch_approved_alert(alert_id: str) -> Dict[str, Any]:
    """Module-level convenience wrapper for the approve endpoint."""
    return await get_alert_dispatcher().dispatch_approved_alert(alert_id)
