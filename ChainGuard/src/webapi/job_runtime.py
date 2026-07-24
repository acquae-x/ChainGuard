"""Per-job execution context shared with synchronous LLM adapters."""

from contextvars import ContextVar


# The durable worker sets this before running a decision.  ContextVar keeps
# simultaneous web workers isolated; it deliberately is not an environment
# variable shared by unrelated jobs in the same process.
llm_timeout_seconds: ContextVar[float | None] = ContextVar("llm_timeout_seconds", default=None)
