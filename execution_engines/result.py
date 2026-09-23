"""The common return value for actions in every execution engine.

An action returns an ExecutionResult to tell its caller what happened:

* output contains display messages as a list of strings. A string can contain
  multiple lines, such as captured command output or an error explanation.
* returncode describes the outcome. Zero means success; nonzero means failure
  or cancellation. The command runner uses 130 for cancellation and 124 for
  timeouts, and otherwise normally preserves the command's exit code.

For example:

    return ExecutionResult(["Container restarted successfully."], 0)
    return ExecutionResult(["Container could not be found."], 1)

Both fields have defaults, so ExecutionResult() represents success with no
messages. An action that returns only messages can omit the return code:

    return ExecutionResult(["Host Actions 1"])

This object stores results; it does not run commands or update the interface.
When a live output callback is installed, the dispatcher forwards final messages
through that callback and clears this list before returning. Commands send their
output directly to the same callback instead of also storing it in the result.
The UI worker uses the return code to report completion; it does not replay or
deduplicate output. Without a callback, output remains available to the caller.

The type lives in its own module so deployment, training, troubleshooting, and
the shared dispatcher can import it without importing one another in a cycle.
"""
from dataclasses import dataclass, field


@dataclass
class ExecutionResult:
    # A factory gives each result its own list, preventing messages from being
    # accidentally shared between separate actions.
    output: list[str] = field(default_factory=list)
    returncode: int = 0
