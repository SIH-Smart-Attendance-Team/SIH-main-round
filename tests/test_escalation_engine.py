"""
test_escalation_engine.py — Unit tests for escalation_engine.py decision logic.

Covers all 6 escalation criteria with multilingual keyword lists,
confidence streak, distress sentiment, turn limits, and handoff summary.
"""

from escalation_engine import (
    EscalationEngine,
    EscalationDecision,
    ConversationTurn,
    ConversationState,
    Queue,
    Priority,
    EMERGENCY_KEYWORDS,
    COMPLEX_AGRI_INTENTS,
    EXPLICIT_HUMAN_PHRASES,
    LOW_CONFIDENCE_THRESHOLD,
    LOW_CONFIDENCE_STREAK_LIMIT,
    MAX_TURNS_BEFORE_ESCALATION_CHECK,
    DISTRESS_SENTIMENT_THRESHOLD,
)


def make_turn(text: str, language: str = "en", confidence: float = 0.9,
              intent: str = None, sentiment_score: float = 0.0) -> ConversationTurn:
    """Helper to create a ConversationTurn."""
    return ConversationTurn(
        text=text,
        language=language,
        confidence=confidence,
        intent=intent,
        sentiment_score=sentiment_score,
    )


def make_state(session_id: str = "test_session", channel: str = "whatsapp",
               turn_count: int = 0, low_confidence_streak: int = 0,
               explicit_human_request: bool = False, location: str = None,
               already_escalated: bool = False) -> ConversationState:
    """Helper to create a ConversationState."""
    return ConversationState(
        session_id=session_id,
        channel=channel,
        turn_count=turn_count,
        low_confidence_streak=low_confidence_streak,
        explicit_human_request=explicit_human_request,
        location=location,
        already_escalated=already_escalated,
    )


class TestEmergencyKeywordEscalation:
    """Test emergency keyword matching (Criterion 1)."""

    def test_english_help_triggers_critical(self):
        engine = EscalationEngine()
        turn = make_turn("Help me I'm drowning", language="en", confidence=0.9)
        state = make_state(turn_count=1, location="28.61,77.21")
        decision = engine.evaluate(turn, state)
        assert decision.escalate is True
        assert decision.queue == Queue.DISASTER_RESPONSE
        assert decision.priority == Priority.CRITICAL
        assert "emergency_keyword" in decision.reason

    def test_english_drowning_triggers_critical(self):
        engine = EscalationEngine()
        turn = make_turn("Someone is drowning in the flood", language="en", confidence=0.8)
        state = make_state(turn_count=1)
        decision = engine.evaluate(turn, state)
        assert decision.escalate is True
        assert decision.priority == Priority.CRITICAL

    def test_hindi_emergency_triggers_critical(self):
        engine = EscalationEngine()
        turn = make_turn("बचाओ बाढ़ में फंस गया हूँ", language="hi", confidence=0.85)
        state = make_state(turn_count=1)
        decision = engine.evaluate(turn, state)
        assert decision.escalate is True
        assert decision.priority == Priority.CRITICAL

    def test_bengali_flood_triggers_critical(self):
        engine = EscalationEngine()
        turn = make_turn("বন্যা থেকে বাঁচাতে সাহায্য করুন", language="bn", confidence=0.8)
        state = make_state(turn_count=1)
        decision = engine.evaluate(turn, state)
        assert decision.escalate is True
        assert decision.priority == Priority.CRITICAL

    def test_non_emergency_text_does_not_escalate(self):
        engine = EscalationEngine()
        turn = make_turn("What's the weather like today?", language="en", confidence=0.9)
        state = make_state(turn_count=1)
        decision = engine.evaluate(turn, state)
        assert decision.escalate is False


class TestExplicitHumanRequest:
    """Test explicit human request (Criterion 2)."""

    def test_talk_to_human_in_english(self):
        engine = EscalationEngine()
        turn = make_turn("I want to talk to a human agent", language="en", confidence=0.9)
        state = make_state(turn_count=1)
        decision = engine.evaluate(turn, state)
        assert decision.escalate is True
        assert decision.queue == Queue.GENERAL_SUPPORT
        assert decision.priority == Priority.MEDIUM

    def test_talk_to_person_in_hindi(self):
        engine = EscalationEngine()
        turn = make_turn("मुझे किसी इंसान से बात करनी है", language="hi", confidence=0.9)
        state = make_state(turn_count=1)
        decision = engine.evaluate(turn, state)
        assert decision.escalate is True
        assert decision.queue == Queue.GENERAL_SUPPORT


class TestComplexAgriIntents:
    """Test known complex/high-stakes intents (Criterion 3)."""

    def test_crop_disease_diagnosis_routes_to_agri_expert(self):
        engine = EscalationEngine()
        turn = make_turn(
            "My wheat has yellow rust what pesticide should I use",
            language="en",
            confidence=0.7,
            intent="crop_disease_diagnosis"
        )
        state = make_state(turn_count=1)
        decision = engine.evaluate(turn, state)
        assert decision.escalate is True
        assert decision.queue == Queue.AGRI_EXPERT

    def test_pesticide_dosage_routes_to_agri_expert(self):
        engine = EscalationEngine()
        turn = make_turn(
            "How much pesticide per acre for cotton",
            language="en",
            confidence=0.8,
            intent="pesticide_dosage"
        )
        state = make_state(turn_count=1)
        decision = engine.evaluate(turn, state)
        assert decision.escalate is True
        assert decision.queue == Queue.AGRI_EXPERT


class TestLowConfidenceStreak:
    """Test sustained low confidence streak (Criterion 4)."""

    def test_single_low_confidence_turn_does_not_escalate(self):
        engine = EscalationEngine()
        turn = make_turn("Something unclear", language="en", confidence=LOW_CONFIDENCE_THRESHOLD - 0.1)
        state = make_state(turn_count=1)
        decision = engine.evaluate(turn, state)
        assert decision.escalate is False

    def test_two_consecutive_low_confidence_escalates(self):
        engine = EscalationEngine()
        # First low-confidence turn
        turn1 = make_turn("Unclear 1", language="en", confidence=LOW_CONFIDENCE_THRESHOLD - 0.1)
        state = make_state(turn_count=1)
        engine.evaluate(turn1, state)
        # Second low-confidence turn should escalate
        turn2 = make_turn("Unclear 2", language="en", confidence=LOW_CONFIDENCE_THRESHOLD - 0.1)
        state.turn_count = 2
        decision = engine.evaluate(turn2, state)
        assert decision.escalate is True
        assert decision.reason == "low_confidence_streak"

    def test_confidence_recovery_resets_streak(self):
        engine = EscalationEngine()
        # Low confidence
        turn1 = make_turn("Unclear 1", language="en", confidence=LOW_CONFIDENCE_THRESHOLD - 0.1)
        state = make_state(turn_count=1)
        engine.evaluate(turn1, state)
        # High confidence resets streak
        turn2 = make_turn("Clear now", language="en", confidence=0.9)
        state.turn_count = 2
        engine.evaluate(turn2, state)
        # Another low confidence should NOT escalate (streak reset)
        turn3 = make_turn("Unclear again", language="en", confidence=LOW_CONFIDENCE_THRESHOLD - 0.1)
        state.turn_count = 3
        decision = engine.evaluate(turn3, state)
        assert decision.escalate is False


class TestDistressSentiment:
    """Test distress sentiment (Criterion 5)."""

    def test_distress_sentiment_escalates_after_2_turns(self):
        engine = EscalationEngine()
        # Turn 1: distress (no emergency keywords)
        turn1 = make_turn("I'm so anxious and worried about the storm", language="en", confidence=0.8, sentiment_score=-0.6)
        state = make_state(turn_count=1)
        engine.evaluate(turn1, state)
        # Turn 2: more distress (no emergency keywords)
        turn2 = make_turn("This is overwhelming and frightening", language="en", confidence=0.8, sentiment_score=-0.6)
        state.turn_count = 2
        decision = engine.evaluate(turn2, state)
        assert decision.escalate is True
        assert decision.priority == Priority.HIGH

    def test_distress_sentiment_not_enough_turns(self):
        engine = EscalationEngine()
        turn = make_turn("I'm worried about the storm", language="en", confidence=0.8, sentiment_score=-0.6)
        state = make_state(turn_count=1)
        decision = engine.evaluate(turn, state)
        # Single turn with distress should not escalate yet
        assert decision.escalate is False


class TestTurnLimitEscalation:
    """Test long unresolved threads (Criterion 6)."""

    def test_long_conversation_escalates_with_low_priority(self):
        engine = EscalationEngine()
        state = make_state()
        for i in range(MAX_TURNS_BEFORE_ESCALATION_CHECK):
            turn = make_turn(f"Question {i}", language="en", confidence=0.9)
            state.turn_count = i + 1
            engine.evaluate(turn, state)
        # Next turn should escalate
        turn = make_turn("Another question", language="en", confidence=0.9)
        state.turn_count = MAX_TURNS_BEFORE_ESCALATION_CHECK + 1
        decision = engine.evaluate(turn, state)
        assert decision.escalate is True
        assert decision.priority == Priority.LOW


class TestAlreadyEscalated:
    """Test that already-escalated sessions stay escalated."""

    def test_already_escalated_stays_escalated(self):
        engine = EscalationEngine()
        # First escalate
        turn1 = make_turn("Help me I'm drowning", language="en", confidence=0.9)
        state = make_state(turn_count=1)
        engine.evaluate(turn1, state)
        # Subsequent turns should remain escalated
        turn2 = make_turn("Any other question", language="en", confidence=0.9)
        state.turn_count = 2
        state.already_escalated = True  # This is set by the caller after first escalation
        decision = engine.evaluate(turn2, state)
        assert decision.escalate is True


class TestHandoffSummary:
    """Test handoff summary generation."""

    def test_summary_contains_channel_and_text(self):
        engine = EscalationEngine()
        turn = make_turn("Help me I'm drowning", language="en", confidence=0.9)
        state = make_state(turn_count=1, channel="whatsapp")
        decision = engine.evaluate(turn, state)
        assert "whatsapp" in decision.handoff_summary.lower()
        assert "drowning" in decision.handoff_summary.lower()

    def test_summary_includes_location(self):
        engine = EscalationEngine()
        turn = make_turn("Help me", language="en", confidence=0.9)
        state = make_state(turn_count=1, location="28.61,77.21")
        decision = engine.evaluate(turn, state)
        assert "28.61" in decision.handoff_summary
        assert "77.21" in decision.handoff_summary