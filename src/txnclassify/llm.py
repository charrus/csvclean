"""Classify transactions using a language model served by Ollama."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_OLLAMA_URL = "http://compute1.college-court.co.uk:11434"
DEFAULT_MODEL = "gemma4:e2b"
DEFAULT_CACHE = Path.home() / ".cache" / "txnclassify" / "decisions.json"
UNKNOWN = "Unknown"
# Generic fallbacks, always offered alongside the classes from the examples file.
BASE_CLASSES = ("Income", "Expense")

# Fields in a description that carry no information about the counterparty.
_NOISE_FIELD = re.compile(
    r"""^(
        \d{4}\s\d{2}[A-Z]{3}\d{2}(\s[A-Z])?   # card prefix: 9581 03JUN24 C
        | FP\s\d{2}/.*                         # faster payment reference
        | VIA\s.*                              # VIA MOBILE - PYMT, Via Mobile Xfer
        | INITIAL\sPAYMENT
    )$""",
    re.IGNORECASE | re.VERBOSE,
)
# Trailing "TOWN CC" location on card payments.
_LOCATION_FIELD = re.compile(r"^[A-Z0-9 .'/-]+ [A-Z]{2}$")
_DATE_TOKEN = re.compile(r"^\d{2}[A-Z]{3}(\d{2})?$", re.IGNORECASE)


def _is_reference(token: str) -> bool:
    """Guess whether a token is a date, number or reference code, not a name."""
    digits = sum(c.isdigit() for c in token)
    if digits == 0:
        return False
    return (
        bool(_DATE_TOKEN.match(token))
        or digits * 2 > len(token)
        or (digits >= 2 and len(token) >= 6 and not token.isalpha())
    )


PostFn = Callable[[str, dict[str, Any], float], dict[str, Any]]


class OllamaError(RuntimeError):
    """Raised when the Ollama server cannot be reached or returns an error."""


def normalise_merchant(description: str) -> str:
    """Reduce a raw transaction description to a stable merchant key.

    Drops card prefixes, payment references, dates, trailing locations and
    reference-like tokens (numbers, codes), then keeps at most the first two
    remaining fields.

    Args:
        description: Raw description from the bank export.

    Returns:
        Upper-case merchant key, or the stripped description if nothing remains.
    """
    fields = [f.strip() for f in description.split(",")]
    fields = [f for f in fields if f and not _NOISE_FIELD.match(f)]
    if len(fields) > 1 and _LOCATION_FIELD.match(fields[-1]):
        fields.pop()
    cleaned = []
    for f in fields:
        tokens = [t for t in f.split() if not _is_reference(t)]
        if tokens:
            cleaned.append(" ".join(tokens))
    key = " , ".join(cleaned[:2]).upper()
    return key or description.strip().upper()


def load_examples(path: Path | None = None) -> dict[str, list[str]]:
    """Load the example classifications used to guide the model.

    Args:
        path: JSON file mapping class names to example merchant keywords. When
            omitted, the personal ``classifications.json`` next to this module is
            used if present, otherwise the anonymised example in the repo root.

    Returns:
        Mapping of class name to example keywords (empty if no file is found).
    """
    if path is None:
        personal = Path(__file__).parent / "classifications.json"
        example = Path(__file__).parents[2] / "classifications.example.json"
        path = personal if personal.exists() else example
        if not path.exists():
            return {}
    with open(path, encoding="utf-8") as f:
        data: dict[str, list[str]] = json.load(f)
    return data


def _useful_suggestion(suggested: str, klass: str) -> str:
    """Drop a proposed class that is blank, Unknown or the chosen class."""
    suggested = suggested.strip()
    return (
        "" if suggested.lower() in ("", UNKNOWN.lower(), klass.lower()) else suggested
    )


@dataclass
class Decision:
    """The class chosen for one merchant group."""

    klass: str
    confidence: float
    reason: str = ""
    suggested_class: str = ""
    alternatives: list[str] = field(default_factory=list)
    confirmed: bool = False
    source: str = "llm"

    def to_json(self) -> dict[str, Any]:
        """Serialise for the cache file (the runtime ``source`` is not stored)."""
        data = asdict(self)
        del data["source"]
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Decision:
        """Build a cached decision from its serialised form."""
        return cls(
            klass=str(data["klass"]),
            confidence=float(data.get("confidence", 0.0)),
            reason=str(data.get("reason", "")),
            suggested_class=_useful_suggestion(
                str(data.get("suggested_class", "")), str(data["klass"])
            ),
            alternatives=[str(a) for a in data.get("alternatives", [])],
            confirmed=bool(data.get("confirmed", False)),
            source="cache",
        )


@dataclass
class MerchantGroup:
    """All transactions sharing a merchant key and direction of money flow."""

    merchant: str
    direction: str  # "in" or "out"
    descriptions: list[str] = field(default_factory=list)
    types: set[str] = field(default_factory=set)
    total: float = 0.0
    count: int = 0

    @property
    def key(self) -> str:
        """Cache key for this group."""
        return f"{self.direction}|{self.merchant}"


def merge_passes(first: Decision, second: Decision) -> Decision:
    """Combine two independent decisions for the same group.

    Small models report similar confidence whether right or wrong, so agreement
    between two passes is a more useful certainty signal than either score.

    Args:
        first: Decision from the first pass.
        second: Decision from the second pass.

    Returns:
        The first decision, with confidence capped at 0.4 if the passes disagree
        and the other pass's answer recorded as an alternative.
    """
    alternatives = [
        a
        for a in dict.fromkeys(
            [second.klass, *first.alternatives, *second.alternatives]
        )
        if a != first.klass
    ]
    merged = Decision(
        klass=first.klass,
        confidence=min(first.confidence, second.confidence),
        reason=first.reason,
        suggested_class=first.suggested_class or second.suggested_class,
        alternatives=alternatives,
    )
    if first.klass != second.klass:
        merged.confidence = min(merged.confidence, 0.4)
        merged.reason = f"Second opinion was {second.klass}. {first.reason}".strip()
    return merged


def needs_clarification(
    decision: Decision, classes: Iterable[str], threshold: float
) -> bool:
    """Decide whether a human should confirm a decision.

    Args:
        decision: The decision to check.
        classes: Currently known class names.
        threshold: Minimum confidence accepted without asking.

    Returns:
        True if the decision is unconfirmed and uncertain or outside ``classes``.
    """
    if decision.confirmed:
        return False
    return (
        decision.klass == UNKNOWN
        or decision.klass not in set(classes)
        or decision.confidence < threshold
    )


class DecisionCache:
    """Persist decisions between runs, keyed by merchant group."""

    def __init__(self, path: Path) -> None:
        """Load the cache at ``path`` if it exists."""
        self.path = path
        self.decisions: dict[str, Decision] = {}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            self.decisions = {
                k: Decision.from_json(v) for k, v in raw.get("decisions", {}).items()
            }

    def get(self, key: str, refresh: bool = False) -> Decision | None:
        """Return a cached decision; with ``refresh`` only confirmed ones."""
        decision = self.decisions.get(key)
        if decision is None or (refresh and not decision.confirmed):
            return None
        return decision

    def put(self, key: str, decision: Decision) -> None:
        """Store a decision, never overwriting a confirmed one with a guess."""
        existing = self.decisions.get(key)
        if existing and existing.confirmed and not decision.confirmed:
            return
        self.decisions[key] = decision

    def confirmed_classes(self) -> set[str]:
        """Class names the user has confirmed, including ones they created."""
        return {d.klass for d in self.decisions.values() if d.confirmed}

    def save(self) -> None:
        """Write the cache to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "decisions": {k: d.to_json() for k, d in sorted(self.decisions.items())},
        }
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.path)


def _http_post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result: dict[str, Any] = json.load(response)
    except urllib.error.HTTPError as e:
        raise OllamaError(f"Ollama returned HTTP {e.code}: {e.read().decode()}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise OllamaError(f"Cannot reach Ollama at {url}: {e}") from e
    if "error" in result:
        raise OllamaError(f"Ollama error: {result['error']}")
    return result


def normalise_url(url: str) -> str:
    """Add a scheme to bare ``host:port`` values such as ``OLLAMA_HOST``."""
    url = url.rstrip("/")
    return url if "://" in url else f"http://{url}"


class OllamaClassifier:
    """Classify merchant groups in batches with an Ollama chat model."""

    def __init__(
        self,
        examples: dict[str, list[str]],
        url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 300.0,
        post: PostFn = _http_post,
    ) -> None:
        """Create a classifier.

        Args:
            examples: Class name to example merchant keywords.
            url: Base URL of the Ollama server.
            model: Model name to use.
            timeout: Seconds to wait for each request.
            post: Function performing the HTTP POST (replaceable in tests).
        """
        self.examples = examples
        self._keywords = [
            (keyword.strip().upper(), name)
            for name, keywords in examples.items()
            for keyword in keywords
            if keyword.strip()
        ]
        self.classes = list(dict.fromkeys([*examples, *BASE_CLASSES]))
        self.url = normalise_url(url)
        self.model = model
        self.timeout = timeout
        self._post = post

    def add_classes(self, classes: Iterable[str]) -> None:
        """Make extra classes (e.g. ones the user created) available."""
        for c in classes:
            if c not in self.classes and c != UNKNOWN:
                self.classes.append(c)

    def example_matches(self, group: MerchantGroup) -> list[str]:
        """Classes whose example keywords occur in the group's descriptions."""
        text = " ".join([group.merchant, *group.descriptions]).upper()
        return list(dict.fromkeys(name for kw, name in self._keywords if kw in text))

    def _system_prompt(self) -> str:
        example_lines = "\n".join(
            f"- {name}: {', '.join(keywords)}" if keywords else f"- {name}"
            for name, keywords in self.examples.items()
        )
        return (
            "You classify personal bank transactions into categories.\n"
            "Each item is one merchant or payee with its direction of money flow "
            '("in" = money received, "out" = money spent), the bank transaction '
            "type codes seen, a sample raw description, the number of transactions "
            "and their total value.\n\n"
            "Categories, with example merchant keywords the user has previously "
            f"assigned to each:\n{example_lines}\n"
            f"- Income: generic money received that fits nothing more specific\n"
            f"- Expense: generic money spent that fits nothing more specific\n\n"
            "Rules:\n"
            "- Choose the single most specific category that fits.\n"
            "- Use the examples to understand what each category means to this user.\n"
            "- example_match, when present, lists categories whose example keywords "
            "appear in the transaction. Prefer one of them unless clearly wrong.\n"
            "- Direction matters: money in is never a pure expense category.\n"
            "- Type codes are hints: POS = card payment, D/D = direct debit, "
            "BAC/DPC = bank transfer, C/L = cash machine, INT = interest.\n"
            "- confidence is 0 to 1. Only use 0.8 or above when the merchant is "
            "well known or closely matches an example. Be honest; a wrong "
            "confident answer is worse than asking.\n"
            f'- If no category fits, use "{UNKNOWN}" with low confidence and put a '
            "short proposed category name in suggested_class.\n"
            "- reason is one short sentence.\n"
            "- Return exactly one result per input id."
        )

    def _schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "class": {
                                "type": "string",
                                "enum": [*self.classes, UNKNOWN],
                            },
                            "confidence": {"type": "number"},
                            "reason": {"type": "string"},
                            "suggested_class": {"type": "string"},
                        },
                        "required": ["id", "class", "confidence", "reason"],
                    },
                }
            },
            "required": ["results"],
        }

    def _request(self, groups: list[MerchantGroup]) -> dict[int, Decision]:
        items = [
            {
                "id": i,
                **({"example_match": m} if (m := self.example_matches(g)) else {}),
                "merchant": g.merchant,
                "direction": g.direction,
                "types": sorted(g.types),
                "sample": g.descriptions[0] if g.descriptions else g.merchant,
                "count": g.count,
                "total": round(g.total, 2),
            }
            for i, g in enumerate(groups)
        ]
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": self._schema(),
            "options": {"temperature": 0, "num_ctx": 8192},
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": json.dumps(items)},
            ],
        }
        response = self._post(f"{self.url}/api/chat", payload, self.timeout)
        return parse_results(response.get("message", {}).get("content", ""), groups)

    def classify(self, groups: list[MerchantGroup]) -> list[Decision]:
        """Classify one batch of groups.

        A malformed or incomplete response is retried once, then each missing
        group is sent on its own. Groups that still fail get an ``Unknown``
        decision with zero confidence.

        Args:
            groups: Merchant groups to classify.

        Returns:
            One decision per group, in the same order.

        Raises:
            OllamaError: If the server is unreachable or reports an error.
        """
        results: dict[int, Decision] = {}
        for _ in range(2):
            results = self._request(groups)
            if len(results) == len(groups):
                return [
                    self._check_examples(g, results[i]) for i, g in enumerate(groups)
                ]
        decisions = []
        for i, group in enumerate(groups):
            if i in results:
                decisions.append(self._check_examples(group, results[i]))
                continue
            single = self._request([group]) if len(groups) > 1 else {}
            fallback = Decision(UNKNOWN, 0.0, "Model gave no valid answer")
            decisions.append(self._check_examples(group, single.get(0, fallback)))
        return decisions

    def _check_examples(self, group: MerchantGroup, decision: Decision) -> Decision:
        """Lower confidence when the model contradicts matching examples."""
        matches = self.example_matches(group)
        if matches and decision.klass not in matches:
            decision.confidence = min(decision.confidence, 0.5)
            decision.alternatives = [
                *matches,
                *(a for a in decision.alternatives if a not in matches),
            ]
            decision.reason = (
                f"Examples suggest {', '.join(matches)}. {decision.reason}".strip()
            )
        return decision


def parse_results(content: str, groups: list[MerchantGroup]) -> dict[int, Decision]:
    """Parse the model's JSON reply, discarding invalid entries.

    Args:
        content: Raw message content returned by the model.
        groups: The groups that were sent, used to validate ids.

    Returns:
        Decisions keyed by input id; ids that are missing or invalid are absent.
    """
    try:
        data = json.loads(content)
        entries = data["results"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}
    if not isinstance(entries, list):
        return {}
    results: dict[int, Decision] = {}
    for entry in entries:
        try:
            i = int(entry["id"])
            klass = str(entry["class"]).strip()
            confidence = min(max(float(entry["confidence"]), 0.0), 1.0)
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= i < len(groups) or not klass or i in results:
            continue
        suggested = _useful_suggestion(str(entry.get("suggested_class") or ""), klass)
        results[i] = Decision(
            klass=klass,
            confidence=confidence,
            reason=str(entry.get("reason", "")).strip(),
            suggested_class=suggested,
        )
    return results
