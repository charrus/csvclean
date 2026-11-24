# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this is

`txnclassify` — a single-command Python CLI that reads a bank transaction CSV
export, groups rows by normalised merchant, asks Hermes Agent for each
group's `Class` (with interactive clarification when uncertain), writes a
formatted `.xlsx`, and prints a pivot-table summary to stdout. See `README.md` for user-facing docs.

The project was renamed from `csvclean` to `txnclassify` (commit `4c7203f`).
The git repo directory and some stale artifacts still say `csvclean`; the
package, script, and module names are all `txnclassify`.

## Layout

```
src/txnclassify/cli.py               Typer command: load, group, clarify, write Excel
src/txnclassify/llm.py               merchant normalisation, Hermes client, cache
src/txnclassify/classifications.json example map: {"Class": ["MERCHANT", ...]}
classifications.example.json         anonymized template of the above
tests/                               pytest unit tests (no network)
~/.cache/txnclassify/decisions.json  model and user decisions (outside the repo)
```

## Classification pipeline

1. `normalise_merchant` strips card prefixes, `FP` references, dates, trailing
   card-payment locations and reference-like tokens; rows group by `direction|merchant`.
2. `TYPE_CLASSES` in `cli.py` fixes the class for some transaction types
   (`INT` → `Interest`): all-`INT` groups skip the cache, model and prompts, and
   `apply_decisions` overrides those rows even inside mixed groups.
   `DecisionCache` supplies prior decisions. User-confirmed ones always win and
   survive `--refresh`.
3. `BatchClassifier.classify` shares prompts, validation and retries.
   `HermesClassifier` posts to `/v1/chat/completions` with bearer authentication
   (`API_SERVER_KEY` only; generic `OPENAI_*` variables are deliberately ignored). Hermes does not enforce a
   response schema, so it is included in the prompt and checked locally. The allowed classes are the example classes +
   `Income`/`Expense` + `Unknown`. Incomplete replies are retried, then sent singly.
   Chat replies only name the `hermes-agent` alias, so `describe_model` reads
   the real model from `GET /api/model/options` for the start-up line, falling
   back to the alias on any error.
4. Two passes run in different batch orders; `merge_passes` caps confidence at
   0.4 on disagreement. Contradicting an `example_match` caps it at 0.5.
5. `needs_clarification` → interactive `clarify` → `apply_decisions`.
   Skips retain the suggestion for future prompts, but output Income/Expense with
   Review=True. Cache entries persist `skipped` and `verified` flags. Each batch
   is saved immediately; unverified cached decisions resume at the second pass.
   Legacy cache entries without `verified` are verified on their next run.

Why two passes: the model's self-reported confidence is near-constant (~0.9)
whether right or wrong, and logprobs didn't help either (measured on Ollama,
whose support was removed in favour of Hermes). Pass disagreement and example
contradiction are the signals that actually correlate with errors.

Unit tests inject a fake `post`/`get` or patch the HTTP transport; never make them
hit the network. An autouse fixture in `tests/conftest.py` makes any real
`urlopen` call fail. End-to-end behaviour still needs a run against a real CSV.

## Commands

This project uses [uv](https://github.com/astral-sh/uv). Always prefix with
`uv run`, or use `.venv/bin/python` directly.

```bash
uv sync                      # install, including dev group
uv run txnclassify IN.csv OUT.xlsx
uv run python -m txnclassify.cli IN.csv OUT.xlsx   # equivalent

uv run ruff format src/ tests/   # must be clean before committing
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest
```

Run all four before claiming a change is done. mypy is configured strictly (`disallow_untyped_defs`,
`warn_unreachable`, `warn_unused_ignores`), so a stale `# type: ignore` is an
error, not a warning.

## Privacy constraints

This repo holds one person's real bank data. Treat that as a hard constraint.

- **Never commit** `.csv` or `.xlsx` files, or the real
  `src/txnclassify/classifications.json` — it contains actual merchant names.
  `.gitignore` covers all three patterns.
- When editing docs or examples, use the anonymized placeholders from
  `classifications.example.json` (`ENERGY_PROVIDER`, `SUPERMARKET_1`), never
  real merchant names.
- `README.md` was deliberately anonymized in commit `f3c6d32`. Don't reintroduce
  real categories or merchants into it.

**History was scrubbed on 2026-09-16.** `classifications.json` was removed from
all commits, and the payee names that earlier commits hardcoded in `cli.py` (plus
three real supermarket names in the README example) were replaced with anonymized
placeholders. The file is now untracked and ignored. Don't re-add it to git.

## Conventions

- Line length 88, double quotes, google-style docstrings (ruff `D` rules are on,
  so every public function needs one).
- Prefer `df.loc[mask, col] = ...` over `np.where` for conditional column
  assignment — it reads better and avoids a numpy dependency for one call.
- Example keywords are matched as case-insensitive plain substrings (not regex):
  they contain literal `.` characters (`MERCHANT.COM/BILL`).
- Never commit the decision cache or point `--cache` inside the repo; it holds
  real merchant names.
- Files use **LF** line endings. There is no `.gitattributes` and
  `core.autocrlf` is `false`, so a CRLF save shows up as a whole-file rewrite
  that buries the real diff.

## pandas gotchas

`pandas>=2.3.1` is pinned without an upper bound, and `pandas-stubs>=3.0.0` is
already a dependency, so assume a pandas 3 resolve is possible.

- **Don't test dtypes by equality.** `df[col].dtype == "object"` is true on
  pandas 2 but false on pandas 3, where `read_csv` infers `str`
  (`future.infer_string`). Use `pd.api.types.is_string_dtype(df[col])`.
- **Preserve MultiIndex names** when appending aggregate rows. Building a row
  with `.rename(tuple).to_frame().T` flattens the index and silently drops the
  `Class`/`SubClass` header from the printed report. Use
  `pd.MultiIndex.from_tuples([...], names=y.index.names)`.
- Run suspicious changes under `-W error::FutureWarning` to catch deprecations.

## Verifying a change

`NatWest-download-20250817.csv` (1576 rows, ~213 merchant groups, untracked,
local only) is the reference input. A full uncached run took ~5.5 minutes on
the former Ollama backend; Hermes timing depends on its configured model. Set
`API_SERVER_KEY` and `HERMES_API_URL`, and always pass a scratch `--cache` so you don't touch the user's real
decisions. Model output is not deterministic across batch compositions, so
compare classification quality (agreement rate with a previous output, rows
flagged for review) rather than expecting zero diff. To diff two outputs:

```bash
uv run txnclassify NatWest-download-20250817.csv /tmp/new.xlsx --no-interactive --cache /tmp/new-cache.json
git stash && uv run txnclassify NatWest-download-20250817.csv /tmp/old.xlsx --no-interactive --cache /tmp/old-cache.json; git stash pop
uv run python -c "
import pandas as pd
a, b = pd.read_excel('/tmp/old.xlsx'), pd.read_excel('/tmp/new.xlsx')
print('rows differing:', int(a.fillna('').ne(b.fillna('')).any(axis=1).sum()))"
```

Write outputs to a temp directory, not the repo — `NatWest-download-20250817.xlsx`
in the project root is an existing local artifact, don't clobber it.
