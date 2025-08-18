from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pandas as pd
import typer

app = typer.Typer(help="Clean up bank transactions and classify them.")


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
    """Classify all transactions and write to output CSV file."""
    classes = {
        "SALARY_INCOME_1": "Salary Income",
        "RENTAL_INCOME_1": "Rental Income",
        "SHARES_INCOME_1": "Shares Income",
        "REFUND": "Refunds",
        "WELFARE_INCOME_1": "Welfare Income",
        "JOINT_MORTGAGE_2": "Joint Mortgage",
        "SERVICE_CHARGE_1": "Service Charge",
        "JOINT_MORTGAGE_1": "Joint Mortgage",
        "MORTGAGE_INTEREST_1": "Mortgage Interest",
        "LANDLORDS_INSURANCE_1": "Landlords Insurance",
        "COUNCIL_TAX_1": "Council Tax",
        "CC_SERVICE_CHARGE_2": "CC Service Charge",
        "CC_SERVICE_CHARGE_1": "CC Service Charge",
        "UTILITY_BILL_1": "Utility Bill",
        "CONTENTS_INSURANCE_1": "Contents Insurance",
        "UTILITY_BILL_6": "Utility Bill",
        "UTILITY_BILL_2": "Utility Bill",
        "CAR_2": "Car",
        "UTILITY_BILL_5": "Utility Bill",
        "UTILITY_BILL_4": "Utility Bill",
        "HOME_IMPROVEMENT_13": "Home Improvement",
        "ONLINE_SHOPPING_1": "Online Shopping",
        "ONLINE_SHOPPING_2": "Online Shopping",
        "ONLINE_SUBSCRIPTION_1": "Online Subscription",
        "TRANSPORT_1": "Transport",
        "TRANSPORT_2": "Transport",
        "UTILITY_BILL_3": "Utility Bill",
        "TAKEAWAY_6": "Takeaway",
        "TAKEAWAY_26": "Takeaway",
        "TAKEAWAY_15": "Takeaway",
        "TAKEAWAY_19": "Takeaway",
        "TAKEAWAY_18": "Takeaway",
        "TAKEAWAY_4": "Takeaway",
        "TAKEAWAY_11": "Takeaway",
        "TAKEAWAY_7": "Takeaway",
        "TAKEAWAY_27": "Takeaway",
        "TAKEAWAY_9": "Takeaway",
        "TAKEAWAY_13": "Takeaway",
        "TAKEAWAY_17": "Takeaway",
        "TAKEAWAY_22": "Takeaway",
        "TAKEAWAY_25": "Takeaway",
        "TAKEAWAY_20": "Takeaway",
        "TAKEAWAY_10": "Takeaway",
        "TAKEAWAY_5": "Takeaway",
        "TAKEAWAY_2": "Takeaway",
        "TAKEAWAY_16": "Takeaway",
        "TAKEAWAY_23": "Takeaway",
        "TAKEAWAY_3": "Takeaway",
        "TAKEAWAY_24": "Takeaway",
        "GROCERY_10": "Grocery",
        "GROCERY_11": "Grocery",
        "GROCERY_8": "Grocery",
        "GROCERY_1": "Grocery",
        "GROCERY_6": "Grocery",
        "GROCERY_5": "Grocery",
        "GROCERY_3": "Grocery",
        "GROCERY_12": "Grocery",
        "GROCERY_9": "Grocery",
        "GROCERY_7": "Grocery",
        "GROCERY_4": "Grocery",
        "GROCERY_2": "Grocery",
        "PHARMACY_2": "Pharmacy",
        "PHARMACY_5": "Pharmacy",
        "PHARMACY_1": "Pharmacy",
        "PHARMACY_6": "Pharmacy",
        "PHARMACY_7": "Pharmacy",
        "HOME_IMPROVEMENT_7": "Home Improvement",
        "HOME_IMPROVEMENT_5": "Home Improvement",
        "HOME_IMPROVEMENT_15": "Home Improvement",
        "HOME_IMPROVEMENT_11": "Home Improvement",
        "HOME_IMPROVEMENT_8": "Home Improvement",
        "HOME_IMPROVEMENT_2": "Home Improvement",
        "HOME_IMPROVEMENT_9": "Home Improvement",
        "HOME_IMPROVEMENT_3": "Home Improvement",
        "CREDIT_REPORT_1": "Credit Report",
        "INTERNET_SUBSCRIPTION_9": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_11": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_16": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_7": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_4": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_15": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_5": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_13": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_3": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_10": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_12": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_14": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_6": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_2": "Internet Subscription",
        "INTERNET_SUBSCRIPTION_8": "Internet Subscription",
        "EDUCATION_2": "Education",
        "HOME_IMPROVEMENT_14": "Home Improvement",
        "PARKING_2": "Parking",
        "PARKING_1": "Parking",
        "VETERINARY_1": "Veterinary",
        "ACCOUNTANT_1": "Accountant",
        "CAR_4": "Car",
        "CAR_1": "Car",
        "CAR_3": "Car",
        "CAR_5": "Car",
        "LEGAL_1": "Legal",
        "LEGAL_2": "Legal",
        "HEALTH_INSURANCE_1": "Health Insurance",
        "CLOTHING_2": "Clothing",
        "TAX_1": "Tax",
        "SOCIAL_2": "Social",
        "SOCIAL_1": "Social",
        "INVESTMENTS_1": "Investments",
    }
    income_classes = {
        "To A/C ": "Transfer Income To",
        "From A/C ": "Transfer Income From",
        "REFUNDS_1": "Refunds",
    }
    expense_classes = {
        "To A/C ": "Transfer Expense To",
        "From A/C ": "Transfer Expense From",
        "REFUNDS_1": "Utility Bill",
        "HOME_IMPROVEMENT_10": "Home Improvement",
    }

    reader = pd.read_csv(infile, parse_dates=["Date"], date_format="%d %b %Y")
    # Strip whitespace from string columns
    for column in reader.columns:
        if isinstance(reader[column].dtype, pd.StringDtype):
            reader[column] = reader[column].str.strip()

    # Defaults for Income and Expense Classes
    reader.loc[reader["Value"] > 0, "Class"] = "Income"
    reader.loc[reader["Value"] < 0, "Class"] = "Expense"
    # Interest
    reader.loc[reader["Type"] == "INT", "Class"] = "Interest"
    # Cash Machine
    reader.loc[reader["Type"] == "C/L", "Class"] = "Cash Machine"

    # Income and Expense Classes
    for description, class_name in classes.items():
        reader.loc[reader["Description"].str.contains(description), "Class"] = (
            class_name
        )
    # Special cases for income classes
    for description, class_name in income_classes.items():
        reader.loc[
            (reader["Value"] > 0) & (reader["Description"].str.contains(description)),
            "Class",
        ] = class_name
    # Special cases for expense classes
    for description, class_name in expense_classes.items():
        reader.loc[
            (reader["Value"] < 0) & (reader["Description"].str.contains(description)),
            "Class",
        ] = class_name

    reader.to_csv(outfile, index=False)

    summary = reader.groupby("Class")["Value"].sum()

    print("Summary of transactions by class:")
    for class_name, total in summary.items():
        print(f" - {class_name}: {total:,.2f}")
