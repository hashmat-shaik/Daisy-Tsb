from db_helper import get_connection
import json

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