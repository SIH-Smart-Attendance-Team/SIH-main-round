"""Unit tests for escalation_engine.py — pure function logic, no external deps."""

import pytest

from escalation_engine import (
    ConversationState,
    ConversationTurn,
    EscalationEngine,
    Priority,
    Queue,
)


@pytest.fixture
def engine():
    return EscalationEngine()


@pytest.fixture
def base_state():
    return ConversationState(
        session_id="test-session-1",
        channel="voice",
        turn_count=1,
    )


@pytest.fixture
def base_turn():
    return ConversationTurn(
        text="What is the weather today?",
        language="en",
        confidence=0.9,
        intent=None,
        sentiment_score=0.1,
    )


# ---------------------------------------------------------------------------
# 1. Emergency keyword escalation
# ---------------------------------------------------------------------------

class TestEmergencyKeywordEscalation:
    def test_english_help_triggers_critical(self, engine, base_state):
        turn = ConversationTurn(text="I need help now!", language="en", confidence=0.9)
        decision = engine.evaluate(turn, base_state)
        assert decision.escalate is True
        assert decision.priority == Priority.CRITICAL
        assert decision.queue == Queue.DISASTER_RESPONSE
        assert decision.reason == "emergency_keyword_match"

    def test_english_drowning_triggers_critical(self, engine, base_state):
        turn = ConversationTurn(text="Someone is drowning!", language="en", confidence=0.9)
        decision = engine.evaluate(turn, base_state)
        assert decision.escalate is True
        assert decision.priority == Priority.CRITICAL
        assert decision.queue == Queue.DISASTER_RESPONSE

    def test_hindi_emergency_triggers_critical(self, engine, base_state):
        turn = ConversationTurn(text="मदद की ज़रूरत है", language="hi", confidence=0.9)
        decision = engine.evaluate(turn, base_state)
        assert decision.escalate is True
        assert decision.priority == Priority.CRITICAL
        assert decision.queue == Queue.DISASTER_RESPONSE

    def test_bengali_flood_triggers_critical(self, engine, base_state):
        turn = ConversationTurn(text="বন্যা আসছে গ্রীষ্মে", language="bn", confidence=0.9)
        decision = engine.evaluate(turn, base_state)
        assert decision.escalate is True
        assert decision.priority == Priority.CRITICAL
        assert decision.queue == Queue.DISASTER_RESPONSE

    def test_non_emergency_text_does_not_escalate(self, engine, base_state):
        turn = ConversationTurn(text="What is the weather forecast?", language="en", confidence=0.9)
        decision = engine.evaluate(turn, base_state)
        assert decision.escalate is False
        assert decision.reason == "none"


# ---------------------------------------------------------------------------
# 2. Explicit human request escalation
# ---------------------------------------------------------------------------

class TestExplicitHumanRequest:
    def test_talk_to_human_in_english(self, engine, base_state):
        turn = ConversationTurn(
            text="I want to talk to a human agent please",
            language="en", confidence=0.9
        )
        decision = engine.evaluate(turn, base_state)
        assert decision.escalate is True
        assert decision.priority == Priority.MEDIUM
        assert decision.queue == Queue.GENERAL_SUPPORT
        assert decision.reason == "explicit_human_request"

    def test_talk_to_person_in_hindi(self, engine, base_state):
        turn = ConversationTurn(text="किसी इंसान से बात करना है", language="hi", confidence=0.9)
        decision = engine.evaluate(turn, base_state)
        assert decision.escalate is True
        assert decision.priority == Priority.MEDIUM
        assert decision.queue == Queue.GENERAL_SUPPORT


# ---------------------------------------------------------------------------
# 3. Complex agri intents
# ---------------------------------------------------------------------------

class TestComplexAgriIntents:
    def test_crop_disease_diagnosis_routes_to_agri_expert(self, engine, base_state):
        turn = ConversationTurn(
            text="My rice plants have yellow spots on leaves",
            language="en", confidence=0.9,
            intent="crop_disease_diagnosis"
        )
        decision = engine.evaluate(turn, base_state)
        assert decision.escalate is True
        assert decision.queue == Queue.AGRI_EXPERT
        assert "high_stakes_intent" in decision.reason

    def test_pesticide_dosage_routes_to_agri_expert(self, engine, base_state):
        turn = ConversationTurn(
            text="How much pesticide should I use?",
            language="en", confidence=0.9,
            intent="pesticide_dosage"
        )
        decision = engine.evaluate(turn, base_state)
        assert decision.escalate is True
        assert decision.queue == Queue.AGRI_EXPERT


# ---------------------------------------------------------------------------
# 4. Low confidence streak escalation
# ---------------------------------------------------------------------------

class TestLowConfidenceStreak:
    def test_single_low_confidence_turn_does_not_escalate(self, engine):
        state = ConversationState(session_id="s1", channel="voice")
        turn = ConversationTurn(text="something", language="en", confidence=0.3)
        decision = engine.evaluate(turn, state)
        assert decision.escalate is False

    def test_two_consecutive_low_confidence_escalates(self, engine):
        state = ConversationState(session_id="s1", channel="voice")
        turn1 = ConversationTurn(text="first", language="en", confidence=0.3)
        turn2 = ConversationTurn(text="second", language="en", confidence=0.3)

        d1 = engine.evaluate(turn1, state)
        assert d1.escalate is False  # first low-confidence turn

        d2 = engine.evaluate(turn2, state)
        assert d2.escalate is True
        assert d2.reason == "low_confidence_streak"
        assert d2.priority == Priority.MEDIUM

    def test_confidence_recovery_resets_streak(self, engine):
        state = ConversationState(session_id="s1", channel="voice")
        turn1 = ConversationTurn(text="first", language="en", confidence=0.3)
        turn2 = ConversationTurn(text="second", language="en", confidence=0.8)
        turn3 = ConversationTurn(text="third", language="en", confidence=0.3)

        engine.evaluate(turn1, state)
        assert state.low_confidence_streak == 1

        engine.evaluate(turn2, state)
        assert state.low_confidence_streak == 0  # reset

        d3 = engine.evaluate(turn3, state)
        assert d3.escalate is False  # only 1 consecutive low-confidence now


# ---------------------------------------------------------------------------
# 5. Distress sentiment
# ---------------------------------------------------------------------------

class TestDistressSentiment:
    def test_distress_sentiment_escalates_after_2_turns(self, engine):
        state = ConversationState(session_id="s1", channel="voice", turn_count=3)
        turn = ConversationTurn(
            text="I'm so frustrated",
            language="en", confidence=0.8,
            sentiment_score=-0.7
        )
        decision = engine.evaluate(turn, state)
        assert decision.escalate is True
        assert decision.reason == "distress_sentiment"
        assert decision.priority == Priority.HIGH

    def test_distress_sentiment_not_enough_turns(self, engine):
        state = ConversationState(session_id="s1", channel="voice", turn_count=1)
        turn = ConversationTurn(
            text="I'm upset",
            language="en", confidence=0.8,
            sentiment_score=-0.6
        )
        decision = engine.evaluate(turn, state)
        assert decision.escalate is False


# ---------------------------------------------------------------------------
# 6. Turn limit escalation
# ---------------------------------------------------------------------------

class TestTurnLimitEscalation:
    def test_long_conversation_escalates_with_low_priority(self, engine):
        state = ConversationState(
            session_id="s1", channel="voice",
            turn_count=7  # exceeds MAX_TURNS_BEFORE_ESCALATION_CHECK (6)
        )
        turn = ConversationTurn(
            text="I have a general question",  # avoids triggering emergency keywords
            language="en", confidence=0.9
        )
        decision = engine.evaluate(turn, state)
        assert decision.escalate is True
        assert decision.priority == Priority.LOW
        assert decision.reason == "turn_limit_exceeded"


# ---------------------------------------------------------------------------
# 7. Already escalated
# ---------------------------------------------------------------------------

class TestAlreadyEscalated:
    def test_already_escalated_stays_escalated(self, engine, base_state):
        base_state.already_escalated = True
        turn = ConversationTurn(text="follow up", language="en", confidence=0.9)
        decision = engine.evaluate(turn, base_state)
        assert decision.escalate is True
        assert decision.reason == "conversation_already_escalated"


# ---------------------------------------------------------------------------
# 8. Handoff summary
# ---------------------------------------------------------------------------

class TestHandoffSummary:
    def test_summary_contains_channel_and_text(self, engine, base_state):
        turn = ConversationTurn(text="I need help with crops", language="en", confidence=0.9)
        decision = engine.evaluate(turn, base_state)
        assert "Channel: voice" in decision.handoff_summary
        assert "I need help with crops" in decision.handoff_summary
        assert "Turns so far: 1" in decision.handoff_summary

    def test_summary_includes_location(self, engine, base_state):
        base_state.location = "Delhi"
        turn = ConversationTurn(text="Need help", language="en", confidence=0.9)
        decision = engine.evaluate(turn, base_state)
        assert "Location: Delhi" in decision.handoff_summary
