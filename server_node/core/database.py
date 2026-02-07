"""
Database Manager for Sentinel.
Handles persistent storage of tracked events using SQLite.
"""
import sqlite3
import logging
import os
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger("database")

DB_PATH = "sentinel.db"

@dataclass
class TrackedEvent:
    track_id: int
    label: str
    camera_id: str
    start_time: float
    last_seen: float
    max_conf: float
    snapshot_path: str = ""

class DatabaseManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self):
        if self.initialized:
            return
            
        self.conn = None
        self._init_db()
        self.initialized = True

    def _init_db(self):
        """Initialize the SQLite database and create tables."""
        try:
            self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            cursor = self.conn.cursor()
            
            # Events Table
            # Stores unique 'visits' per track ID
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    track_id INTEGER,
                    label TEXT,
                    camera_id TEXT,
                    start_time TIMESTAMP,
                    last_seen TIMESTAMP,
                    max_conf REAL,
                    snapshot_path TEXT,
                    embedding BLOB
                )
            ''')
            self.conn.commit()
            logger.info(f"Database initialized at {DB_PATH}")
            
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")

    def log_event(self, event: TrackedEvent):
        """Logs a new tracked event or updates an existing one."""
        if not self.conn:
            return

        try:
            cursor = self.conn.cursor()
            
            # Check if this track_id exists for this run? 
            # Note: YOLO track IDs reset on restart. 
            # For a persistent DB across restarts, we ideally need ReID.
            # For now, we assume simple session-based or we just insert new rows.
            # To avoid duplicates if we call this frequently, we checks if track_id exists RECENTLY?
            # Actually, standard logic: INSERT.
            
            # However, we want to UPDATE the 'last_seen' if it exists.
            # But since track_ids are not unique across server restarts, this is tricky.
            # For this MVP, we will treat every 'new' detection in memory as a new potential DB entry,
            # but we need to update the DB row if the track_id is still active.
            
            # NOTE: The FrameProcessor will handle the logic of "Is this a new track?".
            # If it calls log_event, we assume it wants to CREATE or UPDATE.
            
            # Let's try to update first based on track_id within the last hour? (Simple heuristic)
            # Or simpler: The FrameProcessor keeps state. It calls `create_event` once, and `update_event` periodically.
            pass
            
        except Exception as e:
            logger.error(f"Database error: {e}")

    def create_event(self, event: TrackedEvent) -> int:
        """Creates a new event row. Returns the row ID."""
        if not self.conn: return -1
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO events (track_id, label, camera_id, start_time, last_seen, max_conf, snapshot_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (event.track_id, event.label, event.camera_id, 
                  datetime.fromtimestamp(event.start_time), 
                  datetime.fromtimestamp(event.last_seen), 
                  event.max_conf, event.snapshot_path))
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to insert event: {e}")
            return -1

    def update_event(self, row_id: int, last_seen: float, max_conf: float):
        """Updates the last_seen time and max confidence of an event."""
        if not self.conn: return
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE events 
                SET last_seen = ?, max_conf = MAX(max_conf, ?)
                WHERE id = ?
            ''', (datetime.fromtimestamp(last_seen), max_conf, row_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to update event: {e}")

    def get_recent_events(self, limit=50):
        """Retrieves the most recent tracked events."""
        if not self.conn: return []
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT id, track_id, label, camera_id, start_time, last_seen, max_conf, snapshot_path 
                FROM events 
                ORDER BY start_time DESC 
                LIMIT ?
            ''', (limit,))
            # Convert to list of dicts for easier consumption
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to fetch events: {e}")
            return []

# Global singleton
db_manager = DatabaseManager()
