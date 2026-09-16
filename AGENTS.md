# AGENTS.md

Guidance for AI coding agents working in this repository.

## What this is

`txnclassify` — a single-command Python CLI that reads a bank transaction CSV
export, tags each row with a `Class` and `SubClass` by keyword-matching the
`Description`, writes a formatted `.xlsx`, and prints a pivot-table summary to
stdout. See `README.md` for user-facing docs.

The project was renamed from `csvclean` to `txnclassify` (commit `4c7203f`).
The git repo directory and some stale artifacts still say `csvclean`; the
package, script, and module names are all `txnclassify`.

## Layout

```
src/txnclassify/cli.py               all logic — one Typer command, ~130 lines
src/txnclassify/classifications.json keyword map: {"Class": ["MERCHANT", ...]}
classifications.example.json         anonymized template of the above
```

There is no test suite and no `tests/` directory. Verify changes by running the
CLI against a real CSV and diffing the output (see Verifying below).

## Commands

This project uses [uv](https://github.com/astral-sh/uv). Always prefix with
`uv run`, or use `.venv/bin/python` directly.

```bash
uv sync                      # install, including dev group
uv run txnclassify IN.csv OUT.xlsx
uv run python -m txnclassify.cli IN.csv OUT.xlsx   # equivalent

uv run ruff format src/      # must be clean before committing
uv run ruff check src/
uv run mypy src/
```

Run all three of `ruff format`, `ruff check`, and `mypy` before claiming a
change is done. mypy is configured strictly (`disallow_untyped_defs`,
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

**Known issue:** `src/txnclassify/classifications.json` is already tracked in
git despite being listed in `.gitignore` — gitignore does not apply to
already-tracked files. The committed version contains real merchant names.
Untracking it needs `git rm --cached` plus a history rewrite; ask the maintainer
before touching this.

## Conventions

- Line length 88, double quotes, google-style docstrings (ruff `D` rules are on,
  so every public function needs one).
- Prefer `df.loc[mask, col] = ...` over `np.where` for conditional column
  assignment — it reads better and avoids a numpy dependency for one call.
- Keyword matching uses `str.contains(..., regex=False, na=False)`. Keep both
  flags: patterns in `classifications.json` contain literal `.` characters
  (`MERCHANT.COM/BILL`), and a null `Description` otherwise yields `NA` and makes
  the subsequent `.loc` raise.
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

`NatWest-download-20250817.csv` (1576 rows, untracked, local only) is the
reference input. To prove a refactor is behaviour-preserving, generate output
before and after and diff the dataframes:

```bash
uv run txnclassify NatWest-download-20250817.csv /tmp/new.xlsx
git stash && uv run txnclassify NatWest-download-20250817.csv /tmp/old.xlsx; git stash pop
uv run python -c "
import pandas as pd
a, b = pd.read_excel('/tmp/old.xlsx'), pd.read_excel('/tmp/new.xlsx')
print('rows differing:', int(a.fillna('').ne(b.fillna('')).any(axis=1).sum()))"
```

Write outputs to a temp directory, not the repo — `NatWest-download-20250817.xlsx`
in the project root is an existing local artifact, don't clobber it.
