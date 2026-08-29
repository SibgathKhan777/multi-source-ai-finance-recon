import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

from database import reset_db, get_session


@pytest.fixture()
def db_session():
    reset_db()
    session = get_session()
    try:
        yield session
    finally:
        session.close()
