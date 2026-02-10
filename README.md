# txnclassify

A Python CLI tool for cleaning and classifying bank transaction CSV files. Automatically categorizes transactions into meaningful classes (e.g., Grocery, Utility Bill, Takeaway) and generates detailed Excel reports with summaries.

## Features

- **Automatic Classification**: Classifies transactions into 30+ categories based on merchant names
- **Excel Output**: Generates formatted Excel files with autofilters and proper formatting
- **Summary Reports**: Creates pivot table summaries showing totals by category and subcategory
- **Date Parsing**: Handles date formats from bank exports
- **Data Privacy**: Removes sensitive columns (Account Number, Account Name, Balance)

## Installation

### Prerequisites

- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) package manager

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
2. Classify all transactions
3. Generate an Excel file with classified transactions
4. Print a summary report to the console

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

## Output

### Excel File
The output Excel file includes:
- Formatted date column (YYYY-MM-DD)
- Currency formatting for values (£#,##0.00)
- Autofilter on all columns
- Auto-fitted column widths
- Two new columns: `Class` and `SubClass`

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
Expense              SUPERMARKET_1        -450.23
                     SUPERMARKET_2   -320.15
                     Total        -770.38
Grocery              LOCAL_SHOP     -150.00
                     Total        -150.00
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

# Format code
uv run ruff format src/
```

### Code Quality Tools

- **Ruff**: Fast Python linter and formatter
- **MyPy**: Static type checker with strict configuration

## Customization

### Setting Up Your Classifications

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

3. The tool performs case-sensitive substring matching on transaction descriptions

**Note:** Your personal `classifications.json` file is gitignored to protect your privacy. Only the anonymized example file is tracked in version control.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

Charlie Rusbridger (charlie@rusbridger.com)
