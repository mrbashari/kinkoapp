import sqlite3

def check_db():
    conn = sqlite3.connect('portfolio_manager.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    print("\n--- بررسی کاربران ---")
    users = c.execute("SELECT id, username, full_name FROM users").fetchall()
    for u in users:
        print(f"ID: {u['id']} | User: {u['username']} ({u['full_name']})")

    print("\n--- بررسی تحلیل‌های ثبت شده ---")
    signals = c.execute("SELECT id, symbol, owner_id, is_public FROM analysis_signals").fetchall()
    
    if not signals:
        print(">> هیچ تحلیلی در دیتابیس یافت نشد! (مشکل در ثبت)")
    else:
        for s in signals:
            print(f"Signal ID: {s['id']} | Symbol: {s['symbol']} | Owner ID: {s['owner_id']} (Type: {type(s['owner_id'])}) | Public: {s['is_public']}")

    conn.close()

if __name__ == '__main__':
    check_db()