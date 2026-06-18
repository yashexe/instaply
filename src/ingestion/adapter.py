"""
Abstract base adapter for ATS source ingestion.
"""

from abc import ABC, abstractmethod

from src.ingestion.models import RawJob


class SourceAdapter(ABC):
    """Base class for all ATS adapters.

    Each adapter knows how to fetch and normalize jobs from a single
    ATS provider.
    """

    provider: str

    @abstractmethod
    async def fetch_jobs(self, source: dict) -> list[RawJob]:
        """Fetch and normalize all jobs from the given source.

        Args:
            source: A dict with at least 'normalized_url', 'company_name',
                    'provider', and other source metadata.

        Returns:
            A list of RawJob instances.
        """
        ...
