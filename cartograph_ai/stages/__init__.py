"""Pipeline stages.

Stage 1 (HTTP probe) and Stage 2 (HTML analysis) are pure-Python and
always run. Stage 3 (JS execution) is opt-in via the ``browser`` extra
and lives in a separate module shipped only when Playwright is installed.
Stage 4 (Claude classification) is the LLM call.
"""
