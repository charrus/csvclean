# txnclassify

A Python CLI tool for cleaning and classifying bank transaction CSV files. A language model served by [Ollama](https://ollama.com) categorizes transactions into meaningful classes (e.g., Grocery, Utility Bill, Takeaway), asks you when it is unsure, and generates detailed Excel reports with summaries.

## Features

- **LLM Classification**: An Ollama model classifies each merchant, guided by your example categories rather than exact keyword rules, so new merchants need no configuration
- **Asks When Unsure**: Low-confidence answers, and merchants where two independent model passes disagree, are put to you interactively
- **Remembers Decisions**: Model answers and your confirmations are cached, so re-runs are fast and you are never asked the same question twice
- **Excel Output**: Generates formatted Excel files with autofilters and proper formatting
- **Summary Reports**: Creates pivot table summaries showing totals by category and subcategory
- **Date Parsing**: Handles date formats from bank exports
- **Data Privacy**: Removes sensitive columns (Account Number, Account Name, Balance)

## Installation

### Prerequisites

- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) package manager
- An [Ollama](https://ollama.com) server with a model pulled (default `gemma4:e2b`)

### Install uv

```bash
# On Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# On macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Install from source

```bash
# Clone the repository
git clone <repository-url>
cd txnclassify

# Install the package (uv will automatically create a virtual environment)
uv sync

# Run the CLI
uv run txnclassify --help
```

## Usage

### Basic Command

```bash
uv run txnclassify <input-csv-file> <output-excel-file>
```

Or, if you've activated the virtual environment:
```bash
txnclassify <input-csv-file> <output-excel-file>
```

### Example

```bash
uv run txnclassify transactions.csv transactions-clean.xlsx
```

This will:
1. Read the input CSV file
2. Group transactions by merchant (stripping card numbers, dates and references)
3. Classify each merchant with the Ollama model, in batches, twice
4. Ask you to confirm merchants the model is unsure about
5. Generate an Excel file with classified transactions
6. Print a summary report to the console

The first run on a year of transactions (~200 merchants) takes a few minutes;
later runs reuse cached decisions and only classify new merchants.

### Options

| Option | Default | Description |
| --- | --- | --- |
| `--ollama-url` | `$OLLAMA_HOST`, else the project server | Ollama server URL (`host:port` is accepted) |
| `--model` | `gemma4:e2b` | Model to use |
| `--examples` | `classifications.json`, else `classifications.example.json` | Example categories to guide the model |
| `--threshold` | `0.7` | Ask about decisions below this confidence |
| `--batch-size` | `20` | Merchants per model request |
| `--no-interactive` | | Never prompt; uncertain rows are marked in the `Review` column |
| `--no-verify` | | Skip the second model pass (about half the time, fewer questions caught) |
| `--cache` | `~/.cache/txnclassify/decisions.json` | Where decisions are stored between runs |
| `--refresh` | | Re-ask the model, keeping only answers you confirmed |

### Clarification prompts

When a merchant needs clarification you see sample descriptions, the model's
answer, any alternatives and its reason. Then:

- **Enter** accepts the suggestion (or skips if there is none)
- a **number** picks a class from the list (`?` reprints the list)
- a **name** picks a class, or creates a new one that is remembered for future runs
- **s** skips; the rows fall back to `Income`/`Expense` and are marked for review

### Input CSV Format

The tool expects CSV files with the following columns:
- `Date` (format: "DD MMM YYYY", e.g., "17 Aug 2025")
- `Type` (transaction type code)
- `Description` (merchant/transaction description)
- `Value` (transaction amount)
- `Account Number` (will be removed)
- `Account Name` (will be removed)
- `Balance` (will be removed)

## Transaction Categories

The tool classifies transactions into customizable categories. Here are some example categories:

### Expenses
- **Utility Bill**: Energy, internet, water, phone
- **Takeaway**: Fast food and food delivery
- **Eating Out**: Restaurants and bars
- **Grocery**: Supermarkets and food stores
- **Pharmacy**: Pharmacies and health products
- **Home Improvement**: Hardware, furniture, repairs
- **Subscriptions**: Streaming services, software, digital services
- **Transport**: Car expenses, public transport, taxis, parking
- **Online Shopping**: Online retailers and marketplaces
- **Personal Care**: Personal products and services
- **Hobbies**: Electronics, entertainment, hobby supplies
- **Gifts**: Gift shops and personal transfers
- **Clothing**: Clothing and sportswear
- **Education**: Online courses and learning platforms
- **Housing Costs**: Service charges, maintenance, insurance
- **Professional Services**: Accountant, legal, financial services
- **Insurance**: Various insurance types
- **Tax**: Tax authority payments

### Income
- **Salary**: Employment income
- **Investment Income**: Dividends, rental income, interest
- **Other Income**: Government benefits, refunds

### Other
- **Cash Withdrawals**: ATM transactions
- **Transfers**: Account transfers
- **Currency Exchange**: Foreign exchange transactions

## Use Cases

### Filing a UK Tax Return (Self-Assessment)

This tool is particularly useful for preparing self-assessment tax returns by automatically categorizing your transactions into allowable expense categories.

**Example Setup for Self-Employed/Landlords:**

1. Configure your classifications to match HMRC expense categories:
   ```json
   {
     "Office Costs": ["STATIONERY_SHOP", "PRINTER_INK", "OFFICE_SUPPLIES"],
     "Travel Costs": ["TRAIN_STATION", "FUEL_STATION", "PARKING"],
     "Premises Costs": ["INSURANCE_CO", "REPAIRS", "UTILITIES"],
     "Professional Fees": ["ACCOUNTANT", "SOLICITOR", "PROFESSIONAL_BODY"],
     "Marketing": ["ADVERTISING", "WEBSITE_HOSTING", "BUSINESS_CARDS"],
     "Staff Costs": ["PAYROLL", "RECRUITMENT_AGENCY"],
     "Business Income": ["CLIENT_PAYMENT", "INVOICE_REFERENCE"],
     "Rental Income": ["LETTING_AGENT"],
     "Rental Expenses": ["PROPERTY_MANAGEMENT", "REPAIRS", "INSURANCE"]
   }
   ```

2. Export your bank statements as CSV files

3. Run the classifier:
   ```bash
   uv run txnclassify bank-2024-25.csv tax-summary.xlsx
   ```

4. Review the Excel output with categorized transactions

5. Use the summary pivot table totals for your tax return form

**Benefits:**
- ✅ Automatic categorization saves hours of manual work
- ✅ Consistent classification reduces errors
- ✅ Easy to verify transactions by category
- ✅ Provides audit trail for HMRC compliance
- ✅ Calculates totals automatically
- ✅ Separates personal vs business transactions

**Note:** Always review categorized transactions before using them for tax purposes. Consult with an accountant if unsure about expense allowability.

## Output

### Excel File
The output Excel file includes:
- Formatted date column (YYYY-MM-DD)
- Currency formatting for values (£#,##0.00)
- Autofilter on all columns
- Auto-fitted column widths
- New columns: `Class`, `SubClass` (the normalised merchant), `Confidence`,
  `Source` (`llm`, `user` or `cache`) and `Review` (true for unresolved rows)

### Console Summary
A pivot table summary showing:
- Total spending/income by category
- Breakdown by subcategory
- Category totals

Example output:
```
Detailed report of transactions:
                                    Value
Class                SubClass
Expense              SUPERMARKET_1   -450.23
                     SUPERMARKET_2   -320.15
                     Total           -770.38
Grocery              LOCAL_SHOP      -150.00
                     Total           -150.00
...
```

## Development

### Setup Development Environment

```bash
# Install with dev dependencies (automatically handled by uv sync)
uv sync --group dev

# Run linter
uv run ruff check src/

# Run type checker
uv run mypy src/

# Run tests
uv run pytest

# Format code
uv run ruff format src/ tests/
```

### Code Quality Tools

- **Ruff**: Fast Python linter and formatter
- **MyPy**: Static type checker with strict configuration

## Customization

### Setting Up Your Example Classifications

The JSON file is no longer a set of matching rules. Its keys are the categories
the model may choose from, and the keywords are examples showing what each
category means to you. A transaction containing an example keyword is hinted
to the model, and if the model disagrees you are asked.

1. Copy the example file to create your personal classifications:
   ```bash
   cp classifications.example.json src/txnclassify/classifications.json
   ```

2. Edit `src/txnclassify/classifications.json` with your merchant names and categories:
   ```json
   {
     "Category Name": [
       "MERCHANT_KEYWORD_1",
       "MERCHANT_KEYWORD_2"
     ],
     "Another Category": [
       "KEYWORD_3"
     ]
   }
   ```

3. A handful of representative merchants per category is enough; the model
   generalises to merchants that are not listed. Categories you create at a
   prompt are stored in the decision cache, not in this file.

**Note:** Your personal `classifications.json` file is gitignored to protect your privacy. Only the anonymized example file is tracked in version control. Transaction descriptions are sent to the Ollama server you configure, so use one you control.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

Charlie Rusbridger (charlie@rusbridger.com)
