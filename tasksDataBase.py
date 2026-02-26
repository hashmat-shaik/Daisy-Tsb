from db_helper import get_connection
import json

# ==========================================
#  TODO LIST DATABASE
# ==========================================

def setupTodoDB():
    connection = sqlite3.connect('userTaskList.db')
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS userTodoLists (
            key TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ''')
    connection.commit()
    connection.close()

def getTodoData(channel_id: int, user_id: int) -> dict:
    key = f"{channel_id}:{user_id}"
    connection = sqlite3.connect('userTaskList.db')
    cursor = connection.cursor()
    cursor.execute('SELECT data FROM userTodoLists WHERE key = ?', (key,))
    result = cursor.fetchone()
    connection.close()

    default = {"pending": [], "completed": []}
    if not result:
        return default
    try:
        loaded = json.loads(result[0])
        if "pending" not in loaded: loaded["pending"] = []
        if "completed" not in loaded: loaded["completed"] = []
        return loaded
    except json.JSONDecodeError:
        return default

def saveTodoData(channel_id: int, user_id: int, data: dict):
    key = f"{channel_id}:{user_id}"
    connection = sqlite3.connect('userTaskList.db')
    cursor = connection.cursor()
    cursor.execute('''
        INSERT INTO userTodoLists (key, data) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET data = excluded.data
    ''', (key, json.dumps(data)))
    connection.commit()
    connection.close()

def getUserTodoPendingCount(user_id: int) -> int:
    """Return total number of pending todo tasks across all channels for a user."""
    connection = sqlite3.connect('userTaskList.db')
    cursor = connection.cursor()
    cursor.execute("SELECT data FROM userTodoLists WHERE key LIKE ?", (f"%:{user_id}",))
    rows = cursor.fetchall()
    connection.close()

    total_pending = 0
    for (data_json,) in rows:
        try:
            data = json.loads(data_json)
            total_pending += len(data.get("pending", []))
        except json.JSONDecodeError:
            pass
    return total_pending

def clearAllUserTodos(user_id: int):
    """Move all pending todo tasks to completed at midnight reset, per channel."""
    connection = sqlite3.connect('userTaskList.db')
    cursor = connection.cursor()
    cursor.execute("SELECT key, data FROM userTodoLists WHERE key LIKE ?", (f"%:{user_id}",))
    rows = cursor.fetchall()

    for key, data_json in rows:
        try:
            data = json.loads(data_json)
            # Move remaining pending → completed so history is preserved, then wipe both
            data["completed"] = data.get("completed", []) + data.get("pending", [])
            data["pending"] = []
            cursor.execute(
                "UPDATE userTodoLists SET data = ? WHERE key = ?",
                (json.dumps(data), key)
            )
        except json.JSONDecodeError:
            pass

    connection.commit()
    connection.close()

def setupTaskDB():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS
    userTasks(userID INTEGER PRIMARY KEY, tasks TEXT)
    ''')
    connection.commit()
    connection.sync()
    connection.close()


def getUserData(userID):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute('SELECT tasks FROM userTasks WHERE userID = ?', (userID,))
    result = cursor.fetchone()
    connection.close()

    default_structure = {"journal": [], "daily": []}

    if not result:
        return default_structure

    try:
        loaded_data = json.loads(result[0])
        
        if isinstance(loaded_data, list):
            loaded_data = {"journal": loaded_data, "daily": []}
        
        if "journal" not in loaded_data: loaded_data["journal"] = []
        if "daily" not in loaded_data: loaded_data["daily"] = []

        return loaded_data

    except json.JSONDecodeError:
        print(f"⚠️ DATA CORRUPTION WARNING: User {userID} has broken JSON.")
        return default_structure


def SaveUserTasks(userID, journal_tasks, daily_tasks):
    connection = get_connection()
    cursor = connection.cursor()
    
    tasks_dict = {
        "journal": journal_tasks,
        "daily": daily_tasks
    }
    
    tasks_json = json.dumps(tasks_dict)
    
    cursor.execute('''
        INSERT INTO userTasks (userID, tasks) VALUES (?, ?)
        ON CONFLICT(userID) DO UPDATE SET tasks = excluded.tasks
    ''', (userID, tasks_json))
    
    connection.commit()
    connection.sync()
    connection.close()