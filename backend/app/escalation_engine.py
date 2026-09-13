"""
escalation_engine.py

Hybrid rule + confidence-score escalation engine shared by the voice
and WhatsApp channels. This is intentionally channel-agnostic: it takes
a normalized ConversationTurn / ConversationState and returns an
EscalationDecision. Neither Twilio nor WhatsApp objects should ever
appear in this file.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"  # e.g. life-safety, active disaster


class Queue(str, Enum):
    AGRI_EXPERT = "agriculture_expert"
    DISASTER_RESPONSE = "disaster_response_officer"
    GENERAL_SUPPORT = "general_support"


@dataclass
class ConversationTurn:
    text: str                      # normalized transcript / message text
    language: str                  # e.g. "hi", "bn", "ta", "en"
    confidence: float              # NLU/ASR confidence 0.0-1.0 for this turn
    intent: Optional[str] = None   # e.g. "crop_disease", "cyclone_warning"
    sentiment_score: float = 0.0   # -1 (distressed/angry) to +1 (calm/positive)


@dataclass
class ConversationState:
    session_id: str
    channel: str                   # "voice" | "whatsapp"
    turn_count: int = 0
    low_confidence_streak: int = 0
    explicit_human_request: bool = False
    location: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    already_escalated: bool = False


@dataclass
class EscalationDecision:
    escalate: bool
    priority: Priority
    queue: Queue
    reason: str
    handoff_summary: str  # short context summary to whisper/forward to the human agent


# ---------------------------------------------------------------------------
# Trigger definitions
# ---------------------------------------------------------------------------

# Multilingual emergency / life-safety keyword sets. Extend per launch language.
# Keep these lists reviewed by native speakers + domain experts — false negatives
# here are the highest-severity failure mode in this whole system.
EMERGENCY_KEYWORDS = {
    "en": [
        r"\bhelp\b", r"\bdrowning\b", r"\btrapped\b", r"\bcollaps(e|ed|ing)\b",
        r"\bflood(ing)?\b.*\b(house|home|village)\b", r"\bcyclone\b.*\bnow\b",
        r"\bemergency\b", r"\bdying\b", r"\bfire\b", r"\binjured\b",
    ],
    "hi": [
        r"मदद", r"डूब", r"फंस", r"आपातकाल", r"बाढ़", r"तूफ़ान", r"घायल", r"आग",
    ],
    "bn": [
        r"সাহায্য", r"ডুবে", r"বন্যা", r"জরুরি", r"আগুন", r"আহত",
    ],
    "ta": [
        r"உதவி", r"மூழ்கு", r"வெள்ளம்", r"அவசரம்", r"தீ",
    ],
}

# High-complexity agricultural/technical topics we don't want a general model
# guessing on — route to a human agri-expert instead.
COMPLEX_AGRI_INTENTS = {
    "crop_disease_diagnosis",
    "pesticide_dosage",
    "livestock_illness",
    "soil_toxicity",
    "crop_insurance_claim_dispute",
}

EXPLICIT_HUMAN_PHRASES = {
    "en": [r"\btalk to (a )?(human|person|agent|officer)\b", r"\breal person\b"],
    "hi": [r"किसी इंसान से बात", r"अधिकारी से बात"],
}

LOW_CONFIDENCE_THRESHOLD = 0.55
LOW_CONFIDENCE_STREAK_LIMIT = 2   # 2 consecutive low-confidence turns -> escalate
MAX_TURNS_BEFORE_ESCALATION_CHECK = 6  # long unresolved threads get flagged
DISTRESS_SENTIMENT_THRESHOLD = -0.5


def _matches_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class EscalationEngine:
    """
    Stateless evaluator. Call `evaluate()` on every turn; it inspects the
    current turn plus the running ConversationState and returns a decision.
    The caller (voice or WhatsApp adapter) is responsible for persisting
    ConversationState back to Redis between turns.
    """

    def evaluate(self, turn: ConversationTurn, state: ConversationState) -> EscalationDecision:
        if state.already_escalated:
            return EscalationDecision(
                escalate=True,
                priority=Priority.HIGH,
                queue=Queue.GENERAL_SUPPORT,
                reason="conversation_already_escalated",
                handoff_summary=self._summarize(turn, state),
            )

        # 1. Life-safety / emergency keywords -> immediate critical escalation
        keywords = EMERGENCY_KEYWORDS.get(turn.language, []) + EMERGENCY_KEYWORDS["en"]
        if _matches_any(keywords, turn.text):
            return EscalationDecision(
                escalate=True,
                priority=Priority.CRITICAL,
                queue=Queue.DISASTER_RESPONSE,
                reason="emergency_keyword_match",
                handoff_summary=self._summarize(turn, state),
            )

        # 2. Explicit request for a human
        explicit_patterns = EXPLICIT_HUMAN_PHRASES.get(turn.language, []) + EXPLICIT_HUMAN_PHRASES["en"]
        if _matches_any(explicit_patterns, turn.text):
            return EscalationDecision(
                escalate=True,
                priority=Priority.MEDIUM,
                queue=Queue.GENERAL_SUPPORT,
                reason="explicit_human_request",
                handoff_summary=self._summarize(turn, state),
            )

        # 3. Known complex/high-stakes intents -> route to a domain expert,
        #    not because the model failed, but because the topic warrants it.
        if turn.intent in COMPLEX_AGRI_INTENTS:
            return EscalationDecision(
                escalate=True,
                priority=Priority.MEDIUM,
                queue=Queue.AGRI_EXPERT,
                reason=f"high_stakes_intent:{turn.intent}",
                handoff_summary=self._summarize(turn, state),
            )

        # 4. Sustained low model confidence -> the bot is guessing, stop guessing
        if turn.confidence < LOW_CONFIDENCE_THRESHOLD:
            state.low_confidence_streak += 1
        else:
            state.low_confidence_streak = 0

        if state.low_confidence_streak >= LOW_CONFIDENCE_STREAK_LIMIT:
            return EscalationDecision(
                escalate=True,
                priority=Priority.MEDIUM,
                queue=Queue.GENERAL_SUPPORT,
                reason="low_confidence_streak",
                handoff_summary=self._summarize(turn, state),
            )

        # 5. Distress sentiment (frustration/panic) sustained past a couple of turns
        if turn.sentiment_score <= DISTRESS_SENTIMENT_THRESHOLD and state.turn_count >= 2:
            return EscalationDecision(
                escalate=True,
                priority=Priority.HIGH,
                queue=Queue.GENERAL_SUPPORT,
                reason="distress_sentiment",
                handoff_summary=self._summarize(turn, state),
            )

        # 6. Conversation dragging on too long without resolution
        if state.turn_count >= MAX_TURNS_BEFORE_ESCALATION_CHECK:
            return EscalationDecision(
                escalate=True,
                priority=Priority.LOW,
                queue=Queue.GENERAL_SUPPORT,
                reason="turn_limit_exceeded",
                handoff_summary=self._summarize(turn, state),
            )

        # No escalation triggered
        return EscalationDecision(
            escalate=False,
            priority=Priority.LOW,
            queue=Queue.GENERAL_SUPPORT,
            reason="none",
            handoff_summary="",
        )

    @staticmethod
    def _summarize(turn: ConversationTurn, state: ConversationState) -> str:
        """Short context string to whisper to a voice agent or paste into the
        WhatsApp agent dashboard. Keep this under ~2 sentences — it's read
        aloud in the voice case."""
        loc = f" Location: {state.location}." if state.location else ""
        return (
            f"Channel: {state.channel}. Turns so far: {state.turn_count}. "
            f"Last message ({turn.language}): \"{turn.text[:160]}\".{loc}"
        )

