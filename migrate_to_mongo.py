import sqlite3
from pymongo import MongoClient
from werkzeug.security import generate_password_hash

def migrate():
    # Connect to SQLite
    sqlite_conn = sqlite3.connect('database.db')
    sqlite_conn.row_factory = sqlite3.Row
    cursor = sqlite_conn.cursor()

    # Connect to MongoDB
    mongo_client = MongoClient('mongodb://localhost:27017/')
    db = mongo_client['money_buddy']
    users_col = db['users']
    expenses_col = db['expenses']

    print("Starting migration...")

    # 1. Migrate Users
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    user_id_map = {} # To keep track of mapping between SQLite ID and MongoDB ObjectId

    for user in users:
        # Check if user already exists in Mongo
        if not users_col.find_one({'username': user['username']}):
            result = users_col.insert_one({
                'username': user['username'],
                'password': user['password'] # They are already hashed in SQLite
            })
            user_id_map[user['id']] = str(result.inserted_id)
            print(f"Migrated user: {user['username']}")
        else:
            # If user exists, find their mongo ID for expense mapping
            mongo_user = users_col.find_one({'username': user['username']})
            user_id_map[user['id']] = str(mongo_user['_id'])
            print(f"User {user['username']} already exists, mapping expenses...")

    # 2. Migrate Expenses
    cursor.execute("SELECT * FROM expenses")
    expenses = cursor.fetchall()
    
    count = 0
    for exp in expenses:
        mongo_user_id = user_id_map.get(exp['user_id'])
        if mongo_user_id:
            # Check for duplicates (optional, but good for safety)
            duplicate = expenses_col.find_one({
                'user_id': mongo_user_id,
                'type': exp['type'],
                'amount': exp['amount'],
                'description': exp['description'],
                'timestamp': exp['timestamp']
            })
            
            if not duplicate:
                expenses_col.insert_one({
                    'user_id': mongo_user_id,
                    'type': exp['type'],
                    'amount': exp['amount'],
                    'description': exp['description'],
                    'category': exp['category'],
                    'timestamp': exp['timestamp']
                })
                count += 1
    
    print(f"Migrated {count} expense records.")
    print("Migration complete! You can now see the 'money_buddy' database in MongoDB Compass.")

if __name__ == "__main__":
    migrate()
