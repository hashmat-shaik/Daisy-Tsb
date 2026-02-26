from db_helper import get_connection
import json

def setupTimeDB():
    connection = get_connection()
    cursor = connection.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS
    userTime(userID INTEGER PRIMARY KEY, time REAL DEFAULT 0, daily_time REAL DEFAULT 0)
    ''')

    new_columns = [
        ("current_streak", "INTEGER DEFAULT 0"),
        ("streak_status", "TEXT DEFAULT 'INACTIVE'"),
        ("last_completion_date", "TEXT"),
        ("season_id", "INTEGER DEFAULT 1")
    ]
    
    for col_name, col_type in new_columns:
        try:
            cursor.execute(f'ALTER TABLE userTime ADD COLUMN {col_name} {col_type}')
        except Exception:
            pass

    try:
        cursor.execute('ALTER TABLE userTime ADD COLUMN daily_time REAL DEFAULT 0')
    except Exception:
        pass

    connection.commit()
    connection.sync()
    connection.close()


def getUserTime(userID):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute('SELECT time FROM userTime WHERE userID = ?', (userID,))
    result = cursor.fetchone()
    connection.close()
    return result[0] if result else 0


def getUserDailyTime(userID):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute('SELECT daily_time FROM userTime WHERE userID = ?', (userID,))
    result = cursor.fetchone()
    connection.close()
    return result[0] if result else 0


def SaveUserTime(userID, duration):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute('UPDATE userTime SET time = time + ? WHERE userID = ?', (duration, userID))
    
    if cursor.rowcount == 0:
        cursor.execute('INSERT INTO userTime (userID, time, daily_time) VALUES (?, ?, ?)', (userID, duration, duration))
    else:
        cursor.execute('UPDATE userTime SET daily_time = daily_time + ? WHERE userID = ?', (duration, userID))

    connection.commit()
    connection.sync()
    connection.close()


def get_leaderboard_data(lbtype, offset=0):
    connection = get_connection()
    cursor = connection.cursor()
    
    if lbtype == "daily":
        cursor.execute('SELECT userID, daily_time FROM userTime ORDER BY daily_time DESC LIMIT 10 OFFSET ?', (offset,))
    elif lbtype == "all time":
        cursor.execute('SELECT userID, time FROM userTime ORDER BY time DESC LIMIT 10 OFFSET ?', (offset,))
    
    result = cursor.fetchall()
    connection.close()
    return result


def get_streak_info(userID):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute('SELECT current_streak, streak_status, last_completion_date FROM userTime WHERE userID = ?', (userID,))
    result = cursor.fetchone()
    connection.close()
    
    if result:
        return {"streak": result[0], "status": result[1], "last_date": result[2]}
    return {"streak": 0, "status": 'INACTIVE', "last_date": None}


def get_streak_leaderboard():
    connection = get_connection()
    cursor = connection.cursor()
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
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute('''
        UPDATE userTime 
        SET current_streak = 0, 
            streak_status = 'INACTIVE', 
            last_completion_date = NULL
    ''')
    connection.commit()
    connection.sync()
    connection.close()
    print("Season has been reset. All streaks are now 0.")


def get_contextual_data(target_user_id, lb_mode='daily'):
    connection = get_connection()
    cursor = connection.cursor()
    
    if lb_mode == 'daily':
        cursor.execute('SELECT userID, daily_time FROM userTime WHERE daily_time > 0 ORDER BY daily_time DESC')
    else:
        cursor.execute('SELECT userID, time FROM userTime WHERE time > 0 ORDER BY time DESC')
    
    all_data = cursor.fetchall()
    connection.close()
    
    total_users = len(all_data)
    if total_users == 0:
        return [], 0

    user_ids = [row[0] for row in all_data]
    target_index = user_ids.index(target_user_id) if target_user_id in user_ids else -1

    indices_to_fetch = set()
    
    for i in range(min(3, total_users)):
        indices_to_fetch.add(i)

    slots_available = 7
    
    if target_index == -1:
        start_slice = 3
    else:
        desired_start = target_index - 2
        start_slice = max(3, desired_start)
    
    max_start = max(3, total_users - slots_available)
    start_slice = min(start_slice, max_start)
    
    for i in range(start_slice, start_slice + slots_available):
        if i < total_users:
            indices_to_fetch.add(i)

    sorted_indices = sorted(list(indices_to_fetch))
    result_data = []
    
    for idx in sorted_indices:
        uid, time_val = all_data[idx]
        result_data.append((idx + 1, uid, time_val))
        
    return result_data, target_index + 1 if target_index != -1 else 0