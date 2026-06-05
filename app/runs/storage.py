import os
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List

DB_PATH = "/opt/ai-lab/ai-senate/data/council.db"

def init_db():
    """Initializes the SQLite database and creates the runs table if it doesn't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            new_document INTEGER NOT NULL,
            max_rounds INTEGER DEFAULT 2,
            current_round INTEGER DEFAULT 1,
            auto_stop_if_clean INTEGER DEFAULT 1,
            phase TEXT DEFAULT 'queued'
        )
    """)
    
    # Try adding new columns if they might be missing in an old database
    new_cols = [
        ("max_rounds", "INTEGER DEFAULT 2"),
        ("current_round", "INTEGER DEFAULT 1"),
        ("auto_stop_if_clean", "INTEGER DEFAULT 1"),
        ("phase", "TEXT DEFAULT 'queued'")
    ]
    for col_name, col_def in new_cols:
        try:
            cursor.execute(f"ALTER TABLE runs ADD COLUMN {col_name} {col_def}")
        except sqlite3.OperationalError:
            # Column already exists
            pass
            
    conn.commit()
    conn.close()

def create_run(run_id: str, new_document: bool, max_rounds: int = 2, auto_stop_if_clean: bool = True) -> Dict[str, Any]:
    """Creates a new run in the database."""
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO runs (id, status, created_at, updated_at, new_document, max_rounds, current_round, auto_stop_if_clean, phase) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, "queued", now, now, 1 if new_document else 0, max_rounds, 1, 1 if auto_stop_if_clean else 0, "queued")
    )
    conn.commit()
    conn.close()
    return {
        "id": run_id,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "new_document": new_document,
        "max_rounds": max_rounds,
        "current_round": 1,
        "auto_stop_if_clean": auto_stop_if_clean,
        "phase": "queued"
    }

def update_run_status(run_id: str, status: str) -> None:
    """Updates the status of an existing run."""
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE runs SET status = ?, updated_at = ? WHERE id = ?",
        (status, now, run_id)
    )
    conn.commit()
    conn.close()

def update_run_progress(run_id: str, status: Optional[str] = None, phase: Optional[str] = None, current_round: Optional[int] = None) -> None:
    """Updates the progress fields of an existing run."""
    now = datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    updates = []
    params = []
    
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if phase is not None:
        updates.append("phase = ?")
        params.append(phase)
    if current_round is not None:
        updates.append("current_round = ?")
        params.append(current_round)
        
    updates.append("updated_at = ?")
    params.append(now)
    
    params.append(run_id)
    
    query = f"UPDATE runs SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, params)
    
    conn.commit()
    conn.close()

def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single run by ID."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        row_keys = row.keys()
        return {
            "id": row["id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "new_document": bool(row["new_document"]),
            "max_rounds": row["max_rounds"] if "max_rounds" in row_keys else 2,
            "current_round": row["current_round"] if "current_round" in row_keys else 1,
            "auto_stop_if_clean": bool(row["auto_stop_if_clean"]) if "auto_stop_if_clean" in row_keys else True,
            "phase": row["phase"] if "phase" in row_keys else "queued"
        }
    return None

def list_runs() -> List[Dict[str, Any]]:
    """Lists all runs ordered by creation date desc."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM runs ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "new_document": bool(row["new_document"]),
            "max_rounds": row["max_rounds"] if "max_rounds" in row.keys() else 2,
            "current_round": row["current_round"] if "current_round" in row.keys() else 1,
            "auto_stop_if_clean": bool(row["auto_stop_if_clean"]) if "auto_stop_if_clean" in row.keys() else True,
            "phase": row["phase"] if "phase" in row.keys() else "queued"
        }
        for row in rows
    ]
