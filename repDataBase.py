from db_helper import get_connection

def setupRepDB():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS userReps (
        userID INTEGER PRIMARY KEY, 
        reps INTEGER DEFAULT 0
    )
    ''')
    connection.commit()
    connection.sync()
    connection.close()


def get_reps(userID):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute('SELECT reps FROM userReps WHERE userID = ?', (userID,))
    result = cursor.fetchone()
    connection.close()
    return result[0] if result else 0


def add_rep(userID):
    """Increments rep by 1 and returns the new total."""
    connection = get_connection()
    cursor = connection.cursor()
    
    cursor.execute('SELECT reps FROM userReps WHERE userID = ?', (userID,))
    result = cursor.fetchone()
    
    if result:
        new_reps = result[0] + 1
        cursor.execute('UPDATE userReps SET reps = ? WHERE userID = ?', (new_reps, userID))
    else:
        new_reps = 1
        cursor.execute('INSERT INTO userReps (userID, reps) VALUES (?, ?)', (userID, new_reps))
        
    connection.commit()
    connection.sync()
    connection.close()
    return new_reps