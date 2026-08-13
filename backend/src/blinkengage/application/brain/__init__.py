"""Application-layer boundary for the Company AI Brain.

The domain package holds the rules; this one holds the shape of the thing that
will eventually apply them against a database, a provider and the tool
executor. Phase 1 ships the interface only — see
``docs/architecture/company-ai-brain.md``.
"""

from blinkengage.application.brain.orchestrator import BrainOrchestrator
from blinkengage.application.brain.service import CompanyBrain

__all__ = ["BrainOrchestrator", "CompanyBrain"]
