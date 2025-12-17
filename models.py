from flask_login import UserMixin
from database import get_db_connection

class User(UserMixin):
    def __init__(self, id, username, full_name, role):
        self.id = id
        self.username = username
        self.full_name = full_name
        self.role = role # <--- جدید

    @staticmethod
    def get(user_id):
        conn = get_db_connection()
        user_data = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        
        if user_data:
            return User(
                id=user_data['id'], 
                username=user_data['username'], 
                full_name=user_data['full_name'],
                role=user_data['role'] # <--- جدید
            )
        return None

    @staticmethod
    def find_by_username(username):
        conn = get_db_connection()
        user_data = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        return user_data