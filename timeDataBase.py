import sqlite3
import json

def setupTimeDB():
    connection = sqlite3.connect('userTimeUsage.db')

    cursor = connection.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS
    userTime(userID INTEGER PRIMARY KEY, time REAL DEFAULT 0, daily_time REAL DEFAULT 0)
    ''')
    
    

    # Add new Streak and Season columns safely
    new_columns = [
        ("current_streak", "INTEGER DEFAULT 0"),
        ("streak_status", "TEXT DEFAULT 'INACTIVE'"),
        ("last_completion_date", "TEXT"), # Stores YYYY-MM-DD
        ("season_id", "INTEGER DEFAULT 1")
    ]
    
    for col_name, col_type in new_columns:
        try:
            cursor.execute(f'ALTER TABLE userTime ADD COLUMN {col_name} {col_type}')
        except sqlite3.OperationalError:
            pass

    # Add the daily_time column if it doesn't exist (for existing databases)
    try:
        cursor.execute('ALTER TABLE userTime ADD COLUMN daily_time REAL DEFAULT 0')
    except sqlite3.OperationalError:
        pass

    connection.commit()
    connection.close()

def getUserTime(userID):
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()
    cursor.execute('SELECT time FROM userTime WHERE userID = ?', (userID,))
    result = cursor.fetchone()
    connection.close()

    if result == None:
        return 0
    else:
        return result[0]
    
def getUserDailyTime(userID):
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()
    cursor.execute('SELECT daily_time FROM userTime WHERE userID = ?', (userID,))
    result = cursor.fetchone()
    connection.close()

    if result == None:
        return 0
    else:
        return result[0]


def SaveUserTime(userID, duration):
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()

    # 1. Update (or Insert) TOTAL Time
    # We try to update first. If no row exists, we insert.
    cursor.execute('UPDATE userTime SET time = time + ? WHERE userID = ?', (duration, userID))
    
    # If the row didn't exist (changes == 0), we create it
    if cursor.rowcount == 0:
        cursor.execute('INSERT INTO userTime (userID, time, daily_time) VALUES (?, ?, ?)', (userID, duration, duration))
    else:
        # 2. Update DAILY Time
        # We only need to run this if the user already existed (because the INSERT above handles both)
        cursor.execute('UPDATE userTime SET daily_time = daily_time + ? WHERE userID = ?', (duration, userID))

    connection.commit()
    connection.close()

def get_leaderboard_data(lbtype,offset=0):
    """Fetches 10 users from the database, starting after the offset."""
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()
    
    # The '?' is a placeholder for the offset value
    if lbtype == "daily":
        cursor.execute('SELECT userID, daily_time FROM userTime ORDER BY daily_time DESC LIMIT 10 OFFSET ?', (offset,))
        result = cursor.fetchall()
    elif lbtype == "all time":
        cursor.execute('SELECT userID, time FROM userTime ORDER BY time DESC LIMIT 10 OFFSET ?', (offset,))
        result = cursor.fetchall()
    
    connection.close()
    return result

def get_streak_info(userID):
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()
    cursor.execute('SELECT current_streak, streak_status, last_completion_date FROM userTime WHERE userID = ?', (userID,))
    result = cursor.fetchone()
    connection.close()
    
    if result:
        return {"streak": result[0], "status": result[1], "last_date": result[2]}
    return {"streak": 0, "status": 'INACTIVE', "last_date": None}

def get_streak_leaderboard():
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()
    # Filter for active streaks and sort by the highest number
    cursor.execute('''
        SELECT userID, current_streak 
        FROM userTime 
        WHERE current_streak > 0 
        ORDER BY current_streak DESC
    ''')
    result = cursor.fetchall()
    connection.close()
    return result

def reset_seasonal_streaks():
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()
    
    # 1. Reset all streaks to 0
    # 2. Set all statuses to INACTIVE so they can redefine tasks
    cursor.execute('''
        UPDATE userTime 
        SET current_streak = 0, 
            streak_status = 'INACTIVE', 
            last_completion_date = NULL
    ''')
    
    connection.commit()
    connection.close()
    print("Season has been reset. All streaks are now 0.")
def get_contextual_data(target_user_id, lb_mode='daily'):
    """
    Fetches Top 3 + 7 Contextual Users (Total 10) to fill the leaderboard.
    Logic: Show 2 users above target (if possible) and fill the rest below.
    """
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()
    
    # 1. Select data based on mode
    if lb_mode == 'daily':
        cursor.execute('SELECT userID, daily_time FROM userTime WHERE daily_time > 0 ORDER BY daily_time DESC')
    else:
        cursor.execute('SELECT userID, time FROM userTime WHERE time > 0 ORDER BY time DESC')
    
    all_data = cursor.fetchall()
    connection.close()
    
    total_users = len(all_data)
    if total_users == 0:
        return [], 0

    # 2. Find target user's index (0-based)
    # Create a list of IDs to find index easily
    user_ids = [row[0] for row in all_data]
    
    target_index = -1
    if target_user_id in user_ids:
        target_index = user_ids.index(target_user_id)

    # 3. Determine Indices to Fetch
    indices_to_fetch = set()
    
    # --- A. ALWAYS GET TOP 3 ---
    for i in range(min(3, total_users)):
        indices_to_fetch.add(i)

    # --- B. DETERMINE THE LIST VIEW (7 Slots) ---
    # We have 7 slots to fill (Visual Slots 4-10)
    slots_available = 7
    
    if target_index == -1:
        # Scenario: User not on board (hasn't studied).
        # Just fill the remaining 7 slots with Ranks 4-10.
        start_slice = 3
    else:
        # Scenario: User is on the board.
        # We want to show 2 people ABOVE the user (index - 2).
        # But we cannot start earlier than index 3 (because 0,1,2 are Top 3).
        desired_start = target_index - 2
        start_slice = max(3, desired_start)
    
    # --- C. SHIFT WINDOW IF NEAR BOTTOM ---
    # If starting here means we run out of users before filling 7 slots,
    # shift the start window UP to fill the empty space.
    # Example: Total 10 users. User is Rank 10. Start 8. slice 8-15 (Too far).
    # Correct: Start 3. Slice 3-10.
    
    # Calculate the maximum possible start index that ensures we have 'slots_available' items
    # (or as many as possible if total < 10)
    max_start = max(3, total_users - slots_available)
    
    # Clamp the start_slice
    start_slice = min(start_slice, max_start)
    
    # --- D. ADD INDICES TO SET ---
    for i in range(start_slice, start_slice + slots_available):
        if i < total_users:
            indices_to_fetch.add(i)

    # 4. Build Result
    sorted_indices = sorted(list(indices_to_fetch))
    result_data = []
    
    for idx in sorted_indices:
        uid, time_val = all_data[idx]
        result_data.append((idx + 1, uid, time_val))
        
    return result_data, target_index + 1 if target_index != -1 else 0
# ==========================================
#  PER-TAG TIME TRACKING
# ==========================================

def setupTagTimeDB():
    """Creates the userTagTime table if it doesn't exist."""
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS userTagTime (
            userID  INTEGER NOT NULL,
            tag     TEXT    NOT NULL,
            time    REAL    DEFAULT 0,
            PRIMARY KEY (userID, tag)
        )
    ''')
    connection.commit()
    connection.close()

def SaveUserTimeByTag(userID: int, tag: str, duration: float) -> None:
    """
    Adds `duration` seconds to the user's time under `tag`.
    Upserts the row so callers never need to worry about first-time setup.
    """
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()
    cursor.execute('''
        INSERT INTO userTagTime (userID, tag, time)
        VALUES (?, ?, ?)
        ON CONFLICT(userID, tag) DO UPDATE SET time = time + excluded.time
    ''', (userID, tag, duration))
    connection.commit()
    connection.close()

def getUserTagTimes(userID: int) -> list[tuple[str, float]]:
    """
    Returns a list of (tag, total_seconds) sorted by time descending
    for the given user.
    """
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()
    cursor.execute(
        'SELECT tag, time FROM userTagTime WHERE userID = ? ORDER BY time DESC',
        (userID,)
    )
    result = cursor.fetchall()
    connection.close()
    return result

# ==========================================
#  DAILY HISTORY  (for 7-day bar chart)
# ==========================================

def setupDailyHistoryDB():
    """Creates userDailyHistory table — one row per user per date."""
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS userDailyHistory (
            userID  INTEGER NOT NULL,
            date    TEXT    NOT NULL,   -- YYYY-MM-DD
            seconds REAL    DEFAULT 0,
            PRIMARY KEY (userID, date)
        )
    ''')
    connection.commit()
    connection.close()


def snapshotDailyTime(userID: int) -> None:
    """
    Called at end-of-day (before the daily_time reset).
    Records today's daily_time into the history table.
    """
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()

    cursor.execute('SELECT daily_time FROM userTime WHERE userID = ?', (userID,))
    result = cursor.fetchone()
    daily_seconds = result[0] if result else 0

    today = datetime.utcnow().strftime('%Y-%m-%d')

    cursor.execute('''
        INSERT INTO userDailyHistory (userID, date, seconds)
        VALUES (?, ?, ?)
        ON CONFLICT(userID, date) DO UPDATE SET seconds = excluded.seconds
    ''', (userID, today, daily_seconds))

    connection.commit()
    connection.close()


def get_last_7_days(userID: int) -> list[tuple[str, float]]:
    """
    Returns the last 7 days of history for a user as [(date_str, seconds), ...],
    oldest first. Missing days are filled with 0 so the bar chart always has 7 bars.
    """
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()

    # Pull up to 7 rows, most recent first
    cursor.execute('''
        SELECT date, seconds FROM userDailyHistory
        WHERE userID = ?
        ORDER BY date DESC
        LIMIT 7
    ''', (userID,))
    rows = {row[0]: row[1] for row in cursor.fetchall()}
    connection.close()

    result = []
    for i in range(6, -1, -1):   # 6 days ago → today
        d = (datetime.utcnow() - timedelta(days=i)).strftime('%Y-%m-%d')
        result.append((d, rows.get(d, 0.0)))

    return result   # [(YYYY-MM-DD, seconds), ...] oldest → newest

def get_weekly_leaderboard(offset: int = 0) -> list[tuple[int, float]]:
    """
    Returns top 10 users ranked by total study seconds over the last 7 days.
    Combines completed-day snapshots (userDailyHistory) with today's live
    daily_time so the leaderboard is always up to date when flushed.
    Returns [(userID, total_seconds), ...].
    """
    from datetime import datetime, timedelta
    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()

    today = datetime.utcnow().strftime('%Y-%m-%d')
    cutoff = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')

    # Sum past snapshots (excludes today — today is in daily_time, not yet snapshotted)
    # UNION with today's live daily_time so flushed time is immediately visible
    cursor.execute('''
        SELECT userID, SUM(seconds) as total FROM (
            SELECT userID, seconds
            FROM userDailyHistory
            WHERE date >= ? AND date < ?

            UNION ALL

            SELECT userID, daily_time AS seconds
            FROM userTime
            WHERE daily_time > 0
        )
        GROUP BY userID
        ORDER BY total DESC
        LIMIT 10 OFFSET ?
    ''', (cutoff, today, offset))

    result = cursor.fetchall()
    connection.close()
    return result


def get_weekly_rank(userID: int) -> int:
    """Returns the user's rank on the weekly leaderboard (1-based).
    Includes today's live daily_time same as get_weekly_leaderboard."""
    from datetime import datetime, timedelta
    today  = datetime.utcnow().strftime('%Y-%m-%d')
    cutoff = (datetime.utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')

    connection = sqlite3.connect('userTimeUsage.db')
    cursor = connection.cursor()

    # User's own weekly total (past days + today)
    cursor.execute('''
        SELECT SUM(seconds) FROM (
            SELECT seconds FROM userDailyHistory
            WHERE userID = ? AND date >= ? AND date < ?
            UNION ALL
            SELECT daily_time FROM userTime WHERE userID = ?
        )
    ''', (userID, cutoff, today, userID))
    result = cursor.fetchone()
    user_total = result[0] if result and result[0] else 0

    # Count users ranked higher
    cursor.execute('''
        SELECT COUNT(*) FROM (
            SELECT userID, SUM(seconds) as total FROM (
                SELECT userID, seconds FROM userDailyHistory
                WHERE date >= ? AND date < ?
                UNION ALL
                SELECT userID, daily_time FROM userTime WHERE daily_time > 0
            )
            GROUP BY userID
        ) WHERE total > ?
    ''', (cutoff, today, user_total))
    ahead = cursor.fetchone()[0]
    connection.close()
    return ahead + 1