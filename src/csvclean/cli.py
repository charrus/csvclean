from __future__ import annotations

import csv
from pathlib import Path
from datetime import datetime

import typer

app = typer.Typer(
    help="Clean messy CSVs: trim headers, strip whitespace, drop empties, and dedupe."
)


def _open_csv(path: Path):
    return csv.DictReader(path.open("r", newline="", encoding="utf-8-sig"))


def _write_csv(path: Path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


@app.command()
def clean(
    infile: Path = typer.Argument(..., help="Input CSV file"),
    outfile: Path = typer.Argument(..., help="Output CSV file"),
):
    """Clean a CSV and write the result."""
    reader = _open_csv(infile)
    # Normalize headers
    fieldnames = [h.strip() for h in (reader.fieldnames or [])]
    cleaned_rows = []
    for row in reader:
        normalized = {
            k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()
        }
        if all(
            (v is None or (isinstance(v, str) and v.strip() == ""))
            for v in normalized.values()
        ):
            continue
        normalized["Class"] = ""
        normalized["Date"] = (
            datetime.strptime(normalized["Date"], "%d %b %Y").date().isoformat()
        )
        if normalized.get("Type") == "INT":
            normalized["Class"] = "Interest"
        elif normalized["Description"].startswith("To A/C ") or normalized[
            "Description"
        ].startswith("From A/C "):
            normalized["Class"] = "Transfer"
        elif float(normalized.get("Value")) > 0:
            normalized["Class"] = "Income"
            if "SALARY_INCOME_1" in normalized["Description"]:
                normalized["Class"] = "Salary Income"
            elif "RENTAL_INCOME_1" in normalized["Description"]:
                normalized["Class"] = "Rental Income"
            elif "SHARES_INCOME_1" in normalized["Description"]:
                normalized["Class"] = "Shares Income"
            elif (
                "REFUND" in normalized["Description"]
                or "REFUNDS_1" in normalized["Description"]
            ):
                normalized["Class"] = "Refund Income"
            elif "WELFARE_INCOME_1" in normalized["Description"]:
                normalized["Class"] = "Salary Income"
            elif "JOINT_MORTGAGE_2" in normalized["Description"]:
                normalized["Class"] = "Joint Mortgage"
        else:
            normalized["Class"] = "Expense"
            if "SERVICE_CHARGE_RENT" in normalized["Description"]:
                normalized["Class"] = "Service Charge"
            elif "MORTGAGE_INTEREST_1" in normalized["Description"]:
                normalized["Class"] = "Mortgage Interest"
            elif "LANDLORDS_INSURANCE_1" in normalized["Description"]:
                normalized["Class"] = "Landlords Insurance"
            elif "JOINT_MORTGAGE_1" in normalized["Description"]:
                normalized["Class"] = "Joint Mortgage"
        cleaned_rows.append(normalized)
    if cleaned_rows:
        fieldnames = list(cleaned_rows[0].keys())
    _write_csv(outfile, cleaned_rows, fieldnames)
    typer.echo(f"Cleaned {len(cleaned_rows)} rows → {outfile}")
