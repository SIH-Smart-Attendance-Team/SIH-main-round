"""
core_agent.py

The single place where "what should the bot say / do next" is decided.
Both the voice adapter and the WhatsApp adapter call CoreAgent.handle_turn()
so escalation criteria and response logic never diverge between channels.

This assumes your existing offline-aware WeatherAgent and disaster-map
data layer are importable as shown below — adjust import paths to match
your actual module layout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from backend.app.ai_engine import generate_weather_advisory
from backend.app.escalation_engine import (
    EscalationEngine,
    ConversationTurn,
    ConversationState,
    EscalationDecision,
)

try:
    import redis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False

# --- Existing components (already built per the prompt) -------------------
# from weather_agent import WeatherAgent          # offline-aware weather agent
# from disaster_map import DisasterDataLayer      # Leaflet map's backing data

REDIS_URL = "redis://localhost:6379/0"
SESSION_TTL_SECONDS = 60 * 60 * 2  # 2 hours


@dataclass
class AgentReply:
    text: str
    language: str
    escalation: EscalationDecision


class SessionStore:
    """Thin Redis wrapper for ConversationState persistence."""

    def __init__(self, url: str = REDIS_URL):
        self._url = url
        self._r = None
        self._memory: dict[str, str] = {}
        if _REDIS_AVAILABLE:
            try:
                self._r = redis.Redis.from_url(url, decode_responses=True)
                self._r.ping()
            except Exception:
                self._r = None

    def _key(self, channel: str, session_id: str) -> str:
        return f"weathergpt:session:{channel}:{session_id}"

    def load(self, channel: str, session_id: str) -> ConversationState:
        if self._r is not None:
            raw = self._r.get(self._key(channel, session_id))
            if raw is not None:
                data = json.loads(raw)
                return ConversationState(**data)
        key = self._key(channel, session_id)
        if key in self._memory:
            data = json.loads(self._memory[key])
            return ConversationState(**data)
        return ConversationState(session_id=session_id, channel=channel)

    def save(self, state: ConversationState) -> None:
        payload = json.dumps(state.__dict__)
        if self._r is not None:
            try:
                self._r.set(self._key(state.channel, state.session_id), payload, ex=SESSION_TTL_SECONDS)
                return
            except Exception:
                pass
        self._memory[self._key(state.channel, state.session_id)] = payload


class CoreAgent:
    def __init__(self):
        self.escalation_engine = EscalationEngine()
        self.sessions = SessionStore()
        # self.weather_agent = WeatherAgent()
        # self.disaster_layer = DisasterDataLayer()

    async def handle_turn(
        self,
        session_id: str,
        channel: str,
        user_text: str,
        language: str = "en",
        location: Optional[str] = None,
    ) -> AgentReply:
        state = self.sessions.load(channel, session_id)
        if location:
            state.location = location

        # --- 1. Run NLU / intent classification -----------------------
        intent, confidence, sentiment = self._classify(user_text, language)

        turn = ConversationTurn(
            text=user_text,
            language=language,
            confidence=confidence,
            intent=intent,
            sentiment_score=sentiment,
        )

        # --- 2. Evaluate escalation BEFORE generating a full answer -----
        decision = self.escalation_engine.evaluate(turn, state)

        state.turn_count += 1

        if decision.escalate:
            state.already_escalated = True
            self.sessions.save(state)
            reply_text = self._escalation_message(language)
            return AgentReply(text=reply_text, language=language, escalation=decision)

        # --- 3. Otherwise, generate the normal answer -------------------
        reply_text = await self._generate_answer(user_text, intent, language, state)
        self.sessions.save(state)

        return AgentReply(
            text=reply_text,
            language=language,
            escalation=decision,  # escalate=False
        )

    # -- Replace these with your real NLU / weather-agent calls ----------

    def _classify(self, text: str, language: str) -> tuple[str, float, float]:
        """
        Plug in your actual intent classifier / LLM call here. Should return
        (intent, confidence 0-1, sentiment -1 to 1).
        """
        # placeholder
        return ("general_weather_query", 0.8, 0.1)

    async def _generate_answer(self, text: str, intent: str, language: str, state: ConversationState) -> str:
        # Default coordinates (e.g. New Delhi) or parse from state.location
        lat, lon = 28.61, 77.21
        result = await generate_weather_advisory(
            user_text=text,
            source_lang=language,
            lat=lat,
            lon=lon,
            target_lang=language,
        )
        return result.get("native_advisory") or result.get("english_advisory")

    def _escalation_message(self, language: str) -> str:
        messages = {
            "en": "I'm connecting you to a human expert now. Please stay on the line.",
            "hi": "मैं आपको अभी एक विशेषज्ञ से जोड़ रहा हूँ। कृपया लाइन पर बने रहें।",
        }
        return messages.get(language, messages["en"])

