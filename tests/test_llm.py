"""Tests for the Ollama classifier helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from txnclassify.llm import (
    UNKNOWN,
    Decision,
    DecisionCache,
    MerchantGroup,
    OllamaClassifier,
    merge_passes,
    needs_clarification,
    normalise_merchant,
    parse_results,
)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("9581 03JUN24 C , SUPERMARKET_1 4626 , LONDON GB", "SUPERMARKET_1"),
        ("9581 11DEC24 , FOOD_DELIVERY , LONDON GB", "FOOD_DELIVERY"),
        ("9581 12SEP24 , MARKETPLACE* AJ8SL5DL5 , LONDON GB", "MARKETPLACE*"),
        ("FRIEND , TRAVEL , VIA MOBILE - PYMT , FP 13/07/24 1234", "FRIEND , TRAVEL"),
        (
            "To A/C 01234567 , ACCOUNT HOLDER S94, Via Mobile Xfer",
            "TO A/C , ACCOUNT HOLDER",
        ),
        ("INSURANCE_COMPANY , INITIAL PAYMENT", "INSURANCE_COMPANY"),
        ("ATM_OPERATOR 14JUN", "ATM_OPERATOR"),
        ("30APR GRS 12345678", "GRS"),
        ("ENERGY_PROVIDER", "ENERGY_PROVIDER"),
        ("12345", "12345"),
        ("9581 01FEB25 , O2 , WWW.O2.CO.UK GB", "O2"),
    ],
)
def test_normalise_merchant(description: str, expected: str) -> None:
    """Reference numbers, dates and locations are removed."""
    assert normalise_merchant(description) == expected


def _groups(n: int) -> list[MerchantGroup]:
    return [MerchantGroup(f"MERCHANT_{i}", "out", [f"MERCHANT_{i}"]) for i in range(n)]


def _reply(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {"message": {"content": json.dumps({"results": results})}}


def _result(i: int, klass: str = "Grocery", confidence: float = 0.9) -> dict[str, Any]:
    return {"id": i, "class": klass, "confidence": confidence, "reason": "r"}


def test_parse_results_discards_invalid_entries() -> None:
    """Out-of-range ids, duplicates and missing fields are dropped."""
    content = json.dumps(
        {
            "results": [
                _result(0, confidence=1.7),
                _result(0, "Transport"),
                _result(5),
                {"id": 1, "class": "Grocery"},
            ]
        }
    )
    results = parse_results(content, _groups(2))
    assert list(results) == [0]
    assert results[0].klass == "Grocery"
    assert results[0].confidence == 1.0


def test_parse_results_ignores_useless_suggestions() -> None:
    """A proposed class of Unknown, or the chosen class itself, is dropped."""
    entries = [
        {**_result(0, UNKNOWN), "suggested_class": "unknown"},
        {**_result(1, "Grocery"), "suggested_class": "Grocery"},
        {**_result(2, UNKNOWN), "suggested_class": "Pets"},
    ]
    results = parse_results(json.dumps({"results": entries}), _groups(3))
    assert [r.suggested_class for r in results.values()] == ["", "", "Pets"]


def test_parse_results_malformed() -> None:
    """Non-JSON replies yield no results."""
    assert parse_results("not json", _groups(1)) == {}
    assert parse_results('{"results": 3}', _groups(1)) == {}


def test_classify_retries_then_falls_back_per_item() -> None:
    """An incomplete batch is retried, then missing items are sent singly."""
    calls: list[list[dict[str, Any]]] = []

    def post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        items = json.loads(payload["messages"][1]["content"])
        calls.append(items)
        if len(items) > 1:
            return _reply([_result(0)])  # always omits id 1
        return _reply([_result(0, "Transport")])

    classifier = OllamaClassifier({"Grocery": [], "Transport": []}, post=post)
    decisions = classifier.classify(_groups(2))
    assert [d.klass for d in decisions] == ["Grocery", "Transport"]
    assert [len(c) for c in calls] == [2, 2, 1]
    assert calls[2][0]["merchant"] == "MERCHANT_1"


def test_classify_gives_unknown_when_model_never_answers() -> None:
    """A group the model cannot classify becomes Unknown with zero confidence."""

    def post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        return {"message": {"content": "{}"}}

    decisions = OllamaClassifier({}, post=post).classify(_groups(1))
    assert decisions[0].klass == UNKNOWN
    assert decisions[0].confidence == 0.0


def test_schema_restricts_classes() -> None:
    """The response schema only allows known classes and Unknown."""
    captured: dict[str, Any] = {}

    def post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        captured.update(payload)
        return _reply([_result(0)])

    classifier = OllamaClassifier(
        {"Grocery": ["SUPERMARKET_1"]}, url="host:1", post=post
    )
    classifier.add_classes(["Pets"])
    classifier.classify(_groups(1))
    item_schema = captured["format"]["properties"]["results"]["items"]
    assert item_schema["properties"]["class"]["enum"] == [
        "Grocery",
        "Income",
        "Expense",
        "Pets",
        UNKNOWN,
    ]
    assert "SUPERMARKET_1" in captured["messages"][0]["content"]


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (Decision("Grocery", 0.9), False),
        (Decision("Grocery", 0.5), True),
        (Decision(UNKNOWN, 0.9), True),
        (Decision("Invented", 0.9), True),
        (Decision("Invented", 0.1, confirmed=True), False),
    ],
)
def test_needs_clarification(decision: Decision, expected: bool) -> None:
    """Uncertain, unknown or unlisted classes need a human unless confirmed."""
    assert needs_clarification(decision, ["Grocery"], 0.7) is expected


def test_cache_keeps_confirmed_decisions(tmp_path: Path) -> None:
    """Confirmed answers survive model guesses, refreshes and reloads."""
    path = tmp_path / "sub" / "decisions.json"
    cache = DecisionCache(path)
    cache.put("out|A", Decision("Pets", 1.0, confirmed=True, source="user"))
    cache.put("out|A", Decision("Grocery", 0.9))
    cache.put("out|B", Decision("Grocery", 0.9))
    cache.save()

    reloaded = DecisionCache(path)
    confirmed = reloaded.get("out|A", refresh=True)
    assert confirmed is not None
    assert (confirmed.klass, confirmed.source) == ("Pets", "cache")
    assert reloaded.get("out|B") is not None
    assert reloaded.get("out|B", refresh=True) is None
    assert reloaded.confirmed_classes() == {"Pets"}


def test_example_match_lowers_confidence_when_contradicted() -> None:
    """A class that contradicts matching example keywords is sent for review."""
    sent: list[dict[str, Any]] = []

    def post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        sent.extend(json.loads(payload["messages"][1]["content"]))
        return _reply([_result(0, "Transport", 0.95), _result(1, "Grocery", 0.95)])

    classifier = OllamaClassifier(
        {"Grocery": ["supermarket_1"], "Transport": []}, post=post
    )
    groups = [
        MerchantGroup("SUPERMARKET_1", "out", ["9581 03JUN24 C , SUPERMARKET_1 4626"]),
        MerchantGroup("SUPERMARKET_1 EXPRESS", "out", ["SUPERMARKET_1 EXPRESS"]),
    ]
    wrong, right = classifier.classify(groups)
    assert sent[0]["example_match"] == ["Grocery"]
    assert (wrong.confidence, wrong.alternatives) == (0.5, ["Grocery"])
    assert right.confidence == 0.95


def test_merge_passes() -> None:
    """Disagreeing passes cap confidence and record the other answer."""
    agreed = merge_passes(Decision("Grocery", 0.9), Decision("Grocery", 0.8))
    assert (agreed.klass, agreed.confidence, agreed.alternatives) == (
        "Grocery",
        0.8,
        [],
    )
    disagreed = merge_passes(Decision("Grocery", 0.9), Decision("Takeaway", 0.9))
    assert (disagreed.klass, disagreed.confidence) == ("Grocery", 0.4)
    assert disagreed.alternatives == ["Takeaway"]
