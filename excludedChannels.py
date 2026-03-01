import sqlite3
import json

def setupExChannelDB():
    connection = sqlite3.connect("excludedChannels.db")
    cursor = connection.cursor()
    createTable = '''
    CREATE TABLE IF NOT EXISTS
    exchannels(serverID INTEGER PRIMARY KEY, channels TEXT)
    '''
    cursor.execute(createTable)
    connection.commit()
    connection.close()


def getExChannel(serverID):
    connection = sqlite3.connect("excludedChannels.db")
    cursor = connection.cursor()
    cursor.execute('SELECT channels FROM exchannels WHERE serverID = ?', (serverID,))
    result = cursor.fetchone()
    connection.close()

    if result:
        #load the JSON file back to python string
        return json.loads(result[0])
    else:
        return []
    

def addChannel(serverID,channelID):
    connection = sqlite3.connect("excludedChannels.db")
    cursor = connection.cursor()
    exChannels = getExChannel(serverID)
    exChannels.append(channelID)
    exchannels_json = json.dumps(exChannels)
    cursor.execute('SELECT serverID FROM exchannels WHERE serverID = ?', (serverID,))
    if cursor.fetchone():
        cursor.execute('UPDATE exchannels SET channels = ? WHERE serverID = ?', (exchannels_json, serverID))
    else:
        cursor.execute('INSERT INTO exchannels (serverID, channels) VALUES (?, ?)', (serverID, exchannels_json))
    connection.commit()
    connection.close()