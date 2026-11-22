"""Tests for CLI helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from openpyxl import load_workbook
from typer.testing import CliRunner

from txnclassify.cli import (
    app,
    apply_decisions,
    clarify,
    classify_groups,
    group_transactions,
    resolve_answer,
)
from txnclassify.llm import (
    ClassifierError,
    Decision,
    DecisionCache,
    HermesClassifier,
    MerchantGroup,
)

CLASSES = ["Grocery", "Transport"]


def _reply(klass: str) -> dict[str, Any]:
    """A Hermes reply classifying the single item with id 0."""
    content = json.dumps({"results": [{"id": 0, "class": klass, "confidence": 0.9}]})
    return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}


@pytest.mark.parametrize(
    ("answer", "suggestion", "expected"),
    [
        ("", "Grocery", "Grocery"),
        ("", "", None),
        ("s", "Grocery", None),
        ("S", "Grocery", None),
        ("2", "Grocery", "Transport"),
        ("transport", "", "Transport"),
        ("Cash Machine", "", "Cash Machine"),
        ("unknown", "Grocery", None),
        ("", "Unknown", None),
    ],
)
def test_resolve_answer(answer: str, suggestion: str, expected: str | None) -> None:
    """Enter accepts, numbers select, names match or create, s skips."""
    assert resolve_answer(answer, suggestion, CLASSES) == expected


@pytest.mark.parametrize("answer", ["0", "3", "122"])
def test_resolve_answer_rejects_out_of_range_number(answer: str) -> None:
    """A number outside the list is an error, not a new class name."""
    with pytest.raises(ValueError, match="No class number"):
        resolve_answer(answer, "Grocery", CLASSES)


def test_clarify_reprompts_after_out_of_range_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An out-of-range number asks again and adds no class."""
    frame = pd.DataFrame(
        {"Description": ["SUPERMARKET_1"], "Type": ["POS"], "Value": [-10]}
    )
    groups = group_transactions(frame)
    answers = iter(["27", "2"])
    monkeypatch.setattr("txnclassify.cli.typer.prompt", lambda *a, **kw: next(answers))
    classes = CLASSES.copy()
    decision = clarify(next(iter(groups.values())), Decision("Grocery", 0.4), classes)
    assert decision.klass == "Transport"
    assert decision.confirmed
    assert classes == CLASSES


@pytest.mark.parametrize(
    "verify,fail_at", [(False, 2), (True, 2), (True, 3), (True, 4)]
)
def test_completed_batches_resume_after_failure(
    tmp_path: Path, verify: bool, fail_at: int
) -> None:
    """Successful first passes and verified results survive later failures."""
    groups = {g.key: g for g in [MerchantGroup("A", "out"), MerchantGroup("B", "out")]}
    path = tmp_path / "decisions.json"
    calls = 0
    resumed: list[str] = []

    def post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise ClassifierError("synthetic failure")
        item = json.loads(payload["messages"][1]["content"])[0]
        if calls > fail_at:
            resumed.append(item["merchant"])
        return _reply("Grocery")

    classifier = HermesClassifier({"Grocery": []}, "test-key", post=post)
    with pytest.raises(ClassifierError, match="synthetic failure"):
        classify_groups(groups, classifier, DecisionCache(path), 1, False, verify)
    saved = DecisionCache(path)
    assert saved.get("out|A") is not None
    if fail_at == 4:
        assert saved.decisions["out|B"].verified
        assert not saved.decisions["out|A"].verified
    elif fail_at == 2:
        assert saved.get("out|B") is None

    results = classify_groups(groups, classifier, saved, 1, False, verify)
    assert len(results) == 2
    if fail_at == 4:
        assert resumed == ["A"]
    elif fail_at == 3:
        assert resumed == ["B", "A"]
    elif verify:
        assert resumed == ["B", "B", "A"]
    else:
        assert resumed == ["B"]
    assert all(d.verified == verify for d in DecisionCache(path).decisions.values())


def test_cached_first_pass_gets_verified_without_repeating_it(tmp_path: Path) -> None:
    """Enabling verification later checks answers from a no-verify run."""
    group = MerchantGroup("SUPERMARKET_1", "out")
    store = DecisionCache(tmp_path / "decisions.json")
    store.put(group.key, Decision("Grocery", 0.9))
    calls = 0

    def post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _reply("Transport")

    classifier = HermesClassifier(
        {"Grocery": [], "Transport": []}, "test-key", post=post
    )
    result = classify_groups({group.key: group}, classifier, store, 20, False)[
        group.key
    ]
    assert calls == 1
    assert result.verified
    assert result.confidence == 0.4
    assert result.alternatives == ["Transport"]
    classify_groups(
        {group.key: group}, classifier, DecisionCache(store.path), 20, False
    )
    assert calls == 1


def test_confirmed_cache_survives_refresh_without_model_calls(tmp_path: Path) -> None:
    """Refresh and verification always preserve human confirmations."""
    group = MerchantGroup("SUPERMARKET_1", "out")
    store = DecisionCache(tmp_path / "decisions.json")
    store.put(group.key, Decision("Grocery", 1.0, confirmed=True))

    def post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        pytest.fail("confirmed decisions must not reach the model")

    result = classify_groups(
        {group.key: group}, HermesClassifier({}, "test-key", post=post), store, 20, True
    )
    assert result[group.key].confirmed


@pytest.mark.parametrize("value,fallback", [(-10, "Expense"), (10, "Income")])
def test_skip_uses_direction_fallback_and_survives_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: int, fallback: str
) -> None:
    """Skipping a recognised category never silently applies that suggestion."""
    frame = pd.DataFrame(
        {"Description": ["SUPERMARKET_1"], "Type": ["POS"], "Value": [value]}
    )
    groups = group_transactions(frame)
    key = next(iter(groups))
    monkeypatch.setattr("txnclassify.cli.typer.prompt", lambda *a, **kw: "s")
    skipped = clarify(groups[key], Decision("Grocery", 0.4), CLASSES.copy())
    store = DecisionCache(tmp_path / "decisions.json")
    store.put(key, skipped)
    store.save()
    reloaded = DecisionCache(store.path).decisions
    apply_decisions(frame, groups, reloaded, [*CLASSES, "Income", "Expense"], 0.7)
    assert frame.loc[0, "Class"] == fallback
    assert frame.loc[0, "Review"]
    assert reloaded[key].klass == "Grocery"
    assert reloaded[key].skipped


def _input_files(tmp_path: Path) -> tuple[Path, Path]:
    infile = tmp_path / "transactions.csv"
    pd.DataFrame(
        {
            "Date": ["17 Aug 2025"],
            "Type": ["POS"],
            "Description": ["SUPERMARKET_1"],
            "Value": [-10.0],
            "Account Number": ["00000000"],
            "Account Name": ["EXAMPLE"],
            "Balance": [0.0],
        }
    ).to_csv(infile, index=False)
    examples = tmp_path / "examples.json"
    examples.write_text('{"Grocery": ["SUPERMARKET_1"]}', encoding="utf-8")
    return infile, examples


@pytest.fixture
def model_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace Hermes HTTP requests with synthetic classifications."""
    requests: list[dict[str, Any]] = []

    def post(
        url: str, payload: dict[str, Any], timeout: float, *, headers: dict[str, str]
    ) -> dict[str, Any]:
        requests.append(payload)
        items = json.loads(payload["messages"][1]["content"])
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {
                                "results": [
                                    {
                                        "id": item["id"],
                                        "class": "Grocery",
                                        "confidence": 0.9,
                                        "reason": "Synthetic classification",
                                    }
                                    for item in items
                                ]
                            }
                        )
                    },
                }
            ]
        }

    monkeypatch.setattr("txnclassify.llm._http_post", post)
    monkeypatch.setenv("API_SERVER_KEY", "synthetic-test-key")
    monkeypatch.setenv("HERMES_API_URL", "http://example.invalid:8642/v1")
    return requests


def _run_export(infile: Path, examples: Path, tmp_path: Path) -> Any:
    return CliRunner().invoke(
        app,
        [
            str(infile),
            str(tmp_path / "output.xlsx"),
            "--no-interactive",
            "--examples",
            str(examples),
            "--cache",
            str(tmp_path / "cache.json"),
        ],
    )


@pytest.mark.parametrize(
    ("args", "expected"), [([], 900.0), (["--timeout", "120"], 120.0)]
)
def test_timeout_option_reaches_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str], expected: float
) -> None:
    """Every model request waits for the configured number of seconds."""
    infile, examples = _input_files(tmp_path)
    timeouts: list[float] = []

    def post(
        url: str, payload: dict[str, Any], timeout: float, *, headers: dict[str, str]
    ) -> dict[str, Any]:
        timeouts.append(timeout)
        return _reply("Grocery")

    monkeypatch.setattr("txnclassify.llm._http_post", post)
    monkeypatch.setenv("API_SERVER_KEY", "synthetic-test-key")
    result = CliRunner().invoke(
        app,
        [
            str(infile),
            str(tmp_path / "output.xlsx"),
            "--no-interactive",
            "--examples",
            str(examples),
            "--cache",
            str(tmp_path / "cache.json"),
            *args,
        ],
    )
    assert result.exit_code == 0, result.output
    assert timeouts and all(t == expected for t in timeouts)


def test_export_preserves_formula_like_text(
    tmp_path: Path, model_requests: list[dict[str, Any]]
) -> None:
    """Untrusted transaction and category strings are never Excel formulas."""
    infile, examples = _input_files(tmp_path)
    frame = pd.read_csv(infile)
    frame["Description"] = "=1+1"
    frame.to_csv(infile, index=False)
    store = DecisionCache(tmp_path / "cache.json")
    store.put("out|=1+1", Decision("=2+2", 1.0, confirmed=True))
    store.save()

    result = _run_export(infile, examples, tmp_path)

    assert result.exit_code == 0, result.output
    assert not model_requests
    workbook = load_workbook(tmp_path / "output.xlsx", data_only=False)
    try:
        sheet = workbook.active
        assert sheet is not None
        columns = {cell.value: i for i, cell in enumerate(sheet[1], start=1)}
        for name, value in [
            ("Description", "=1+1"),
            ("SubClass", "=1+1"),
            ("Class", "=2+2"),
        ]:
            cell = sheet.cell(2, columns[name])
            assert cell.value == value
            assert cell.data_type == "s"
    finally:
        workbook.close()


def test_hermes_cli_writes_excel_with_env_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Hermes CLI route authenticates, verifies and writes a usable report."""
    infile, examples = _input_files(tmp_path)
    outfile = tmp_path / "output.xlsx"
    calls: list[dict[str, Any]] = []

    def post(
        url: str, payload: dict[str, Any], timeout: float, *, headers: dict[str, str]
    ) -> dict[str, Any]:
        assert url == "http://example.invalid:8642/v1/chat/completions"
        assert headers == {"Authorization": "Bearer synthetic-test-key"}
        assert payload["model"] == "hermes-agent"
        calls.append(payload)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {
                                "results": [
                                    {"id": 0, "class": "Grocery", "confidence": 0.9}
                                ]
                            }
                        )
                    },
                }
            ]
        }

    monkeypatch.setattr("txnclassify.llm._http_post", post)
    result = CliRunner().invoke(
        app,
        [
            str(infile),
            str(outfile),
            "--no-interactive",
            "--examples",
            str(examples),
            "--cache",
            str(tmp_path / "cache.json"),
        ],
        env={
            "API_SERVER_KEY": "synthetic-test-key",
            "HERMES_API_URL": "http://example.invalid:8642/v1",
        },
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 2
    assert "synthetic-test-key" not in result.output
    output = pd.read_excel(outfile)
    assert output.loc[0, "Class"] == "Grocery"
    assert not output.loc[0, "Review"]
    assert "Account Number" not in output
    assert "Class" in result.output and "SubClass" in result.output


def test_hermes_cli_missing_key_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing Hermes key fails clearly before any model request."""
    infile, examples = _input_files(tmp_path)
    monkeypatch.delenv("API_SERVER_KEY", raising=False)
    # A generic OpenAI key must never be sent to the Hermes server.
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-key")
    result = CliRunner().invoke(
        app,
        [
            str(infile),
            str(tmp_path / "output.xlsx"),
            "--examples",
            str(examples),
            "--cache",
            str(tmp_path / "cache.json"),
        ],
    )
    assert result.exit_code == 1
    assert "set API_SERVER_KEY or --api-key" in result.output
    assert not (tmp_path / "output.xlsx").exists()
