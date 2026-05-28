"""cartograph-ai: probe before extract.

Given a URL, classify how a site serves data and recommend the optimal
extraction strategy. Claude is the intelligence layer, not the scraper.

Public API::

    from cartograph_ai import probe

See https://github.com/AgentXaGent/cartograph-ai for full docs.
"""

from cartograph_ai.exceptions import (
    AntiBotDetectedError,
    AuthWalledError,
    CartographError,
    ClassificationError,
    HTMLAnalysisError,
    HTTPProbeError,
    LowConfidenceError,
    OutputValidationError,
    ProbeTimeoutError,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "AntiBotDetectedError",
    "AuthWalledError",
    "CartographError",
    "ClassificationError",
    "HTMLAnalysisError",
    "HTTPProbeError",
    "LowConfidenceError",
    "OutputValidationError",
    "ProbeTimeoutError",
]
