from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = BACKEND_DIR / "recon.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

LEDGER_CSV = DATA_DIR / "ledger.csv"
PSP_CSV = DATA_DIR / "psp_export.csv"
BANK_CSV = DATA_DIR / "bank_statement.csv"
GROUND_TRUTH_CSV = DATA_DIR / "ground_truth.csv"

# Phase 3 matching tolerances
TIMESTAMP_TOLERANCE_MINUTES = 5
AMOUNT_TOLERANCE_PCT = 0.0001  # 0.01%, used for large-value batch netting (pass 4)
# Pass 2's per-transaction cap: cent-level rounding noise only. A 0.01% relative
# tolerance is far too loose at typical transaction sizes here (e.g. it would
# silently wave through story 11's 0.02 diff on a 4999.00 amount), so pass 2
# uses this tight absolute cap and leaves real diffs for Phase 5 to classify.
AMOUNT_TOLERANCE_ABS = 0.01

# Phase 6 late-arrival handling
LOOK_BACK_DAYS = 7

# Only currency present in this dataset — used by the agent to infer
# missing currency fields (story 8).
DEFAULT_CURRENCY = "INR"
