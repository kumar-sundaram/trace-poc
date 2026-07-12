"""Settings load from config/settings.yaml and are overridable via TRACE_* env vars (NFR-6)."""

from api.config import Settings


def test_defaults_load_from_yaml():
    s = Settings()
    assert s.signal.fanout_min_parties == 3
    assert s.signal.fanout_window_days == 14
    assert s.degree_guard_threshold == 200
    assert s.resolve.no_match_threshold < s.resolve.auto_match_threshold
    assert s.resolve.addressless_confidence_cap < s.resolve.auto_match_threshold
    assert s.embedding.dimension in (256, 512, 1024)  # Titan v2 supported sizes


def test_role_vocabulary_covers_test_data_roles():
    s = Settings()
    for role in (
        "BORROWER",
        "KEY_BORROWER_PRINCIPAL",
        "SPONSOR",
        "GUARANTOR",
        "PROPERTY_MANAGER",
    ):
        assert role in s.role_vocabulary


def test_env_override(monkeypatch):
    monkeypatch.setenv("TRACE_DEGREE_GUARD_THRESHOLD", "500")
    monkeypatch.setenv("TRACE_SIGNAL__FANOUT_MIN_PARTIES", "5")
    s = Settings()
    assert s.degree_guard_threshold == 500
    assert s.signal.fanout_min_parties == 5


def test_stream_paths():
    s = Settings()
    assert s.streams.resolution_outcome_path.name == "resolution-outcome.jsonl"
    assert s.streams.signal_path.name == "signal.jsonl"
