from db_helper import get_connection
import json

def setupExChannelDB():
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS
    exchannels(serverID INTEGER PRIMARY KEY, channels TEXT)
    ''')
    connection.commit()
    connection.sync()
    connection.close()


def getExChannel(serverID):
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute('SELECT channels FROM exchannels WHERE serverID = ?', (serverID,))
    result = cursor.fetchone()
    connection.close()

    if result:
        return json.loads(result[0])
    else:
        return []


def addChannel(serverID, channelID):
    connection = get_connection()
    cursor = connection.cursor()
    
    exChannels = getExChannel(serverID)
    exChannels.append(channelID)
    exchannels_json = json.dumps(exChannels)
    
    cursor.execute('''
        INSERT INTO exchannels (serverID, channels) VALUES (?, ?)
        ON CONFLICT(serverID) DO UPDATE SET channels = excluded.channels
    ''', (serverID, exchannels_json))
    
    connection.commit()
    connection.sync()
    connection.close()