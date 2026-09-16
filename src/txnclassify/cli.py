"""CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

app = typer.Typer(help="Clean up bank transactions and classify them.")


def load_classifications() -> dict[str, list[str]]:
    """Load transaction classifications from JSON file.

    Returns:
        Dictionary mapping transaction classes to lists of keywords.
    """
    classifications_path = Path(__file__).parent / "classifications.json"
    with open(classifications_path, encoding="utf-8") as f:
        data: dict[str, list[str]] = json.load(f)
        return data


@app.command()
def clean(
    infile: Annotated[Path, typer.Argument(help="Input CSV file")],
    outfile: Annotated[Path, typer.Argument(help="Output Excel (.xlsx) file")],
) -> None:
    """Classify all transactions and write to an output Excel file."""
    gclasses = load_classifications()

    df = pd.read_csv(infile, parse_dates=["Date"], date_format="%d %b %Y")
    # Drop columns not needed and for privacy reasons
    df.drop(columns=["Account Number", "Account Name", "Balance"], inplace=True)

    # Strip whitespace from string columns
    for column in df.columns:
        if pd.api.types.is_string_dtype(df[column]):
            df[column] = df[column].str.strip()

    # Defaults for Income and Expense Classes
    df.loc[df["Value"] > 0, "Class"] = "Income"
    df.loc[df["Value"] < 0, "Class"] = "Expense"
    df["SubClass"] = ""
    # Interest
    df.loc[df["Type"] == "INT", "Class"] = "Interest"

    # Cash Machine (Use Description for SubClass after tidying up by removing the
    # DDMMM suffix) - Might be useful to break them down by type of Cash machine.
    cash_machine = df["Type"] == "C/L"
    df.loc[cash_machine, "Class"] = "Cash Machine"
    df.loc[cash_machine, "SubClass"] = df.loc[cash_machine, "Description"].str.replace(
        r" [0-9]{2}[A-Z]{3}$", "", regex=True
    )

    # Expense classes and subclasses
    for txn_type in gclasses.keys():
        for txn_sub_type in gclasses[txn_type]:
            class_mask = df["Description"].str.contains(
                txn_sub_type, regex=False, na=False
            )
            df.loc[class_mask, "Class"] = txn_type
            # Use the string matched in Description for the SubClass to
            # see a breakdown of transactions for the Class:
            df.loc[class_mask, "SubClass"] = txn_sub_type.strip()

    # Sort by date
    df = df.sort_values(by=["Date"])

    # Write the classified transactions to an Excel file
    writer = pd.ExcelWriter(outfile, engine="xlsxwriter", datetime_format="yyyy-mm-dd")
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
