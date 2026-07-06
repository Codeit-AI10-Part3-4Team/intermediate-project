# tests/api/test_config.py
"""Settings 계약 테스트 — 환경 변수(APP_*) 통로가 실제로 동작하는지 검증."""

from api.config import Settings


def test_defaults():
    s = Settings(_env_file=None)

    assert s.use_mock is True
    assert s.chroma_dir == "/data/vector_db/vector_db_v9"
    assert s.log_level == "INFO"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("APP_USE_MOCK", "false")
    monkeypatch.setenv("APP_CHROMA_DIR", "/tmp/other_db")

    s = Settings(_env_file=None)

    assert s.use_mock is False
    assert s.chroma_dir == "/tmp/other_db"
