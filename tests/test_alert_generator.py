"""
test_alert_generator.py — Unit tests for alert_generator.py pure functions.

Tests _event_fingerprint, _event_key, _severity_escalated, and diff logic
without requiring database connections.
"""

import pytest
from alert_generator import (
    _event_fingerprint,
    _event_key,
    _severity_escalated,
    SEVERITY_ORDER,
)


class TestEventFingerprint:
    """Test _event_fingerprint stability and uniqueness."""

    def test_same_event_produces_same_fingerprint(self):
        event = {
            "source": "GDACS",
            "hazard_type": "cyclone",
            "event_time": "2024-01-01T12:00:00Z",
            "title": "Cyclone Warning",
            "latitude": 19.07,
            "longitude": 88.36,
        }
        fp1 = _event_fingerprint(event)
        fp2 = _event_fingerprint(event)
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA256 hex

    def test_different_source_changes_fingerprint(self):
        e1 = {"source": "GDACS", "hazard_type": "cyclone", "event_time": "2024-01-01T12:00:00Z", "title": "Test", "latitude": 19.07, "longitude": 88.36}
        e2 = {"source": "USGS", "hazard_type": "cyclone", "event_time": "2024-01-01T12:00:00Z", "title": "Test", "latitude": 19.07, "longitude": 88.36}
        assert _event_fingerprint(e1) != _event_fingerprint(e2)

    def test_different_hazard_type_changes_fingerprint(self):
        e1 = {"source": "GDACS", "hazard_type": "cyclone", "event_time": "2024-01-01T12:00:00Z", "title": "Test", "latitude": 19.07, "longitude": 88.36}
        e2 = {"source": "GDACS", "hazard_type": "flood", "event_time": "2024-01-01T12:00:00Z", "title": "Test", "latitude": 19.07, "longitude": 88.36}
        assert _event_fingerprint(e1) != _event_fingerprint(e2)

    def test_different_coordinates_change_fingerprint(self):
        e1 = {"source": "GDACS", "hazard_type": "cyclone", "event_time": "2024-01-01T12:00:00Z", "title": "Test", "latitude": 19.07, "longitude": 88.36}
        e2 = {"source": "GDACS", "hazard_type": "cyclone", "event_time": "2024-01-01T12:00:00Z", "title": "Test", "latitude": 28.61, "longitude": 77.21}
        assert _event_fingerprint(e1) != _event_fingerprint(e2)

    def test_missing_fields_handled_gracefully(self):
        event = {"source": "GDACS"}  # minimal
        fp = _event_fingerprint(event)
        assert len(fp) == 64


class TestEventKey:
    """Test _event_key tuple for diffing."""

    def test_returns_tuple_of_source_hazard_fingerprint(self):
        event = {
            "source": "GDACS",
            "hazard_type": "cyclone",
            "event_time": "2024-01-01T12:00:00Z",
            "title": "Test",
            "latitude": 19.07,
            "longitude": 88.36,
        }
        key = _event_key(event)
        assert isinstance(key, tuple)
        assert len(key) == 3
        assert key[0] == "GDACS"
        assert key[1] == "cyclone"
        assert len(key[2]) == 64


class TestSeverityEscalated:
    """Test _severity_escalated per IMD 4-level convention."""

    @pytest.mark.parametrize("old_sev,new_sev,expected", [
        ("green", "yellow", True),
        ("green", "orange", True),
        ("green", "red", True),
        ("yellow", "orange", True),
        ("yellow", "red", True),
        ("orange", "red", True),
        ("yellow", "green", False),
        ("orange", "yellow", False),
        ("red", "orange", False),
        ("green", "green", False),
        ("orange", "orange", False),
        ("red", "red", False),
        # Case insensitive
        ("GREEN", "RED", True),
        ("Green", "Red", True),
        # Unknown severities default to level 0
        ("unknown", "red", True),
        ("green", "unknown", False),
    ])
    def test_severity_escalation_matrix(self, old_sev, new_sev, expected):
        assert _severity_escalated(old_sev, new_sev) == expected


class TestSeverityOrder:
    """Test SEVERITY_ORDER constant."""

    def test_order_values(self):
        assert SEVERITY_ORDER["green"] == 0
        assert SEVERITY_ORDER["yellow"] == 1
        assert SEVERITY_ORDER["orange"] == 2
        assert SEVERITY_ORDER["red"] == 3


class TestDiffLogic:
    """Test the diff logic: new events + severity escalations."""

    def test_new_event_detected(self):
        """A fingerprint not in last_seen_map should be 'new'."""
        from alert_generator import _event_fingerprint, _event_key, _severity_escalated, SEVERITY_ORDER

        current_events = [{
            "source": "GDACS",
            "hazard_type": "cyclone",
            "event_time": "2024-01-01T12:00:00Z",
            "title": "Cyclone Warning",
            "latitude": 19.07,
            "longitude": 88.36,
            "severity": "orange",
        }]

        # Empty last_seen_map
        last_seen_map = {}

        candidates = []
        seen_fingerprints = set()
        for event in current_events:
            fp = _event_fingerprint(event)
            if fp in seen_fingerprints:
                continue
            seen_fingerprints.add(fp)
            key = _event_key(event)
            previous = last_seen_map.get(key)
            if previous is None:
                candidates.append((event, "new"))
            elif _severity_escalated(previous.severity, event.get("severity", "")):
                candidates.append((event, "escalated"))

        assert len(candidates) == 1
        assert candidates[0][1] == "new"

    def test_severity_escalation_detected(self):
        """Higher severity for same fingerprint should be 'escalated'."""
        from alert_generator import _event_fingerprint, _event_key, _severity_escalated, SEVERITY_ORDER

        current_events = [{
            "source": "GDACS",
            "hazard_type": "cyclone",
            "event_time": "2024-01-01T12:00:00Z",
            "title": "Cyclone Warning",
            "latitude": 19.07,
            "longitude": 88.36,
            "severity": "red",  # Escalated from orange
        }]

        # Previous event with lower severity
        class MockEvent:
            severity = "orange"

        fp = _event_fingerprint(current_events[0])
        key = _event_key(current_events[0])
        last_seen_map = {key: MockEvent()}

        candidates = []
        seen_fingerprints = set()
        for event in current_events:
            fp = _event_fingerprint(event)
            if fp in seen_fingerprints:
                continue
            seen_fingerprints.add(fp)
            key = _event_key(event)
            previous = last_seen_map.get(key)
            if previous is None:
                candidates.append((event, "new"))
            elif _severity_escalated(previous.severity, event.get("severity", "")):
                candidates.append((event, "escalated"))

        assert len(candidates) == 1
        assert candidates[0][1] == "escalated"

    def test_same_severity_not_escalated(self):
        """Same severity should not produce a candidate."""
        from alert_generator import _event_fingerprint, _event_key, _severity_escalated, SEVERITY_ORDER

        current_events = [{
            "source": "GDACS",
            "hazard_type": "cyclone",
            "event_time": "2024-01-01T12:00:00Z",
            "title": "Cyclone Warning",
            "latitude": 19.07,
            "longitude": 88.36,
            "severity": "orange",
        }]

        class MockEvent:
            severity = "orange"

        fp = _event_fingerprint(current_events[0])
        key = _event_key(current_events[0])
        last_seen_map = {key: MockEvent()}

        candidates = []
        seen_fingerprints = set()
        for event in current_events:
            fp = _event_fingerprint(event)
            if fp in seen_fingerprints:
                continue
            seen_fingerprints.add(fp)
            key = _event_key(event)
            previous = last_seen_map.get(key)
            if previous is None:
                candidates.append((event, "new"))
            elif _severity_escalated(previous.severity, event.get("severity", "")):
                candidates.append((event, "escalated"))

        assert len(candidates) == 0

    def test_duplicate_fingerprints_deduplicated(self):
        """Duplicate fingerprints in current_events should be deduplicated."""
        from alert_generator import _event_fingerprint, _event_key, _severity_escalated, SEVERITY_ORDER

        # Two events with same fingerprint (same source/type/time/title/coords)
        current_events = [
            {"source": "GDACS", "hazard_type": "cyclone", "event_time": "2024-01-01T12:00:00Z", "title": "Cyclone", "latitude": 19.07, "longitude": 88.36, "severity": "orange"},
            {"source": "GDACS", "hazard_type": "cyclone", "event_time": "2024-01-01T12:00:00Z", "title": "Cyclone", "latitude": 19.07, "longitude": 88.36, "severity": "orange"},
        ]

        seen_fingerprints = set()
        for event in current_events:
            fp = _event_fingerprint(event)
            if fp in seen_fingerprints:
                continue
            seen_fingerprints.add(fp)

        assert len(seen_fingerprints) == 1