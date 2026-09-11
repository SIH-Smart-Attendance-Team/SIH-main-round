"""
alert_generator.py — Proactive disaster warning draft generator.

Scheduled background job (Layer 3) that:
  1. Polls disaster_tools.py data sources on a configurable interval
  2. Diffs against last-seen state in PostgreSQL disaster_events
  3. Detects NEW events and SEVERITY ESCALATIONS
  4. Auto-drafts short localized warnings via AI_engine.py
  5. Stores drafts in MongoDB alerts collection (pending human approval)
  6. Exposes approve/reject endpoints for human review before delivery

Design notes:
- Uses a simple asyncio loop (no APScheduler dependency) matching main.py's
  @app.on_event("startup") lifecycle pattern.
- Fully degradable: if any upstream source, Postgres, Mongo, or LLM fails,
  the cycle is logged and skipped without crashing the scheduler loop.
- Nothing is auto-sent. Every draft requires human approval first.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("weathergpt.alert_generator")

# Severity order per IMD 4-level convention
SEVERITY_ORDER = {"green": 0, "yellow": 1, "orange": 2, "red": 3}


def _event_fingerprint(event: Dict[str, Any]) -> str:
    """
    Create a stable fingerprint for an event across polls.

    Fingerprint is derived from source + hazard type + event time + title +
    coordinates so the same real-world event is recognized even when the
    upstream feed re-issues it with minor metadata changes.
    """
    source = str(event.get("source", "unknown"))
    hazard_type = str(event.get("hazard_type", "unknown"))
    event_time = str(event.get("event_time") or "")
    title = str(event.get("title", ""))
    lat = event.get("latitude")
    lon = event.get("longitude")
    raw = f"{source}|{hazard_type}|{event_time}|{title}|{lat}|{lon}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _event_key(event: Dict[str, Any]) -> Tuple[str, str, str]:
    """Return (source, hazard_type, fingerprint) tuple for diffing."""
    return (
        str(event.get("source", "unknown")),
        str(event.get("hazard_type", "unknown")),
        _event_fingerprint(event),
    )


def _severity_escalated(old_severity: str, new_severity: str) -> bool:
    """Return True if severity increased per IMD convention."""
    old_level = SEVERITY_ORDER.get(str(old_severity).lower(), 0)
    new_level = SEVERITY_ORDER.get(str(new_severity).lower(), 0)
    return new_level > old_level


class AlertGenerator:
    """
    Scheduled proactive disaster warning draft generator.

    Polls disaster sources, diffs against PostgreSQL last-seen state, drafts
    short localized warnings for new or escalated events, and stores them in
    MongoDB pending human approval.
    """

    def __init__(
        self,
        poll_interval_seconds: Optional[int] = None,
        languages: Optional[List[str]] = None,
        poll_latitude: Optional[float] = None,
        poll_longitude: Optional[float] = None,
        poll_radius_km: Optional[float] = None,
        poll_days: Optional[int] = None,
        max_drafts_per_cycle: Optional[int] = None,
    ):
        self.poll_interval_seconds = poll_interval_seconds or int(
            os.getenv("ALERT_POLL_INTERVAL_SECONDS", "900")
        )
        self.languages = languages or [
            lang.strip()
            for lang in os.getenv("ALERT_LANGUAGES", "english,hindi").split(",")
            if lang.strip()
        ]
        self.poll_latitude = poll_latitude if poll_latitude is not None else float(
            os.getenv("ALERT_POLL_LAT", "28.61")
        )
        self.poll_longitude = poll_longitude if poll_longitude is not None else float(
            os.getenv("ALERT_POLL_LON", "77.21")
        )
        self.poll_radius_km = poll_radius_km if poll_radius_km is not None else float(
            os.getenv("ALERT_POLL_RADIUS_KM", "2000")
        )
        self.poll_days = poll_days if poll_days is not None else int(
            os.getenv("ALERT_POLL_DAYS", "14")
        )
        self.max_drafts_per_cycle = max_drafts_per_cycle or int(
            os.getenv("ALERT_MAX_DRAFTS_PER_CYCLE", "20")
        )
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_poll_at: Optional[datetime] = None
        self._last_cycle_stats: Dict[str, int] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_poll_at(self) -> Optional[datetime]:
        return self._last_poll_at

    @property
    def last_cycle_stats(self) -> Dict[str, int]:
        return dict(self._last_cycle_stats)

    async def start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            return
        self._stop_event = asyncio.Event()
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="alert-generator")
        logger.info(
            "Alert generator scheduler started (interval=%ss, languages=%s)",
            self.poll_interval_seconds,
            ",".join(self.languages),
        )

    async def stop(self) -> None:
        """Stop the scheduler loop gracefully."""
        self._running = False
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Alert generator scheduler stopped")

    async def _run_loop(self) -> None:
        """Background loop: poll immediately, then wait interval between polls."""
        while not self._stop_event.is_set():
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("Alert generator poll cycle failed: %s", exc)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass

    async def poll_once(self) -> Dict[str, int]:
        """
        Run a single poll cycle.

        Returns stats dict: {events_seen, new_events, escalated_events, drafts_created, errors}
        """
        stats = {
            "events_seen": 0,
            "new_events": 0,
            "escalated_events": 0,
            "drafts_created": 0,
            "errors": 0,
        }

        try:
            # 1. Fetch current disaster state from disaster_tools
            from disaster_tools import get_disaster_alerts

            result = await get_disaster_alerts(
                latitude=self.poll_latitude,
                longitude=self.poll_longitude,
                radius_km=self.poll_radius_km,
                days=self.poll_days,
            )
            current_events = list(result.get("alerts", []))
            stats["events_seen"] = len(current_events)
            self._last_poll_at = datetime.now(timezone.utc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch disaster events: %s", exc)
            stats["errors"] += 1
            self._last_cycle_stats = stats
            return stats

        if not current_events:
            logger.info("No disaster events in this poll cycle")
            self._last_cycle_stats = stats
            return stats

        # 2. Load last-seen state from PostgreSQL disaster_events
        try:
            from db.postgres import get_postgres_manager

            pg = get_postgres_manager()
            await pg.initialize()
            last_seen = await pg.get_disaster_events(limit=500)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load last-seen disaster state: %s", exc)
            stats["errors"] += 1
            self._last_cycle_stats = stats
            return stats

        last_seen_map: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for event in last_seen:
            raw = event.raw_json or {}
            fingerprint = raw.get("fingerprint") or _event_fingerprint(raw)
            key = (
                str(event.source),
                str(event.type),
                str(fingerprint),
            )
            # Keep the highest severity seen for this fingerprint
            existing = last_seen_map.get(key)
            if existing is None or SEVERITY_ORDER.get(
                str(event.severity).lower(), 0
            ) > SEVERITY_ORDER.get(str(existing.severity).lower(), 0):
                last_seen_map[key] = event

        # 3. Diff current vs last-seen: new events + severity escalations
        candidates: List[Tuple[Dict[str, Any], str]] = []
        seen_fingerprints: Set[str] = set()
        for event in current_events:
            fingerprint = _event_fingerprint(event)
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)

            key = _event_key(event)
            previous = last_seen_map.get(key)
            if previous is None:
                candidates.append((event, "new"))
                stats["new_events"] += 1
            elif _severity_escalated(previous.severity, event.get("severity", "")):
                candidates.append((event, "escalated"))
                stats["escalated_events"] += 1

        if not candidates:
            logger.info("No new or escalated disaster events in this poll cycle")
            self._last_cycle_stats = stats
            return stats

        # 4. Persist current events to PostgreSQL (keeps last-seen state fresh)
        try:
            for event in current_events:
                await pg.add_disaster_event(
                    type_=str(event.get("hazard_type", "unknown")),
                    severity=str(event.get("severity", "green")),
                    lat=float(event.get("latitude") or self.poll_latitude),
                    lon=float(event.get("longitude") or self.poll_longitude),
                    source=str(event.get("source", "unknown")),
                    raw_json={**event, "fingerprint": _event_fingerprint(event)},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist disaster events to PostgreSQL: %s", exc)
            stats["errors"] += 1

        # 5. Draft short localized warnings for new/escalated events
        drafts_created = 0
        for event, change_type in candidates:
            if drafts_created >= self.max_drafts_per_cycle:
                logger.warning(
                    "Max drafts per cycle (%d) reached; skipping remaining events",
                    self.max_drafts_per_cycle,
                )
                break

            event_id = str(event.get("id") or _event_fingerprint(event))
            for language in self.languages:
                try:
                    from AI_engine import generate_alert_draft

                    script_text = await generate_alert_draft(event, language)
                    if not script_text:
                        logger.info(
                            "Skipping green-severity event %s for language %s",
                            event_id,
                            language,
                        )
                        continue

                    alert_id = await self._store_draft(
                        event=event,
                        event_id=event_id,
                        language=language,
                        script_text=script_text,
                        change_type=change_type,
                    )
                    drafts_created += 1
                    logger.info(
                        "Drafted alert %s for event %s (%s) in %s",
                        alert_id,
                        event_id,
                        change_type,
                        language,
                    )
                except Exception as exc:  # noqa: BLE001
                    # LLM failure must never crash the scheduler loop
                    logger.error(
                        "Failed to draft alert for event %s in %s: %s",
                        event_id,
                        language,
                        exc,
                    )
                    stats["errors"] += 1

        stats["drafts_created"] = drafts_created
        self._last_cycle_stats = stats
        logger.info(
            "Alert generator cycle complete: seen=%d new=%d escalated=%d drafts=%d errors=%d",
            stats["events_seen"],
            stats["new_events"],
            stats["escalated_events"],
            stats["drafts_created"],
            stats["errors"],
        )
        return stats

    async def _store_draft(
        self,
        event: Dict[str, Any],
        event_id: str,
        language: str,
        script_text: str,
        change_type: str,
    ) -> str:
        """Store a drafted alert in MongoDB."""
        from db.mongo import get_mongo_manager

        mongo = get_mongo_manager()
        await mongo.initialize()
        event_time = event.get("event_time")
        if isinstance(event_time, str):
            try:
                event_time = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
            except Exception:
                event_time = None
        return await mongo.store_alert_draft(
            event_id=event_id,
            event_fingerprint=_event_fingerprint(event),
            language=language,
            script_text=script_text,
            severity=str(event.get("severity", "green")),
            hazard_type=str(event.get("hazard_type", "unknown")),
            title=str(event.get("title", "")),
            description=str(event.get("description", "")),
            latitude=event.get("latitude"),
            longitude=event.get("longitude"),
            source=str(event.get("source", "unknown")),
            event_time=event_time,
            raw_event={**event, "fingerprint": _event_fingerprint(event)},
            change_type=change_type,
        )


_alert_generator: Optional[AlertGenerator] = None


def get_alert_generator() -> AlertGenerator:
    """Get or create the singleton AlertGenerator."""
    global _alert_generator
    if _alert_generator is None:
        _alert_generator = AlertGenerator()
    return _alert_generator


async def close_alert_generator() -> None:
    """Stop and release the singleton AlertGenerator."""
    global _alert_generator
    if _alert_generator:
        await _alert_generator.stop()
        _alert_generator = None