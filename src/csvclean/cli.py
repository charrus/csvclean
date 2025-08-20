"""CLI."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import typer

app = typer.Typer(help="Clean up bank transactions and classify them.")


@app.command()
def clean(
    infile: Path = typer.Argument(..., help="Input CSV file"),
    outfile: Path = typer.Argument(..., help="Output CSV file"),
):
    """Classify all transactions and write to output CSV file."""
    gclasses = {
        "Utility Bill": [
            "UTILITY_BILL_1",
            "UTILITY_BILL_2",
            "UTILITY_BILL_4",
            "UTILITY_BILL_5",
            "UTILITY_BILL_6",
            "UTILITY_BILL_3",
            "REFUNDS_1",
        ],
        "Takeaway": [
            "TAKEAWAY_2",
            "TAKEAWAY_3",
            "TAKEAWAY_4",
            "TAKEAWAY_5",
            "TAKEAWAY_6",
            "TAKEAWAY_7",
            "TAKEAWAY_9",
            "TAKEAWAY_10",
            "TAKEAWAY_11",
            "TAKEAWAY_13",
            "TAKEAWAY_15",
            "TAKEAWAY_16",
            "TAKEAWAY_17",
            "TAKEAWAY_18",
            "TAKEAWAY_19",
            "TAKEAWAY_20",
            "TAKEAWAY_22",
            "TAKEAWAY_23",
            "TAKEAWAY_24",
            "TAKEAWAY_25",
            "TAKEAWAY_26",
            "TAKEAWAY_27",
            "TAKEAWAY_8",
            "TAKEAWAY_1",
            "TAKEAWAY_14",
            "TAKEAWAY_12",
            "TAKEAWAY_21",
        ],
        "Eating Out": [
            "EATING_OUT_1",
            "EATING_OUT_2",
        ],
        "Grocery": [
            "GROCERY_1",
            "GROCERY_2",
            "GROCERY_3",
            "GROCERY_4",
            "GROCERY_5",
            "GROCERY_6",
            "GROCERY_7",
            "GROCERY_8",
            "GROCERY_9",
            "GROCERY_10",
            "GROCERY_11",
            "GROCERY_12",
        ],
        "Pharmacy": [
            "PHARMACY_1",
            "PHARMACY_2",
            "PHARMACY_5",
            "PHARMACY_6",
            "PHARMACY_7",
            "PHARMACY_3",
            "PHARMACY_4",
        ],
        "Home Improvement": [
            "HOME_IMPROVEMENT_2",
            "HOME_IMPROVEMENT_3",
            "HOME_IMPROVEMENT_5",
            "HOME_IMPROVEMENT_7",
            "HOME_IMPROVEMENT_8",
            "HOME_IMPROVEMENT_9",
            "HOME_IMPROVEMENT_11",
            "HOME_IMPROVEMENT_13",
            "HOME_IMPROVEMENT_14",
            "HOME_IMPROVEMENT_15",
            "HOME_IMPROVEMENT_6",
            "HOME_IMPROVEMENT_4",
            "HOME_IMPROVEMENT_10",
            "HOME_IMPROVEMENT_1",
            "HOME_IMPROVEMENT_12",
        ],
        "Internet Subscription": [
            "ONLINE_SUBSCRIPTION_1",
            "INTERNET_SUBSCRIPTION_2",
            "INTERNET_SUBSCRIPTION_3",
            "INTERNET_SUBSCRIPTION_4",
            "INTERNET_SUBSCRIPTION_5",
            "INTERNET_SUBSCRIPTION_6",
            "INTERNET_SUBSCRIPTION_7",
            "INTERNET_SUBSCRIPTION_8",
            "INTERNET_SUBSCRIPTION_9",
            "INTERNET_SUBSCRIPTION_10",
            "INTERNET_SUBSCRIPTION_11",
            "INTERNET_SUBSCRIPTION_12",
            "INTERNET_SUBSCRIPTION_13",
            "INTERNET_SUBSCRIPTION_14",
            "INTERNET_SUBSCRIPTION_15",
            "INTERNET_SUBSCRIPTION_16",
            "INTERNET_SUBSCRIPTION_1",
        ],
        "Car": [
            "CAR_1",
            "CAR_2",
            "CAR_3",
            "CAR_4",
            "CAR_5",
            "PARKING_2",
            "PARKING_1",
        ],
        "CC Service Charge": [
            "CC_SERVICE_CHARGE_2",
            "CC_SERVICE_CHARGE_1",
        ],
        "Online Shopping": [
            "ONLINE_SHOPPING_1",
            "ONLINE_SHOPPING_2",
        ],
        "Vape Supplies": [
            "VAPE_SUPPLIES_4",
            "VAPE_SUPPLIES_7",
            "VAPE_SUPPLIES_6",
            "VAPE_SUPPLIES_2",
            "VAPE_SUPPLIES_5",
            "VAPE_SUPPLIES_1",
            "VAPE_SUPPLIES_8",
            "VAPE_SUPPLIES_3",
        ],
        "Hobbies": [
            "HOBBIES_11",
            "HOBBIES_10",
            "HOBBIES_14",
            "HOBBIES_8",
            "HOBBIES_5",
            "HOBBIES_13",
            "HOBBIES_3",
            "HOBBIES_2",
            "HOBBIES_9",
            "HOBBIES_7",
            "HOBBIES_16",
            "HOBBIES_6",
            "HOBBIES_15",
            "HOBBIES_1",
            "HOBBIES_4",
            "HOBBIES_12",
        ],
        "Gifts": [
            "GIFTS_7",
            "GIFTS_9",
            "GIFTS_3",
            "GIFTS_4",
            "GIFTS_1",
            "GIFTS_8",
            "GIFTS_6",
            "SOCIAL_2",
            "SOCIAL_1",
            "GIFTS_2",
            "GIFTS_5",
        ],
        "Joint Mortgage": [
            "JOINT_MORTGAGE_2",
            "JOINT_MORTGAGE_1",
        ],
        "Clothing": [
            "CLOTHING_2",
            "CLOTHING_1",
        ],
        "Transport": [
            "TRANSPORT_1",
            "TRANSPORT_2",
        ],
        "Education": [
            "EDUCATION_2",
            "EDUCATION_1",
        ],
        "Salary Income": [
            "SALARY_INCOME_1",
            "WELFARE_INCOME_1",
        ],
        "Rental Income": [
            "RENTAL_INCOME_1",
        ],
        "Shares Income": [
            "SHARES_INCOME_1",
        ],
        "Service Charge": [
            "SERVICE_CHARGE_1",
        ],
        "Mortgage Interest": [
            "MORTGAGE_INTEREST_1",
        ],
        "Landlords Insurance": [
            "LANDLORDS_INSURANCE_1",
        ],
        "Council Tax": [
            "COUNCIL_TAX_1",
        ],
        "Contents Insurance": [
            "CONTENTS_INSURANCE_1",
        ],
        "Credit Report": [
            "CREDIT_REPORT_1",
        ],
        "Veterinary": [
            "VETERINARY_1",
        ],
        "Accountant": [
            "ACCOUNTANT_1",
        ],
        "Legal": [
            "LEGAL_1",
            "LEGAL_2",
        ],
        "Health Insurance": [
            "HEALTH_INSURANCE_1",
        ],
        "Tax": [
            "TAX_1",
        ],
        "Investments": [
            "INVESTMENTS_1",
        ],
        "Transfers": [
            "To A/C ",
            "From A/C ",
        ],
        "Currency": [
            "CURRENCY_1",
        ],
    }

    df = pd.read_csv(infile, parse_dates=["Date"], date_format="%d %b %Y")
    # Drop columns not needed and for privacy reasons
    df.drop(columns=["Account Number", "Account Name", "Balance"], inplace=True)

    # Strip whitespace from string columns
    for column in df.columns:
        if isinstance(df[column].dtype, pd.StringDtype):
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
    df["SubClass"] = np.where(
        cash_machine,
        df["Description"].str.replace(r" [0-9]{2}[A-Z]{3}$", "", regex=True),
        "",
    )

    # Expense classes and subclasses
    for txn_type in gclasses.keys():
        for txn_sub_type in gclasses[txn_type]:
            class_mask = df["Description"].str.contains(txn_sub_type)
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
        [y._append(y.sum().rename((x, "Total"))) for x, y in summary.groupby(level=0)]
    )

    print("Detailed report of transactions:")
    print(summary.to_string())
