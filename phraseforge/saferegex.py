"""Regular expressions that come from phrase text ({#regexpos}, {#regexcount},
-validate regex:...). A pattern such as (a+)+ takes exponential time on some
input, and an imported phrase can carry one (security R33). Python's re module
has no time limit, so:

- patterns and texts have a length limit;
- a quantifier on a group that already repeats ((a+)+, (\\w*)*, (x+){2,}) is refused,
  the usual cause of catastrophic backtracking;
- a match runs in a worker thread and gives up after a time limit. The thread
  cannot be stopped, so a pattern that ran out of time is remembered and refused
  from then on, and only one such thread may be running at a time.
"""
from __future__ import annotations

import re
import threading

MAX_PATTERN = 500
MAX_TEXT = 100_000
TIMEOUT_S = 1.0


class RegexError(ValueError):
    """The pattern is refused or did not finish in time; str(e) says why."""


_slow: set[tuple[str, int]] = set()        # (pattern, flags) that ran out of time
_busy = threading.Lock()                    # held while a timed-out match may still run


def nested_quantifier(pattern: str) -> bool:
    """True if a repeated group contains a repeat: (a+)+, ((ab)*)+, (?:x|y+){1,}."""
    stack: list[bool] = []                  # per open group: contains a quantifier
    i, n, in_class = 0, len(pattern), False
    while i < n:
        c = pattern[i]
        if c == "\\":
            i += 2
            continue
        if in_class:
            in_class = c != "]"
            i += 1
            continue
        if c == "[":
            in_class = True
            i += 2 if pattern[i + 1:i + 2] == "]" else 1   # []] holds a literal ]
            continue
        if c == "(":
            stack.append(False)
        elif c == ")":
            inner = stack.pop() if stack else False
            nxt = pattern[i + 1:i + 2]
            repeated = nxt in ("*", "+") or (nxt == "{" and re.match(r"\{\d*,\d*\}|\{\d*[2-9]\d*\}",
                                                                     pattern[i + 1:]))
            if repeated and inner:
                return True
            if stack and (inner or repeated):
                stack[-1] = True
        elif c in "*+?" or (c == "{" and re.match(r"\{\d*(,\d*)?\}", pattern[i:])):
            if c != "?" or (i and pattern[i - 1] not in "*+?}("):   # a lazy ? is not a new repeat
                if stack:
                    stack[-1] = True
        i += 1
    return False


def compile_checked(pattern: str, flags: int = 0) -> re.Pattern:
    if len(pattern) > MAX_PATTERN:
        raise RegexError(f"pattern longer than {MAX_PATTERN} characters")
    if nested_quantifier(pattern):
        raise RegexError("nested repeats such as (a+)+ are not allowed (they can hang)")
    if (pattern, flags) in _slow:
        raise RegexError("pattern too slow")
    try:
        return re.compile(pattern, flags)
    except re.error as e:
        raise RegexError(f"bad pattern: {e}") from e


def run(pattern: str, flags: int, text: str, fn, timeout: float = TIMEOUT_S):
    """fn(compiled, text) under the limits above; raises RegexError."""
    rx = compile_checked(pattern, flags)
    if len(text) > MAX_TEXT:
        raise RegexError(f"text longer than {MAX_TEXT} characters")
    if not _busy.acquire(timeout=timeout):
        raise RegexError("another pattern is still running")
    box: dict = {}
    done = threading.Event()

    def work():
        try:
            box["v"] = fn(rx, text)
        except Exception as e:              # noqa: BLE001 - handed to the caller
            box["e"] = e
        finally:
            done.set()
            _busy.release()

    threading.Thread(target=work, name="regex", daemon=True).start()
    if not done.wait(timeout):
        _slow.add((pattern, flags))         # the lock stays held until that thread ends
        raise RegexError("pattern too slow")
    if "e" in box:
        raise box["e"]
    return box["v"]
