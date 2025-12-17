import sqlite3
import os

DB_NAME = "portfolio_manager.db"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'portfolio_manager.db')

COMMISSION_RATES = {
    'TSE': { # بازار بورس
        'Stock': {'buy': 0.003712, 'sell': 0.0088},
        'Rights': {'buy': 0.003712, 'sell': 0.0088}, # حق تقدم
    },
    'IFB': { # بازار فرابورس (کارمزد خرید کمی کمتر و فروش کمی بیشتر است)
        'Stock': {'buy': 0.003632, 'sell': 0.00891},
        'Rights': {'buy': 0.003632, 'sell': 0.00891},
    },
    'ETF': { # صندوق‌ها (نرخ‌های جدید)
        'Equity': {'buy': 0.00232, 'sell': 0.002375},    # صندوق سهامی
        'Fixed':  {'buy': 0.000375, 'sell': 0.000375},  # درآمد ثابت
        'Gold':   {'buy': 0.0012, 'sell': 0.0012},        # صندوق طلا
    }
}

def normalize_text(text):
    if not text: return ""
    return text.replace('ك', 'ک').replace('ي', 'ی').replace('ى', 'ی').strip()

def get_db_connection():
    # اضافه کردن timeout=20 ثانیه برای حل مشکل locked
    conn = sqlite3.connect(DB_PATH, timeout=20) 
    conn.row_factory = sqlite3.Row
    # فعال کردن حالت WAL برای همزمانی بهتر
    conn.execute('PRAGMA journal_mode=WAL;') 
    return conn


def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    # 1. کاربران
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT,
            email TEXT,
            role TEXT DEFAULT 'manager'
        )
    ''')
    
    c.execute('''
        INSERT INTO users (username, password, full_name, role) 
        VALUES ('admin', '1234', 'مدیر سیستم', 'admin')
        ON CONFLICT(username) DO UPDATE SET role = 'admin'
    ''')

    # 2. سبدها
    c.execute('''
        CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            national_id TEXT,
            broker TEXT,
            manager_name TEXT,
            risk_level TEXT,
            initial_cash REAL,
            current_cash REAL DEFAULT 0,
            initial_stock_value REAL,
            initial_capital REAL,
            initial_index REAL,
            delivery_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT,
            owner_id INTEGER,
            FOREIGN KEY (owner_id) REFERENCES users (id)
        )
    ''')

    # 3. تراکنش‌ها
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER,
            symbol TEXT,
            sector TEXT,
            transaction_type TEXT NOT NULL,
            quantity INTEGER,
            price REAL,
            amount REAL DEFAULT 0,
            asset_class TEXT DEFAULT 'Stock',
            date TEXT,
            commission REAL DEFAULT 0,
            FOREIGN KEY (portfolio_id) REFERENCES portfolios (id)
        )
    ''')

    # 4. قیمت‌ها
    c.execute('''
        CREATE TABLE IF NOT EXISTS market_prices (
            symbol TEXT PRIMARY KEY,
            company_name TEXT,
            sector TEXT,
            asset_type TEXT,        -- Stock, ETF_Equity, ETF_Gold, ETF_Fixed
            market_type TEXT DEFAULT 'TSE', -- TSE (بورس), IFB (فرابورس)
            last_price REAL,
            close_price_yesterday REAL,
            pe_ratio REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 5. تاریخچه
    c.execute('''
        CREATE TABLE IF NOT EXISTS portfolio_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER,
            record_date TEXT,
            total_equity REAL,
            FOREIGN KEY (portfolio_id) REFERENCES portfolios (id)
        )
    ''')

    # 6. تنظیمات مدل‌ها (Model Configs)
    c.execute('''
        CREATE TABLE IF NOT EXISTS model_configs (
            profile_name TEXT PRIMARY KEY,
            target_fixed_income REAL,
            target_gold REAL,
            target_equity REAL,
            description TEXT
        )
    ''')
    if not c.execute("SELECT * FROM model_configs").fetchone():
        c.execute("INSERT INTO model_configs VALUES ('Low', 70, 20, 10, 'سبد کم‌ریسک')")
        c.execute("INSERT INTO model_configs VALUES ('Medium', 40, 30, 30, 'سبد متعادل')")
        c.execute("INSERT INTO model_configs VALUES ('High', 10, 20, 70, 'سبد پرریسک')")

    # 7. ریز دارایی‌های مدل (Model Assets)
    c.execute('''
        CREATE TABLE IF NOT EXISTS model_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_name TEXT,
            symbol TEXT,
            target_weight REAL,
            stop_loss REAL,
            target_short REAL,
            target_mid REAL,
            target_long REAL,
            note TEXT,
            FOREIGN KEY (profile_name) REFERENCES model_configs (profile_name)
        )
    ''')

    # 8. سیگنال‌های تحلیل (Analysis Signals)
    c.execute('''
        CREATE TABLE IF NOT EXISTS analysis_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            target_buy_price REAL,
            target_sell_price REAL,
            stop_loss_price REAL,
            analysis_note TEXT,
            target_profile TEXT,
            asset_class TEXT,
            is_public INTEGER DEFAULT 1,
            owner_id INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (symbol) REFERENCES market_prices (symbol),
            FOREIGN KEY (owner_id) REFERENCES users (id)
        )
    ''')

    # 9. تقویم
    c.execute('''
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id INTEGER,
            title TEXT NOT NULL,
            event_date TEXT NOT NULL,
            event_type TEXT,
            symbol TEXT,
            amount REAL DEFAULT 0,
            is_processed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (portfolio_id) REFERENCES portfolios (id)
        )
    ''')
    
    
    # 10. جدول وضعیت کلی بازار (جدید)
    c.execute('''
        CREATE TABLE IF NOT EXISTS market_overview (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_index REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # ایجاد ردیف اولیه اگر وجود ندارد
    c.execute("INSERT OR IGNORE INTO market_overview (id, total_index) VALUES (1, 0)")
    
    # --- پایان تغییرات ---

    conn.commit() # ذخیره نهایی
    conn.close()  # بستن اتصال (این باید آخرین خط باشد)
    print("دیتابیس کامل ساخته شد.")

def get_all_market_prices():
    conn = get_db_connection()
    prices = conn.execute('''
        SELECT * FROM market_prices 
        WHERE symbol NOT LIKE 'ض%' AND symbol NOT LIKE 'ط%' AND symbol NOT LIKE 'ظ%' 
        AND symbol NOT GLOB '*[0-9]*' AND asset_type != 'Option'
        ORDER BY symbol ASC
    ''').fetchall()
    conn.close()
    return prices

def add_new_transaction(data):
    conn = get_db_connection()
    try:
        p_id = data['portfolio_id']
        t_type = data['type'] 
        symbol = normalize_text(data.get('symbol'))
        date = data['date']
        
        quantity = float(data.get('quantity', 0)) if t_type in ['buy', 'sell'] else 1
        price = float(data.get('price', 0))
        
        # 1. استخراج اطلاعات دارایی از دیتابیس
        sector = "سایر"
        asset_type = "Stock"
        market_type = "TSE" # پیش‌فرض بورس
        
        if symbol and symbol != 'CASH':
            cur = conn.execute("SELECT sector, asset_type, market_type FROM market_prices WHERE symbol=?", (symbol,))
            row = cur.fetchone()
            if row:
                sector = row['sector'] or "سایر"
                asset_type = row['asset_type'] or "Stock"
                market_type = row['market_type'] or "TSE"

        if t_type in ['deposit', 'withdraw', 'dividend']:
            sector = "بانکی"
            asset_class_db = "Cash"
        else:
            asset_class_db = asset_type # برای ذخیره در جدول تراکنش‌ها

        # 2. فرمول محاسبه کارمزد (دقیق و داینامیک)
        if 'commission' in data:
            commission = float(data['commission'])
        else:
            total_val = quantity * price
            commission = 0
            
            # الف) تشخیص نوع صندوق
            if 'ETF' in asset_type or 'صندوق' in asset_type:
                # تشخیص نوع ETF
                if 'Gold' in asset_type or 'طلا' in asset_type:
                    rate = COMMISSION_RATES['ETF']['Gold'].get(t_type, 0)
                elif 'Fixed' in asset_type or 'ثابت' in asset_type:
                    rate = COMMISSION_RATES['ETF']['Fixed'].get(t_type, 0)
                else:
                    # فرض بر صندوق سهامی/مختلط
                    rate = COMMISSION_RATES['ETF']['Equity'].get(t_type, 0)
            
            # ب) سهام و حق تقدم (بورس یا فرابورس)
            else:
                # انتخاب بازار (TSE یا IFB)
                mkt = market_type if market_type in ['TSE', 'IFB'] else 'TSE'
                # انتخاب نوع دارایی (سهام یا حق تقدم)
                kind = 'Rights' if (symbol and symbol.endswith('ح')) else 'Stock'
                
                rate = COMMISSION_RATES[mkt][kind].get(t_type, 0)
            
            commission = total_val * rate

        # 3. محاسبه مبلغ نهایی
        amount = 0
        if t_type == 'buy':
            amount = (quantity * price) + commission
        elif t_type == 'sell':
            amount = (quantity * price) - commission
        else:
            amount = price

        # 4. ثبت
        conn.execute('''
            INSERT INTO transactions 
            (portfolio_id, transaction_type, symbol, sector, quantity, price, amount, commission, date, asset_class)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (p_id, t_type, symbol, sector, quantity, price, amount, commission, date, asset_class_db))
        
        # 5. آپدیت نقدینگی (بصورت بهینه و مستقیم)
        cash_impact = 0
        if t_type in ['deposit', 'sell', 'dividend']:
            cash_impact = amount
        elif t_type in ['withdraw', 'buy']:
            cash_impact = -amount

        conn.execute("UPDATE portfolios SET current_cash = current_cash + ? WHERE id = ?", (cash_impact, p_id))
        
        conn.commit()
        return True
        
    except Exception as e:
        print(f"Transaction Error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()



def update_stock_price(symbol, new_price):
    conn = get_db_connection()
    conn.execute('UPDATE market_prices SET last_price=?, updated_at=CURRENT_TIMESTAMP WHERE symbol=?', (new_price, symbol))
    conn.commit()
    conn.close()

def set_market_index(value):

    conn = get_db_connection()
    conn.execute("UPDATE market_overview SET total_index = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1", (value,))
    conn.commit()
    conn.close()

def recalculate_portfolio_cash(portfolio_id):
    """
    محاسبه مجدد و دقیق مانده نقدینگی بر اساس تمام تراکنش‌های ثبت شده.
    این تابع تضمین می‌کند که عدد نقدینگی همیشه با تراکنش‌ها همخوانی دارد.
    """
    conn = get_db_connection()
    try:
        # فرمول: (واریز + فروش + سود نقدی) - (برداشت + خرید)
        calc = conn.execute('''
            SELECT 
                (SELECT IFNULL(SUM(amount), 0) FROM transactions WHERE portfolio_id = ? AND transaction_type IN ('deposit', 'sell', 'dividend')) 
                - 
                (SELECT IFNULL(SUM(amount), 0) FROM transactions WHERE portfolio_id = ? AND transaction_type IN ('withdraw', 'buy'))
            as final_cash
        ''', (portfolio_id, portfolio_id)).fetchone()
        
        real_cash = calc['final_cash'] if calc else 0
        
        # آپدیت عدد در جدول سبدها
        conn.execute("UPDATE portfolios SET current_cash = ? WHERE id = ?", (real_cash, portfolio_id))
        conn.commit()
    except Exception as e:
        print(f"Cash Recalc Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()