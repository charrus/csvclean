"""CLI."""

from __future__ import annotations

import math
import sys
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from txnclassify.llm import (
    BASE_CLASSES,
    DEFAULT_CACHE,
    DEFAULT_HERMES_MODEL,
    DEFAULT_HERMES_URL,
    DEFAULT_TIMEOUT,
    UNKNOWN,
    BatchClassifier,
    ClassifierError,
    Decision,
    DecisionCache,
    HermesClassifier,
    MerchantGroup,
    load_examples,
    merge_passes,
    needs_clarification,
    normalise_merchant,
)

app = typer.Typer(help="Clean up bank transactions and classify them.")

# Transaction types whose class is fixed: these rows never reach the model.
TYPE_CLASSES = {"INT": "Interest"}


def type_rule(group: MerchantGroup) -> Decision | None:
    """Return the fixed decision for a group made only of rule-typed rows."""
    classes = {TYPE_CLASSES.get(t) for t in group.types}
    if len(classes) != 1 or None in classes:
        return None
    (klass,) = classes
    assert klass is not None
    return Decision(
        klass=klass,
        confidence=1.0,
        reason=f"Transaction type {', '.join(sorted(group.types))}",
        confirmed=True,
        source="rule",
        verified=True,
    )


def group_transactions(df: pd.DataFrame) -> dict[str, MerchantGroup]:
    """Group transactions by merchant key and direction of money flow.

    Adds a ``Merchant`` column holding the group key for each row.

    Args:
        df: Transactions with ``Description``, ``Type`` and ``Value`` columns.

    Returns:
        Merchant groups keyed by their cache key.
    """
    groups: dict[str, MerchantGroup] = {}
    keys = []
    for description, txn_type, value in zip(
        df["Description"].fillna(""), df["Type"].fillna(""), df["Value"], strict=True
    ):
        group = MerchantGroup(
            merchant=normalise_merchant(str(description)),
            direction="in" if value > 0 else "out",
        )
        group = groups.setdefault(group.key, group)
        if description not in group.descriptions:
            group.descriptions.append(str(description))
        group.types.add(str(txn_type))
        group.total += float(value)
        group.count += 1
        keys.append(group.key)
    df["Merchant"] = keys
    return groups


def print_classes(classes: list[str]) -> None:
    """Print numbered class names in columns."""
    width = max(len(c) for c in classes) + 6
    columns = max(1, 88 // width)
    cells = [f"{i:>3}. {name}".ljust(width) for i, name in enumerate(classes, 1)]
    for row in range(0, len(cells), columns):
        typer.echo("".join(cells[row : row + columns]).rstrip())


def show_decision(group: MerchantGroup, decision: Decision) -> None:
    """Print a merchant group and the model's view of it."""
    money = "money in" if group.direction == "in" else "money out"
    total = f"{'-' if group.total < 0 else ''}£{abs(group.total):,.2f}"
    typer.echo("")
    typer.secho(
        f"{group.merchant}  ({money}, {group.count} txns, total {total})", bold=True
    )
    for description in group.descriptions[:3]:
        typer.echo(f"    {description}")
    typer.echo(f"  Model: {decision.klass} ({decision.confidence:.0%})")
    if decision.suggested_class and decision.klass == UNKNOWN:
        typer.echo(f"  Proposed new class: {decision.suggested_class}")
    if decision.alternatives:
        typer.echo(f"  Alternatives: {', '.join(decision.alternatives)}")
    if decision.reason:
        typer.echo(f"  Reason: {decision.reason}")


def resolve_answer(answer: str, suggestion: str, classes: list[str]) -> str | None:
    """Turn a clarification answer into a class name.

    Args:
        answer: What the user typed (already stripped).
        suggestion: Class used when the answer is empty; may be empty.
        classes: Known class names, numbered from 1.

    Returns:
        The chosen class, or None if the user skipped.

    Raises:
        ValueError: If the answer is a number outside the class list.
    """
    if answer.lower() == "s":
        return None
    if not answer:
        chosen = suggestion
    elif answer.isdecimal():
        if not 1 <= int(answer) <= len(classes):
            raise ValueError(f"No class number {answer}; choose 1-{len(classes)}.")
        chosen = classes[int(answer) - 1]
    else:
        # Match an existing class case-insensitively, otherwise create one.
        chosen = next((c for c in classes if c.lower() == answer.lower()), answer)
    return chosen if chosen and chosen.lower() != UNKNOWN.lower() else None


def clarify(group: MerchantGroup, decision: Decision, classes: list[str]) -> Decision:
    """Ask the user to confirm or correct a decision.

    Args:
        group: The merchant group in question.
        decision: The model's decision.
        classes: Known class names; a newly created class is appended.

    Returns:
        A confirmed decision, or a decision marked as skipped.
    """
    show_decision(group, decision)
    suggestion = decision.klass if decision.klass != UNKNOWN else ""
    suggestion = suggestion or decision.suggested_class
    default = f"Enter = {suggestion}, s = skip" if suggestion else "Enter/s = skip"
    prompt = f"  Class [number or name, ? = list, {default}]"
    while True:
        answer = typer.prompt(prompt, default="", show_default=False).strip()
        if answer == "?":
            print_classes(classes)
            continue
        try:
            chosen = resolve_answer(answer, suggestion, classes)
        except ValueError as error:
            typer.secho(f"  {error}", fg="red")
            continue
        break

    if chosen is None:
        return replace(decision, skipped=True)
    if chosen not in classes:
        classes.append(chosen)
        typer.echo(f"  Added class {len(classes)}. {chosen}")
    return Decision(
        klass=chosen,
        confidence=1.0,
        reason="Confirmed by user",
        confirmed=True,
        source="user",
    )


# Seconds between "thinking" updates while a model request runs: a live clock
# in a terminal, but sparse lines when output goes to a log.
HEARTBEAT_SECONDS = 30.0
LIVE_HEARTBEAT_SECONDS = 1.0
# Merchant and class names longer than these are shortened in progress output.
MERCHANT_WIDTH = 32
CLASS_WIDTH = 24
# Characters in the confidence bar; partial blocks give eighth-of-a-cell steps.
BAR_WIDTH = 5
_PARTIAL_BLOCKS = " ▏▎▍▌▋▊▉"


def format_duration(seconds: float) -> str:
    """Format elapsed seconds as ``45s`` or ``4m 05s``."""
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def format_clock(seconds: float) -> str:
    """Format elapsed seconds as a stopwatch-style ``M:SS`` clock, e.g. ``4:05``."""
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes}:{secs:02d}"


@contextmanager
def heartbeat(
    interval: float | None = None, live: bool | None = None
) -> Generator[None, None, None]:
    """Print the elapsed time periodically until the block finishes.

    Args:
        interval: Seconds between updates (default ``LIVE_HEARTBEAT_SECONDS``
            when redrawing in place, else ``HEARTBEAT_SECONDS``).
        live: Redraw one line in place rather than printing a line per update.
            Defaults to whether stderr is a terminal, so logs stay readable.

    Yields:
        Nothing; the heartbeat runs while the ``with`` block does.
    """
    in_place = sys.stderr.isatty() if live is None else live
    if interval is not None:
        every = interval
    else:
        every = LIVE_HEARTBEAT_SECONDS if in_place else HEARTBEAT_SECONDS
    start = time.monotonic()
    done = threading.Event()
    shown = threading.Event()

    def tick() -> None:
        while not done.wait(every):
            elapsed = format_clock(time.monotonic() - start)
            message = f"    processing for {elapsed}"
            if in_place:
                # Return to the line start and clear any longer previous text.
                typer.echo(f"\r{message}\x1b[K", err=True, nl=False, color=True)
                shown.set()
            else:
                typer.echo(message, err=True)

    thread = threading.Thread(target=tick, daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join()
        if shown.is_set():
            typer.echo("\r\x1b[K", err=True, nl=False, color=True)


def confidence_bar(confidence: float) -> str:
    """Draw a 0-1 confidence as a fixed-width bar, e.g. ``██▌░░`` for 0.5."""
    if not math.isfinite(confidence):
        confidence = 0.0
    eighths = round(min(max(confidence, 0.0), 1.0) * BAR_WIDTH * 8)
    full, part = divmod(eighths, 8)
    bar = "█" * full + (_PARTIAL_BLOCKS[part] if part else "")
    return bar.ljust(BAR_WIDTH, "░")


def _fit(text: str, width: int) -> str:
    """Pad ``text`` to ``width``, shortening it with an ellipsis if needed."""
    if len(text) > width:
        text = text[: width - 1] + "…"
    return text.ljust(width)


def show_batch(
    batch: list[MerchantGroup],
    decisions: dict[str, Decision],
    merchant_width: int,
    class_width: int,
) -> None:
    """Print the class and confidence bar chosen for each merchant in a batch.

    Args:
        batch: The groups just classified.
        decisions: Decisions keyed by group key.
        merchant_width: Merchant column width, fixed for the whole run.
        class_width: Class column width, fixed for the whole run.
    """
    for group in batch:
        decision = decisions[group.key]
        confidence = decision.confidence
        percent = f"{confidence:.0%}" if math.isfinite(confidence) else "?"
        typer.echo(
            f"    {_fit(group.merchant, merchant_width)}  →   "
            f"{_fit(decision.klass, class_width)}  "
            f"{confidence_bar(confidence)} {percent:>4} "
            f"[confidence]",
            err=True,
        )


def classify_groups(
    groups: dict[str, MerchantGroup],
    classifier: BatchClassifier,
    store: DecisionCache,
    batch_size: int,
    refresh: bool,
    verify: bool = True,
) -> dict[str, Decision]:
    """Classify each merchant group, using cached decisions where available.

    Args:
        groups: Merchant groups keyed by cache key.
        classifier: Model client used for groups without a cached decision.
        store: Decision cache; updated and saved as batches complete.
        batch_size: Number of groups per model request.
        refresh: Ignore cached model decisions (confirmed ones are kept).
        verify: Classify a second time in a different batch order and lower the
            confidence of groups where the two passes disagree.

    Returns:
        A decision for every group, keyed by cache key.

    Raises:
        ClassifierError: If the model server fails; completed batches stay cached.
    """
    decisions: dict[str, Decision] = {}
    pending = []
    for key, group in groups.items():
        # Type rules are fixed, so they are neither cached nor sent to the model.
        cached = type_rule(group) or store.get(key, refresh=refresh)
        if cached is None:
            pending.append(group)
        else:
            decisions[key] = cached
    # Only ask the server for its model when there is work for it, so a fully
    # cached run never waits on an unreachable server.
    model = classifier.describe_model() if pending else classifier.model
    typer.echo(
        f"{len(groups)} merchants ({len(decisions)} cached, "
        f"{len(pending)} to classify with {model})",
        err=True,
    )

    # Fixed for the whole run so the confidence bars line up across batches.
    merchant_width = min(
        max((len(g.merchant) for g in groups.values()), default=1), MERCHANT_WIDTH
    )
    class_width = min(max(len(c) for c in [*classifier.classes, UNKNOWN]), CLASS_WIDTH)
    for p in range(1, 3 if verify else 2):
        if p == 1:
            order = pending
        else:
            order = [
                group
                for key, group in reversed(groups.items())
                if not decisions[key].confirmed and not decisions[key].verified
            ]
        batches = [order[i : i + batch_size] for i in range(0, len(order), batch_size)]
        for n, batch in enumerate(batches, start=1):
            typer.echo(
                f"  pass {p}/{2 if verify else 1} batch {n}/{len(batches)} "
                f"({len(batch)} merchants)",
                err=True,
            )
            started = time.monotonic()
            with heartbeat():
                results = classifier.classify(batch)
            for group, decision in zip(batch, results, strict=True):
                if p == 2:
                    decision = merge_passes(decisions[group.key], decision)
                decisions[group.key] = decision
                store.put(group.key, decision)
            store.save()
            show_batch(batch, decisions, merchant_width, class_width)
            elapsed = format_duration(time.monotonic() - started)
            typer.echo(f"  batch {n}/{len(batches)} done in {elapsed}", err=True)
    return decisions


def apply_decisions(
    df: pd.DataFrame,
    groups: dict[str, MerchantGroup],
    decisions: dict[str, Decision],
    classes: list[str],
    threshold: float,
) -> None:
    """Write Class, SubClass, Confidence, Source and Review columns in place.

    Unresolved decisions fall back to Income or Expense by direction and are
    marked for review.

    Args:
        df: Transactions with the ``Merchant`` column from ``group_transactions``,
            which is removed.
        groups: Merchant groups keyed by cache key.
        decisions: Decision for every group.
        classes: Known class names.
        threshold: Confidence below which a decision is marked for review.
    """
    klass: dict[str, str] = {}
    review = set()
    for key, group in groups.items():
        decision = decisions[key]
        if needs_clarification(decision, classes, threshold):
            review.add(key)
        if (
            decision.skipped
            or decision.klass == UNKNOWN
            or decision.klass not in classes
        ):
            klass[key] = BASE_CLASSES[0] if group.direction == "in" else BASE_CLASSES[1]
        else:
            klass[key] = decision.klass
    merchant = df.pop("Merchant")
    df["Class"] = merchant.map(klass)
    df["SubClass"] = merchant.map({k: g.merchant for k, g in groups.items()})
    df["Confidence"] = merchant.map({k: d.confidence for k, d in decisions.items()})
    df["Source"] = merchant.map({k: d.source for k, d in decisions.items()})
    df["Review"] = merchant.isin(review)
    # Rule-typed rows keep their fixed class even inside a mixed group.
    fixed = df["Type"].isin(TYPE_CLASSES)
    df.loc[fixed, "Class"] = df.loc[fixed, "Type"].map(TYPE_CLASSES)
    df.loc[fixed, "Confidence"] = 1.0
    df.loc[fixed, "Source"] = "rule"
    df.loc[fixed, "Review"] = False


@app.command()
def clean(
    infile: Annotated[Path, typer.Argument(help="Input CSV file")],
    outfile: Annotated[Path, typer.Argument(help="Output Excel (.xlsx) file")],
    model: Annotated[
        str, typer.Option(help="Hermes model name or agent alias")
    ] = DEFAULT_HERMES_MODEL,
    examples: Annotated[
        Path | None,
        typer.Option(
            help="JSON of example classifications "
            "(default: classifications.json, else classifications.example.json)"
        ),
    ] = None,
    threshold: Annotated[
        float, typer.Option(help="Ask for confirmation below this confidence")
    ] = 0.7,
    batch_size: Annotated[
        int, typer.Option(min=1, help="Merchants per model request")
    ] = 20,
    timeout: Annotated[
        float, typer.Option(min=1, help="Seconds to wait for each model request")
    ] = DEFAULT_TIMEOUT,
    interactive: Annotated[
        bool, typer.Option(help="Prompt to resolve uncertain classifications")
    ] = True,
    cache: Annotated[
        Path, typer.Option(help="File storing decisions between runs")
    ] = DEFAULT_CACHE,
    refresh: Annotated[
        bool, typer.Option(help="Re-ask the model; keep only user-confirmed answers")
    ] = False,
    verify: Annotated[
        bool,
        typer.Option(help="Run a second model pass and ask about disagreements"),
    ] = True,
    api_url: Annotated[
        str,
        typer.Option(envvar="HERMES_API_URL", help="Hermes OpenAI-compatible API URL"),
    ] = DEFAULT_HERMES_URL,
    api_key: Annotated[
        str | None,
        typer.Option(
            envvar="API_SERVER_KEY",
            help="Hermes API key (prefer setting API_SERVER_KEY)",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Classify all transactions and write to an output Excel file."""
    df = pd.read_csv(infile, parse_dates=["Date"], date_format="%d %b %Y")
    # Drop columns not needed and for privacy reasons
    df.drop(columns=["Account Number", "Account Name", "Balance"], inplace=True)

    # Strip whitespace from string columns
    for column in df.columns:
        if pd.api.types.is_string_dtype(df[column]):
            df[column] = df[column].str.strip()

    groups = group_transactions(df)
    store = DecisionCache(cache)
    try:
        classifier = HermesClassifier(
            load_examples(examples),
            api_key=api_key or "",
            url=api_url,
            model=model,
            timeout=timeout,
        )
        classifier.add_classes(store.confirmed_classes())
        classifier.add_classes(TYPE_CLASSES.values())
        decisions = classify_groups(
            groups, classifier, store, batch_size, refresh, verify
        )
    except ClassifierError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e

    uncertain = [
        key
        for key in groups
        if needs_clarification(decisions[key], classifier.classes, threshold)
    ]
    if uncertain and interactive and sys.stdin.isatty():
        typer.echo(f"\n{len(uncertain)} merchants need clarification. Classes:")
        print_classes(classifier.classes)
        # Ask about the largest groups first; they matter most to the totals.
        uncertain.sort(key=lambda k: -abs(groups[k].total))
        for key in uncertain:
            decisions[key] = clarify(groups[key], decisions[key], classifier.classes)
            store.put(key, decisions[key])
            store.save()

    apply_decisions(df, groups, decisions, classifier.classes, threshold)
    if df["Review"].any():
        typer.echo(
            f"{int(df['Review'].sum())} transactions left for review "
            "(Review column in the output).",
            err=True,
        )

    # Sort by date
    df = df.sort_values(by=["Date"])

    # Write the classified transactions to an Excel file
    # Descriptions and class names are untrusted text: never write them as formulas.
    writer = pd.ExcelWriter(
        outfile,
        engine="xlsxwriter",
        datetime_format="yyyy-mm-dd",
        engine_kwargs={"options": {"strings_to_formulas": False}},
    )
    sheet = infile.stem
    # Convert the dataframe to an XlsxWriter Excel object. We also turn off the
    # index column at the left of the output dataframe.
    df.to_excel(writer, sheet_name=sheet, index=False)

    # Get the xlsxwriter workbook and worksheet objects.
    workbook = writer.book
    worksheet = writer.sheets[sheet]

    # Get the dimensions of the dataframe.
    (max_row, max_col) = df.shape

    # Make the columns wider for clarity.
    worksheet.set_column(0, max_col - 1, 12)

    # Set the autofilter.
    worksheet.autofilter(0, 0, max_row, max_col - 1)

    # Format the value
    value_format = workbook.add_format({"num_format": "£#,##0.00;-£#,##0.00"})
    worksheet.set_column("D:D", None, value_format)

    # Autofit the worksheet.
    worksheet.autofit()

    # Close the Pandas Excel writer and output the Excel file.
    writer.close()

    # Create a summary using a pivot table on the classified transactions
    summary = pd.pivot_table(
        df,
        values="Value",
        index=["Class", "SubClass"],
        # columns="Account Number",
        aggfunc="sum",
    )
    # Add Totals to each Class
    summary = pd.concat(
        [
            pd.concat(
                [
                    y,
                    y.sum()
                    .to_frame()
                    .T.set_axis(
                        pd.MultiIndex.from_tuples([(x, "Total")], names=y.index.names)
                    ),
                ]
            )
            for x, y in summary.groupby(level=0)
        ]
    )

    print("Detailed report of transactions:")
    print(summary.to_string())


if __name__ == "__main__":
    app()
