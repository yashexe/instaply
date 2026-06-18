"""
Instaply configuration — loads from .env via Pydantic Settings.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    database_path: str = "data/instaply.db"

    # --- Server ---
    host: str = "127.0.0.1"
    port: int = 8000

    # --- LLM Provider ---
    llm_provider: str = "openai"  # openai | anthropic | gemini

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Google Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # --- Email (SMTP) ---
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    alert_to_email: str = ""

    # --- Scheduler ---
    high_priority_poll_interval: int = 300  # 5 min
    normal_poll_interval: int = 1800  # 30 min
    health_check_interval: int = 1800  # 30 min
    source_failure_escalation_threshold: int = 3  # consecutive failures before degraded + escalation

    # --- Matching ---
    default_alert_threshold: int = 85
    digest_threshold: int = 65
    # Minimum data confidence (0-100) a match needs for each decision tier;
    # a high score built on mostly-unknown data should not page anyone.
    alert_min_confidence: int = 50
    digest_min_confidence: int = 30
    baseline_first_poll: bool = True

    # --- Embeddings (local semantic matching) ---
    embeddings_enabled: bool = True
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"

    # --- LLM budget (protects daily quota, e.g. Gemini free tier ~250/day) ---
    # Hard daily cap across all LLM calls; when reached, every caller uses
    # its non-LLM fallback until the next UTC day.
    llm_daily_budget: int = 200
    # Proactive client-side request spacing: minimum seconds between LLM API
    # calls, to stay under the provider's per-minute rate limit (RPM). The
    # daily budget/cooldown only react after a 429; this prevents tripping it
    # in tight loops. Gemini free tier is ~10 RPM => ~6s; 0 disables spacing.
    llm_min_request_interval_seconds: float = 6.5
    # Slice of the daily budget the match judge may consume, so judging
    # can never starve extraction or alert explanations.
    llm_judge_daily_budget: int = 30
    # Max matches judged per run, and how often the scheduler runs the judge.
    judge_top_k: int = 25
    judge_interval: int = 3600
    # Give up on a match after this many failed judge attempts.
    judge_max_attempts: int = 2

    # --- Source discovery ---
    discovery_enabled: bool = True
    discovery_interval: int = 86400  # how often the discovery job runs (seconds)
    # Politeness limits for probing ATS endpoints for guessed slugs.
    discovery_max_probes_per_run: int = 60
    discovery_probe_delay_seconds: float = 1.0
    # A found board must show at least this many titles matching the user's
    # target roles to be suggested; otherwise it is parked as 'irrelevant'.
    discovery_min_matching_titles: int = 1
    # Stop suggesting when this many suggestions await review.
    discovery_max_suggestions_pending: int = 25
    # not_found/irrelevant companies become probeable again after this long.
    discovery_recheck_days: int = 14
    # Max companies accepted from the LLM candidate provider per run.
    discovery_max_llm_candidates: int = 25
    # Reserved slice of the daily LLM budget for discovery.
    llm_discovery_daily_budget: int = 5

    # --- Digest delivery ---
    digest_interval: int = 86400  # how often the digest job runs (seconds)
    digest_lookback_days: int = 7  # only include matches first seen this recently
    digest_max_items: int = 20  # jobs listed per digest email; the rest are counted

    # --- Logging ---
    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return Path(self.database_path)

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_username and self.smtp_password and self.alert_to_email)

    @property
    def llm_configured(self) -> bool:
        provider = self.llm_provider
        if provider == "openai":
            return bool(self.openai_api_key)
        elif provider == "anthropic":
            return bool(self.anthropic_api_key)
        elif provider == "gemini":
            return bool(self.gemini_api_key)
        return False


settings = Settings()
