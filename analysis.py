import sqlite3
import statistics
import math
import jdatetime
from database import get_db_connection, recalculate_portfolio_cash
from flask import current_app
from datetime import datetime

# =========================================================
# تنظیمات و ثوابت
# =========================================================

COMMISSION_RATES = {
    'Stock': {'buy': 0.003712, 'sell': 0.0088},
    'Gold': {'buy': 0.0024, 'sell': 0.0024},
    'Fixed': {'buy': 0.0001875, 'sell': 0.0001875},
    'Cash': {'buy': 0, 'sell': 0},
    'Other': {'buy': 0, 'sell': 0}
}

def calculate_commission(asset_type, trans_type, total_value):
    if asset_type not in COMMISSION_RATES:
        asset_type = 'Stock'
    
    rate = COMMISSION_RATES[asset_type].get(trans_type, 0)
    return total_value * rate

def format_currency(value):
    if value is None:
        return "0"
    return "{:,.0f}".format(value)

def calculate_pct_change(current, initial):
    try:
        c = float(current or 0)
        i = float(initial or 0)
        if i <= 0: return 0.0
        return ((c - i) / i) * 100
    except:
        return 0.0

# =========================================================
# 1. هسته محاسباتی
# =========================================================

def _init_position(t):
    return {
        'qty': 0, 
        'sum_buy_qty': 0, 
        'sum_buy_cost': 0,
        'name': t['company_name'] or t['symbol'],
        'sector': t['sector'] or 'سایر',
        'last_price': t['last_price'] or 0,
        'prev_price': t['close_price_yesterday'] or 0
    }

def calculate_positions(portfolio_id):
    """
    محاسبه دقیق دارایی‌ها با استفاده از منطق میانگین موزون (Weighted Average)
    """
    conn = get_db_connection()
    # جوین کردن با قیمت‌های لحظه‌ای بازار
    transactions = conn.execute('''
        SELECT t.symbol, t.transaction_type, t.quantity, t.price, t.commission,
               m.last_price, m.company_name, m.sector, m.close_price_yesterday
        FROM transactions t
        LEFT JOIN market_prices m ON t.symbol = m.symbol
        WHERE t.portfolio_id = ?
        ORDER BY t.date ASC, t.id ASC
    ''', (portfolio_id,)).fetchall()
    conn.close()

    current_cash = 0
    positions = {} # ساختار: symbol: {qty, total_cost, ...}

    for t in transactions:
        sym = t['symbol']
        qty = float(t['quantity'] or 0)
        price = float(t['price'] or 0)
        comm = float(t['commission'] or 0)
        t_type = t['transaction_type']
        
        # مقداردهی اولیه اگر نماد جدید است
        if sym and sym not in positions:
            positions[sym] = {
                'qty': 0, 'total_cost': 0, 
                'name': t['company_name'] or sym, 
                'sector': t['sector'] or 'سایر',
                'last_price': t['last_price'] or 0,
                'prev_price': t['close_price_yesterday'] or 0
            }

        if t_type == 'buy':
            cost = (qty * price) + comm
            current_cash -= cost
            if sym:
                positions[sym]['qty'] += qty
                positions[sym]['total_cost'] += cost # افزایش بهای تمام شده
                
        elif t_type == 'sell':
            revenue = (qty * price) - comm
            current_cash += revenue
            if sym and positions[sym]['qty'] > 0:
                # کسر از بهای تمام شده به نسبت تعداد فروش (منطق استاندارد حسابداری)
                avg_cost = positions[sym]['total_cost'] / positions[sym]['qty']
                cost_of_sold = qty * avg_cost
                
                positions[sym]['qty'] -= qty
                positions[sym]['total_cost'] -= cost_of_sold
                
        elif t_type == 'deposit': current_cash += price
        elif t_type == 'withdraw': current_cash -= price
        elif t_type == 'dividend': current_cash += price

    # آماده‌سازی خروجی نهایی
    final_holdings = []
    total_stock_value = 0

    for sym, data in positions.items():
        if data['qty'] > 0.001: # فیلتر کردن مقادیر صفر
            market_price = data['last_price']
            # اگر قیمت بازار صفر بود (آپدیت نشده)، از میانگین خرید استفاده کن تا سود/زیان فضایی نشود
            avg_price = data['total_cost'] / data['qty']
            if not market_price: market_price = avg_price
            
            current_val = data['qty'] * market_price
            total_stock_value += current_val
            
            final_holdings.append({
                'symbol': sym,
                'name': data['name'],
                'sector': data['sector'],
                'qty': data['qty'],
                'price': market_price,
                'avg_buy_price': avg_price,
                'total_cost': data['total_cost'],
                'current_value': current_val,
                'daily_change': 0, # می‌توان محاسبه کرد
                'weight': 0
            })

    return final_holdings, current_cash, total_stock_value

def get_portfolio_details(portfolio_id):
    conn = get_db_connection()
    try:
        # 1. دریافت اطلاعات پایه سبد
        portfolio = conn.execute("SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        if not portfolio:
            return None
            
        # 2. دریافت تراکنش‌ها
        transactions = conn.execute('''
            SELECT transaction_type, symbol, quantity, price, commission, amount, date 
            FROM transactions 
            WHERE portfolio_id = ? 
            ORDER BY date ASC, id ASC
        ''', (portfolio_id,)).fetchall()

        # --- متغیرهای محاسباتی ---
        real_time_cash = 0.0          
        net_invested_capital = 0.0    
        holdings_tracker = {}         
        
        # --- پردازش خط به خط تراکنش‌ها ---
        for t in transactions:
            t_type = t['transaction_type']
            qty = float(t['quantity'] or 0)
            price = float(t['price'] or 0)
            comm = float(t['commission'] or 0)
            amount = float(t['amount'] or 0)
            sym = t['symbol']

            if amount == 0 and t_type in ['deposit', 'withdraw', 'dividend']:
                amount = price * (qty if qty > 0 else 1)

            if t_type == 'deposit':
                real_time_cash += amount
                net_invested_capital += amount
            elif t_type == 'withdraw':
                real_time_cash -= amount
                net_invested_capital -= amount
            elif t_type == 'dividend':
                real_time_cash += amount
            elif t_type == 'buy':
                cost = (qty * price) + comm
                real_time_cash -= cost
                if sym not in holdings_tracker: holdings_tracker[sym] = {'qty': 0.0, 'cost': 0.0}
                holdings_tracker[sym]['qty'] += qty
                holdings_tracker[sym]['cost'] += cost
            elif t_type == 'sell':
                revenue = (qty * price) - comm
                real_time_cash += revenue
                if sym in holdings_tracker and holdings_tracker[sym]['qty'] > 0:
                    current_avg_cost = holdings_tracker[sym]['cost'] / holdings_tracker[sym]['qty']
                    cost_of_sold_shares = qty * current_avg_cost
                    holdings_tracker[sym]['qty'] -= qty
                    holdings_tracker[sym]['cost'] -= cost_of_sold_shares
                    if holdings_tracker[sym]['qty'] <= 0:
                        holdings_tracker[sym]['qty'] = 0
                        holdings_tracker[sym]['cost'] = 0

        if net_invested_capital == 0 and portfolio['initial_capital']:
             net_invested_capital = float(portfolio['initial_capital'])
             if real_time_cash == 0: real_time_cash = net_invested_capital

        # 3. محاسبه ارزش روز دارایی‌ها
        total_assets_value = 0.0
        holdings_list = []
        sector_map = {'Stock': 0, 'Gold': 0, 'Fixed': 0, 'Cash': 0}

        for symbol, data in holdings_tracker.items():
            qty = data['qty']
            total_cost = data['cost']
            
            if qty > 0.001: 
                price_row = conn.execute("SELECT last_price, company_name, asset_type, sector FROM market_prices WHERE symbol=?", (symbol,)).fetchone()
                current_price = float(price_row['last_price']) if price_row and price_row['last_price'] else 0.0
                name = price_row['company_name'] if price_row and price_row['company_name'] else symbol
                asset_type = price_row['asset_type'] if price_row and price_row['asset_type'] else 'Stock'
                sector = price_row['sector'] if price_row and price_row['sector'] else 'نامشخص'
                                
                market_value = qty * current_price
                total_assets_value += market_value
                avg_buy_price = total_cost / qty if qty > 0 else 0
                
                holdings_list.append({
                    'symbol': symbol,
                    'name': name,
                    'qty': qty,
                    'price': current_price,
                    'current_value': market_value,
                    'total_cost': total_cost,
                    'avg_buy_price': avg_buy_price,
                    'weight': 0,
                    'asset_type': asset_type,
                    'sector': sector
                })
                
                std_type = 'Stock'
                if 'Gold' in asset_type or 'طلا' in asset_type: std_type = 'Gold'
                elif 'Fixed' in asset_type or 'ثابت' in asset_type: std_type = 'Fixed'
                sector_map[std_type] = sector_map.get(std_type, 0) + market_value

        # 4. ارزش کل پرتفوی (NAV)
        total_portfolio_value = total_assets_value + real_time_cash
        
        # >>> اصلاح مهم: محاسبه مخرج برای درصدها <<<
        # اگر نقدینگی منفی باشد (بدهی)، آن را از مخرج کم نمی‌کنیم تا درصدها به ۱۰۰ نرمال شوند.
        # مخرج = ارزش سهام + (نقدینگی اگر مثبت باشد)
        gross_allocation_base = total_assets_value + (real_time_cash if real_time_cash > 0 else 0)
        if gross_allocation_base == 0: gross_allocation_base = 1 # جلوگیری از تقسیم بر صفر

        # 5. محاسبه وزن‌ها (با مخرج اصلاح شده)
        for h in holdings_list:
            h['weight'] = (h['current_value'] / gross_allocation_base) * 100
        
        # 6. محاسبه بازدهی سبد
        portfolio_return_pct = 0.0
        if net_invested_capital > 0:
            portfolio_return_pct = ((total_portfolio_value - net_invested_capital) / net_invested_capital) * 100

        # 7. محاسبه بازدهی شاخص
        try:
            # الف) دریافت شاخص اولیه (زمان افتتاح)
            initial_index = float(portfolio['initial_index']) if portfolio['initial_index'] else 0.0
            
            # ب) دریافت شاخص لحظه‌ای از جدول market_overview
            idx_row = conn.execute("SELECT total_index FROM market_overview WHERE id = 1").fetchone()
            current_index = float(idx_row['total_index']) if idx_row and idx_row['total_index'] else 0.0

            # ج) اگر شاخص لحظه‌ای صفر بود (هنوز آپدیت نشده)، سعی کن آنلاین بگیری
            if current_index == 0:
                from tsetmc_service import get_market_index
                fetched = get_market_index()
                if fetched: current_index = fetched

            # د) محاسبه درصد بازدهی
            index_return_pct = 0.0
            if initial_index > 0 and current_index > 0:
                index_return_pct = ((current_index - initial_index) / initial_index) * 100
            
            # هـ) محاسبه آلفا (اختلاف عملکرد سبد با شاخص)
            alpha = portfolio_return_pct - index_return_pct

        except Exception as e:
            print(f"Index Calc Error: {e}")
            index_return_pct = 0
            alpha = 0
            current_index = 0
            initial_index = 0

        # 8. داده‌های خروجی نمودار
        sector_alloc = []
        current_alloc = {'Equity': 0, 'Gold': 0, 'Fixed': 0, 'Cash': 0}
        persian_labels = {'Stock': 'سهام', 'Gold': 'طلا', 'Fixed': 'درآمد ثابت', 'Cash': 'نقدینگی'}
        
        sector_map['Cash'] = real_time_cash

        for k, v in sector_map.items():
            # برای محاسبه درصد در نمودار، مقادیر منفی (بدهی) را صفر در نظر می‌گیریم
            val_for_pct = v if v > 0 else 0
            pct = (val_for_pct / gross_allocation_base * 100)
            
            sector_alloc.append({'name': persian_labels.get(k, k), 'value': v, 'percent': pct})
            
            if k == 'Stock': current_alloc['Equity'] = pct
            elif k == 'Gold': current_alloc['Gold'] = pct
            elif k == 'Fixed': current_alloc['Fixed'] = pct
            elif k == 'Cash': current_alloc['Cash'] = pct

        # سایر محاسبات (بدون تغییر)
        target_config = conn.execute("SELECT * FROM model_configs WHERE profile_name = ?", (portfolio['risk_level'],)).fetchone()
        if not target_config: target_config = {'target_equity': 0, 'target_gold': 0, 'target_fixed_income': 0}

        diff = abs(current_alloc['Equity'] - target_config['target_equity']) + \
               abs(current_alloc['Gold'] - target_config['target_gold']) + \
               abs(current_alloc['Fixed'] - target_config['target_fixed_income'])
        alignment_score = max(0, 100 - (diff / 2))

        target_assets = conn.execute('''
            SELECT ma.*, mp.last_price 
            FROM model_assets ma 
            LEFT JOIN market_prices mp ON ma.symbol = mp.symbol
            WHERE ma.profile_name = ?
        ''', (portfolio['risk_level'],)).fetchall()

        risk_data = calculate_risk_analysis(portfolio_id)

        return {
            'info': dict(portfolio),
            'holdings': holdings_list,
            'sectors': [{'name': k, 'value': v} for k,v in sector_map.items()],
            'total_value': total_portfolio_value,
            'cash_balance': real_time_cash,
            'net_invested': net_invested_capital,
            'benchmark': {
                'portfolio_return': round(portfolio_return_pct, 2),
                'index_return': round(index_return_pct, 2),
                'alpha': round(alpha, 2),
                'current_index': current_index,
                'initial_index': initial_index
            },
            'target_config': dict(target_config),
            'target_assets': [dict(t) for t in target_assets],
            'alignment_score': int(alignment_score),
            'current_allocation': current_alloc,
            'risk_analysis': risk_data
        }

    except Exception as e:
        print(f"CRITICAL ERROR in get_portfolio_details: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        conn.close()


def get_portfolio_summary(current_user_id=None, is_admin=False):
    """دریافت خلاصه وضعیت تمام سبدها برای داشبورد"""
    conn = get_db_connection()
    q = 'SELECT * FROM portfolios' if is_admin else 'SELECT * FROM portfolios WHERE owner_id = ?'
    p_params = [] if is_admin else [current_user_id]
    portfolios = conn.execute(q, p_params).fetchall()
    conn.close()
    
    # تابع کمکی برای تبدیل امن اعداد
    def safe_float(val):
        if not val: return 0.0
        try:
            return float(str(val).replace(',', '').strip())
        except:
            return 0.0

    summary_data = []
    for p in portfolios:
        details = get_portfolio_details(p['id'])
        
        if details:
            initial_cap = safe_float(p['initial_capital'])
            pl_amount = details['total_value'] - initial_cap
            
            summary_data.append({
                'id': p['id'],
                'name': p['name'],
                'manager': p['manager_name'],
                'national_id': p['national_id'],
                'broker': p['broker'],
                'risk_level': p['risk_level'],
                
                # ارسال مقادیر خام برای ویرایش
                'initial_capital': initial_cap, 
                'delivery_date': p['delivery_date'],
                'description': p['description'] if p['description'] else '',
                'initial_index': p['initial_index'],
                
                # داده‌های مالی
                'total_value': details['total_value'],
                'cash_balance': details['cash_balance'], 
                'pl_amount': pl_amount,
                'pl_percent': details['benchmark']['portfolio_return'], 
                'alpha': details['benchmark']['alpha'],
                'owner_id': p['owner_id']
            })
            
    return summary_data


    
# =========================================================
# 2. مدیریت تراکنش‌ها و پرتفوی
# =========================================================

def create_new_portfolio(data, initial_stocks, owner_id):
   
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # 1. محاسبه مقادیر مالی
        stocks_value = 0
        for s in initial_stocks:
            try:
                qty = float(str(s['qty']).replace(',', ''))
                price = float(str(s['price']).replace(',', ''))
                stocks_value += (qty * price)
            except (ValueError, KeyError):
                continue
            
        total_capital = float(data['initial_cash']) + stocks_value

        # 2. ثبت پرتفوی
        c.execute('''
            INSERT INTO portfolios 
            (owner_id, name, manager_name, broker, national_id, risk_level, 
             description, created_at, delivery_date, initial_index, initial_capital, 
             initial_stock_value, initial_cash, current_cash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (owner_id, data['name'], data['manager'], data.get('broker', ''), 
              data.get('national_id', ''), data.get('risk_level', 'Medium'), 
              data.get('desc', ''), datetime.now().strftime('%Y-%m-%d'), 
              data['date'], data.get('initial_index', 0), total_capital,
              stocks_value, data['initial_cash'], data['initial_cash']))
        
        portfolio_id = c.lastrowid

        # 3. ثبت تراکنش‌ها
        transactions_list = []
        if total_capital > 0:
            transactions_list.append((portfolio_id, 'deposit', 'CASH', 'بانکی', 1, total_capital, total_capital, 0, data['date'], 'Cash'))
        
        for stock in initial_stocks:
            try:
                qty = float(str(stock['qty']).replace(',', ''))
                price = float(str(stock['price']).replace(',', ''))
                if qty > 0 and price >= 0:
                    total_val = qty * price
                    sec = c.execute("SELECT sector, asset_type FROM market_prices WHERE symbol=?", (stock['symbol'],)).fetchone()
                    sector = sec['sector'] if sec else 'سایر'
                    a_type = sec['asset_type'] if sec else 'Stock'
                    transactions_list.append((portfolio_id, 'buy', stock['symbol'], sector, qty, price, total_val, 0, data['date'], a_type))
            except: continue

        if transactions_list:
            c.executemany('''
                INSERT INTO transactions 
                (portfolio_id, transaction_type, symbol, sector, quantity, price, amount, commission, date, asset_class)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', transactions_list)

        conn.commit()
        return True

    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()

def update_portfolio_info(portfolio_id, data):
    conn = get_db_connection()
    try:
        # Add risk_level to the SQL UPDATE statement
        conn.execute('''
            UPDATE portfolios SET 
                name=?, manager_name=?, broker=?, national_id=?, initial_capital=?, 
                delivery_date=?, description=?, initial_index=?, risk_level=? 
            WHERE id=?
        ''', (data['name'], data['manager'], data['broker'], data['national_id'], 
              data['capital'], data['date'], data['desc'], data['index'], 
              data['risk_level'], portfolio_id)) # ADDED risk_level
        conn.commit()
    except Exception as e:
        print(f"Update portfolio error: {e}")
    finally:
        conn.close()
        
def delete_portfolio_full(portfolio_id):
    conn = get_db_connection()
    for t in ['transactions', 'portfolio_history', 'calendar_events']:
        conn.execute(f"DELETE FROM {t} WHERE portfolio_id=?", (portfolio_id,))
    conn.execute("DELETE FROM portfolios WHERE id=?", (portfolio_id,))
    conn.commit()
    conn.close()

def delete_transaction(tid):
    conn = get_db_connection()
    # ابتدا ID پرتفوی را می‌گیریم تا بعدا نقدینگی‌اش را آپدیت کنیم
    row = conn.execute("SELECT portfolio_id FROM transactions WHERE id=?", (tid,)).fetchone()
    if row:
        pid = row['portfolio_id']
        conn.execute("DELETE FROM transactions WHERE id=?", (tid,))
        conn.commit()
        conn.close()
        # محاسبه مجدد نقدینگی
        recalculate_portfolio_cash(pid)
    else:
        conn.close()

def update_transaction(tid, ty, q, p, d):
    conn = get_db_connection()
    row = conn.execute("SELECT portfolio_id FROM transactions WHERE id=?", (tid,)).fetchone()
    
    # محاسبه مجدد کارمزد در صورت ویرایش (ساده شده)
    # برای دقت بیشتر بهتر است مشابه add_new_transaction عمل شود اما فعلا آپدیت دستی کافیست
    amount = 0
    if ty == 'buy': amount = (q * p) # تقریبی بدون کارمزد جدید
    elif ty == 'sell': amount = (q * p)
    else: amount = p

    conn.execute('UPDATE transactions SET transaction_type=?, quantity=?, price=?, date=?, amount=? WHERE id=?', (ty, q, p, d, amount, tid))
    conn.commit()
    conn.close()
    
    if row:
        recalculate_portfolio_cash(row['portfolio_id'])

# =========================================================
# 3. توابع ضروری دیگر
# =========================================================

def get_transaction_history(portfolio_id, filters=None):
    conn = get_db_connection()
    query = "SELECT * FROM transactions WHERE portfolio_id = ?"
    params = [portfolio_id]
    
    if filters:
        if filters.get('type') and filters['type'] != 'all':
            query += " AND transaction_type = ?"
            params.append(filters['type'])
        if filters.get('start_date') and filters['start_date'].strip():
            query += " AND date >= ?"
            params.append(filters['start_date'])
        if filters.get('end_date') and filters['end_date'].strip():
            query += " AND date <= ?"
            params.append(filters['end_date'])
            
    query += " ORDER BY date DESC, id DESC"
    trans = conn.execute(query, params).fetchall()
    conn.close()
    return trans

def get_symbol_transactions(portfolio_id, symbol):
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM transactions WHERE portfolio_id=? AND symbol=? ORDER BY date DESC, id DESC', (portfolio_id, symbol)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_portfolio_events(pid):
    conn = get_db_connection()
    events = conn.execute('SELECT * FROM calendar_events WHERE portfolio_id = ? ORDER BY event_date DESC', (pid,)).fetchall()
    conn.close()
    return events

def get_holding_at_date(portfolio_id, symbol, check_date):
    """محاسبه تعداد سهام یک نماد در یک تاریخ مشخص (Historical Balance)"""
    conn = get_db_connection()
    try:
        # جمع خریدها منهای فروش‌ها تا قبل از تاریخ مورد نظر
        query = '''
            SELECT SUM(CASE WHEN type='buy' THEN quantity ELSE -quantity END) as balance
            FROM transactions 
            WHERE portfolio_id = ? 
              AND symbol = ? 
              AND date <= ?
        '''
        result = conn.execute(query, (portfolio_id, symbol, check_date)).fetchone()
        return result['balance'] if result and result['balance'] else 0
    except Exception as e:
        print(f"Error calculating historical balance: {e}")
        return 0
    finally:
        conn.close()

def get_all_market_events():
    conn = get_db_connection()
    try:
        query = '''
            SELECT 
                e.id, e.portfolio_id, e.title, 
                e.event_date as date,
                e.event_type as type,
                e.symbol, e.amount,
                p.name as portfolio_name 
            FROM calendar_events e
            LEFT JOIN portfolios p ON e.portfolio_id = p.id
            ORDER BY e.event_date DESC
        '''
        events = conn.execute(query).fetchall()
        return [dict(e) for e in events]
    except Exception as e:
        print(f"Error fetching calendar events: {e}")
        return []
    finally:
        conn.close()

def get_all_dashboard_events():
    """دریافت رویدادهای نزدیک برای نمایش در داشبورد"""
    conn = get_db_connection()
    try:
        query = '''
            SELECT 
                e.id, e.title, e.symbol, e.amount,
                e.event_date as date,
                e.event_type as type,
                p.name as portfolio_name  -- نام سبد از جدول portfolios گرفته می‌شود
            FROM calendar_events e
            LEFT JOIN portfolios p ON e.portfolio_id = p.id
            WHERE e.event_date >= date('now')
            ORDER BY e.event_date ASC
            LIMIT 8
        '''
        events = conn.execute(query).fetchall()
        
        events_list = []
        for e in events:
            # اینجا قبلاً p_name بود که باعث باگ می‌شد
            # ما مقدار خام دیتابیس را می‌فرستیم (اگر نال باشد، در HTML مدیریت می‌شود)
            events_list.append({
                'id': e['id'],           # اضافه کردن ID برای دکمه حذف
                'title': e['title'],
                'date': e['date'],
                'type': e['type'],
                'symbol': e['symbol'],
                'portfolio_name': e['portfolio_name'], # <--- اصلاح شد (هم‌نام با HTML)
                'amount': e['amount']
            })
        return events_list
        
    except Exception as e:
        print(f"Error fetching dashboard events: {e}")
        return []
    finally:
        conn.close()
    
def add_event(portfolio_id, title, date, ev_type, symbol, amount, record_date=None):
    conn = get_db_connection()
    try:
        # نام ستون‌ها در دیتابیس event_date و event_type است
        conn.execute('''
            INSERT INTO calendar_events (portfolio_id, title, event_date, event_type, symbol, amount, record_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (portfolio_id, title, date, ev_type, symbol, amount, record_date))
        conn.commit()
        return True
    except Exception as e:
        print(f"Add Event Error: {e}")
        return False
    finally:
        conn.close()

def update_event(event_id, title, date, ev_type, symbol, amount, record_date=None):
    conn = get_db_connection()
    try:
        conn.execute('''
            UPDATE calendar_events 
            SET title=?, event_date=?, event_type=?, symbol=?, amount=?, record_date=?
            WHERE id=?
        ''', (title, date, ev_type, symbol, amount, record_date, event_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Update Event Error: {e}")
        return False
    finally:
        conn.close()

def delete_event(id):
    conn = get_db_connection()
    conn.execute("DELETE FROM calendar_events WHERE id = ?", (id,))
    conn.commit()
    conn.close()

def process_dividend_payment(event_id):
    conn = get_db_connection()
    event = conn.execute("SELECT * FROM calendar_events WHERE id = ?", (event_id,)).fetchone()
    
    if event and event['event_type'] == 'dividend' and event['is_processed'] == 0:
        # ثبت تراکنش سود نقدی
        conn.execute('''
            INSERT INTO transactions (portfolio_id, symbol, sector, transaction_type, quantity, price, amount, date, commission)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (event['portfolio_id'], 'DPS', 'BANK', 'dividend', 1, event['amount'], event['amount'], event['event_date'], 0))
        
        conn.execute("UPDATE calendar_events SET is_processed = 1 WHERE id = ?", (event_id,))
        conn.commit()
        conn.close()
        
        # آپدیت موجودی نقد
        recalculate_portfolio_cash(event['portfolio_id'])
        return True
        
    conn.close()
    return False

def distribute_corporate_action(symbol, payment_date, record_date, event_type, dps=0, url='', priority='medium'):
    conn = get_db_connection()
    try:
        # دریافت لیست تمام پرتفوی‌ها
        portfolios = conn.execute("SELECT id, name FROM portfolios").fetchall()
        count = 0
        
        base_title = ""
        if event_type == 'dividend':
            base_title = f"واریز سود نقدی {symbol}"
        elif event_type == 'meeting':
            base_title = f"مجمع عمومی {symbol}"
        
        # تاریخ ملاک برای داشتن سهم
        # برای سود نقدی: تاریخ برگزاری مجمع (Record Date) مهم است
        # برای مجمع: همان تاریخ برگزاری (Payment Date در ورودی تابع نقش تاریخ برگزاری را دارد)
        check_date = record_date if event_type == 'dividend' and record_date else payment_date

        for p in portfolios:
            pid = p['id']
            
            # محاسبه تعداد سهام در تاریخ ملاک
            qty = get_holding_at_date(pid, symbol, check_date)
            
            # اگر سهم را در آن تاریخ داشته است
            if qty > 0:
                total_amount = 0
                description = ""
                
                if event_type == 'dividend':
                    total_amount = qty * dps
                    # مبلغ سود محاسبه شده و ذخیره می‌شود
                
                # ثبت رویداد اختصاصی برای این پرتفوی
                conn.execute('''
                    INSERT INTO calendar_events 
                    (portfolio_id, title, event_date, event_type, symbol, amount, record_date, url, priority)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (pid, base_title, payment_date, event_type, symbol, total_amount, record_date, url, priority))
                count += 1
            
        conn.commit()
        return count 
    except Exception as e:
        print(f"Error distributing action: {e}")
        return 0
    finally:
        conn.close()

        
def get_portfolio_chart_data(portfolio_id):
    conn = get_db_connection()
    rows = conn.execute('SELECT record_date, total_equity FROM portfolio_history WHERE portfolio_id = ? ORDER BY record_date ASC', (portfolio_id,)).fetchall()
    conn.close()
    
    labels = []
    data = []
    for r in rows:
        try:
            y, m, d = map(int, r['record_date'].split('-'))
            jd = jdatetime.date.fromgregorian(day=d, month=m, year=y).strftime('%m/%d')
            labels.append(jd)
            data.append(r['total_equity'])
        except:
            pass
            
    return {'labels': labels, 'data': data}

def calculate_trade_performance(portfolio_id):
    conn = get_db_connection()
    transactions = conn.execute('SELECT symbol, transaction_type, quantity, price, commission, date FROM transactions WHERE portfolio_id = ? ORDER BY date ASC, id ASC', (portfolio_id,)).fetchall()
    conn.close()
    
    closed_trades = []
    positions_tracker = {}
    
    for t in transactions:
        sym = t['symbol']
        qty = t['quantity']
        price = t['price']
        comm = t['commission']
        trans_type = t['transaction_type']
        
        if trans_type == 'buy':
            if sym not in positions_tracker: 
                positions_tracker[sym] = {'avg_price': 0, 'qty_on_hand': 0}
            
            curr = positions_tracker[sym]
            cost_new = (qty * price) + comm
            new_qty = curr['qty_on_hand'] + qty
            
            if new_qty > 0:
                curr['avg_price'] = (curr['avg_price'] * curr['qty_on_hand'] + cost_new) / new_qty
            
            curr['qty_on_hand'] = new_qty
            
        elif trans_type == 'sell':
            if sym in positions_tracker and positions_tracker[sym]['qty_on_hand'] > 0:
                curr = positions_tracker[sym]
                revenue = (qty * price) - comm
                cost_of_sold = qty * curr['avg_price']
                
                pnl = revenue - cost_of_sold
                pnl_pct = 0
                if cost_of_sold > 0:
                    pnl_pct = (pnl / cost_of_sold * 100)
                
                result = 'win' if pnl > 0 else 'loss'
                
                closed_trades.append({
                    'symbol': sym,
                    'date': t['date'],
                    'type': 'sell',
                    'pnl': pnl,
                    'pnl_percent': pnl_pct,
                    'result': result
                })
                
                curr['qty_on_hand'] -= qty
                if curr['qty_on_hand'] < 0:
                    curr['qty_on_hand'] = 0

    total_trades = len(closed_trades)
    win_count = len([t for t in closed_trades if t['result'] == 'win'])
    loss_count = total_trades - win_count
    
    win_rate = 0
    if total_trades > 0:
        win_rate = round((win_count / total_trades * 100), 1)
    
    gross_profit = sum(t['pnl'] for t in closed_trades if t['result'] == 'win')
    gross_loss = abs(sum(t['pnl'] for t in closed_trades if t['result'] == 'loss'))
    
    profit_factor = 0
    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 2)
    elif gross_profit > 0:
        profit_factor = 999 
        
    total_pnl = sum(t['pnl'] for t in closed_trades)

    return {
        'total_trades': total_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'total_pnl': total_pnl,
        'win_count': win_count,
        'loss_count': loss_count,
        'trades_history': list(reversed(closed_trades))
    }

def calculate_advanced_metrics(portfolio_id):
    conn = get_db_connection()
    rows = conn.execute('SELECT total_equity FROM portfolio_history WHERE portfolio_id=? ORDER BY record_date ASC', (portfolio_id,)).fetchall()
    conn.close()
    
    if len(rows) < 2:
        return {'volatility': 0, 'sharpe_ratio': 0, 'max_drawdown': 0, 'total_return': 0}
    
    curve = [r['total_equity'] for r in rows]
    returns = []
    for i in range(1, len(curve)):
        if curve[i-1] > 0:
            returns.append((curve[i] - curve[i-1]) / curve[i-1])
            
    if not returns:
        return {'volatility': 0, 'sharpe_ratio': 0, 'max_drawdown': 0, 'total_return': 0}
    
    vol = statistics.stdev(returns) * math.sqrt(242) * 100
    ann_ret = statistics.mean(returns) * 242
    
    sharpe = 0
    if vol > 0:
        sharpe = (ann_ret - 0.25) / (vol / 100)
    
    peak = curve[0]
    max_dd = 0
    for v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
            
    total_return = 0
    if curve[0] > 0:
        total_return = (curve[-1] - curve[0]) / curve[0] * 100
        
    return {
        'volatility': round(vol, 2),
        'sharpe_ratio': round(sharpe, 2),
        'max_drawdown': round(max_dd * 100, 2),
        'total_return': round(total_return, 2)
    }

def calculate_risk_analysis(portfolio_id):
    """محاسبه شاخص‌های ریسک و هشدارهای سبد"""
    conn = get_db_connection()
    try:
        # 1. دریافت دارایی‌ها (تعداد سهام)
        holdings = conn.execute('''
            SELECT symbol, 
                   SUM(CASE WHEN transaction_type='buy' THEN quantity ELSE -quantity END) as qty 
            FROM transactions WHERE portfolio_id=? GROUP BY symbol
        ''', (portfolio_id,)).fetchall()
        
        total_assets_value = 0
        assets_data = []
        
        # 2. محاسبه ارزش هر دارایی
        for h in holdings:
            if h['qty'] > 0:
                price_row = conn.execute("SELECT last_price FROM market_prices WHERE symbol=?", (h['symbol'],)).fetchone()
                price = float(price_row['last_price']) if price_row and price_row['last_price'] else 0.0
                val = h['qty'] * price
                total_assets_value += val
                assets_data.append({'symbol': h['symbol'], 'value': val})
                
        # 3. دریافت نقدینگی
        p_row = conn.execute("SELECT current_cash FROM portfolios WHERE id=?", (portfolio_id,)).fetchone()
        cash = float(p_row['current_cash']) if p_row and p_row['current_cash'] else 0.0
        
        total_portfolio_value = total_assets_value + cash

        # 4. پیدا کردن بیشترین تمرکز (Top Holding)
        top_symbol = "---"
        top_weight = 0.0
        if assets_data and total_portfolio_value > 0:
            # مرتب‌سازی بر اساس ارزش (نزولی)
            sorted_assets = sorted(assets_data, key=lambda x: x['value'], reverse=True)
            top_asset = sorted_assets[0]
            top_symbol = top_asset['symbol']
            top_weight = (top_asset['value'] / total_portfolio_value) * 100

        # 5. تولید هشدارها
        alerts = []
        
        # الف) هشدار تمرکز (بیش از ۲۵٪)
        if top_weight > 25:
            alerts.append({
                'level': 'critical', 
                'type': 'concentration', 
                'symbol': top_symbol,
                'message': f'ریسک تمرکز بالا: نماد {top_symbol} بیش از ۲۵٪ سبد را تشکیل داده است.'
            })
            
        # ب) هشدار نقدینگی مازاد (بیش از ۳۰٪)
        cash_weight = (cash / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
        if cash_weight > 30:
            alerts.append({
                'level': 'warning',
                'type': 'cash',
                'symbol': 'نقدینگی',
                'message': 'انباشت نقدینگی: بیش از ۳۰٪ سرمایه راکد است.'
            })

        return {
            'alert_count': len(alerts),
            'top_holding_symbol': top_symbol,
            'top_holding_weight': round(top_weight, 1),
            'alerts': alerts
        }

    except Exception as e:
        print(f"Risk Calc Error: {e}")
        return None
    finally:
        conn.close()

def generate_smart_insights(portfolio_id):
    details = get_portfolio_details(portfolio_id)
    if not details: return []
    
    insights = []
    holdings = details['holdings']
    total_val = details['total_value']
    
    cash_pct = 0
    if total_val > 0:
        cash_pct = (details['cash_balance'] / total_val * 100)
        
    if cash_pct > 30:
        insights.append({'type': 'warning', 'title': 'نقدینگی بالا', 'text': f"{int(cash_pct)}% از سبد نقد است."})
    elif cash_pct < 2:
        insights.append({'type': 'danger', 'title': 'نقدینگی پایین', 'text': "نقدینگی کافی نیست."})

    if holdings:
        sorted_h = sorted(holdings, key=lambda x: (x['current_value'] - x['total_cost']), reverse=True)
        best = sorted_h[0]
        pnl = best['current_value'] - best['total_cost']
        if pnl > 0:
            insights.append({'type': 'success', 'title': 'ستاره سبد', 'text': f"نماد {best['symbol']} بهترین عملکرد را دارد."})

    if details['alignment_score'] < 50:
        insights.append({'type': 'warning', 'title': 'انحراف از مدل', 'text': "ترکیب دارایی‌ها با مدل فاصله دارد."})

    if not insights:
        insights.append({'type': 'success', 'title': 'وضعیت نرمال', 'text': 'مدیریت ریسک مطلوب است.'})

    return insights

def filter_portfolios(criteria):
    conn = get_db_connection()
    all_p = conn.execute('SELECT * FROM portfolios').fetchall()
    conn.close()
    
    results = []
    for p in all_p:
        holdings, cash, stock_val = calculate_positions(p['id'])
        total = stock_val + cash
        match = True
        details = []
        
        if criteria.get('target_symbol'):
            found = False
            for h in holdings:
                if h['symbol'] == criteria['target_symbol']:
                    found = True
                    break
            if not found:
                match = False
            else:
                details.append(f"دارای {criteria['target_symbol']}")
                
        if criteria.get('min_cash_percent'):
            c_pct = 0
            if total > 0:
                c_pct = (cash / total) * 100
            if c_pct < float(criteria['min_cash_percent']):
                match = False
                
        if match:
            results.append({
                'id': p['id'], 
                'name': p['name'], 
                'manager': p['manager_name'], 
                'total_equity': total, 
                'details': ", ".join(details)
            })
            
    return results

def perform_stress_test(portfolio_id, scenario):
    """
    NOTE: This function requires that get_portfolio_details correctly adds 'asset_type' 
    to each dictionary in the 'holdings' list.
    """
    details = get_portfolio_details(portfolio_id)
    if not details: return None
    
    current_total_value = details['total_value']
    # Start with cash, which is unaffected by market shocks.
    projected_total_value = details['cash_balance']
    
    simulated_holdings = []

    # Map asset_type to the Persian category name used by the scenario keys.
    persian_labels = {'Stock': 'سهام', 'Gold': 'طلا', 'Fixed': 'درآمد ثابت'}

    for holding in details['holdings']:
        asset_type = holding.get('asset_type', 'Stock')
        
        category_name_en = 'Stock' # Default
        if 'Gold' in asset_type or 'طلا' in asset_type: category_name_en = 'Gold'
        elif 'Fixed' in asset_type or 'ثابت' in asset_type: category_name_en = 'Fixed'

        # Look up shock percentage using the Persian name, which matches the form submission.
        shock_pct = float(scenario.get(persian_labels.get(category_name_en, 'سهام'), 0))
        
        new_value = holding['current_value'] * (1 + (shock_pct / 100))
        projected_total_value += new_value
        
        simulated_holdings.append({
            'symbol': holding['symbol'],
            'sector': persian_labels.get(category_name_en, 'سهام'),
            'new_value': new_value,
            'shock': shock_pct,
            'impact': new_value - holding['current_value']
        })
        
    change_amount = projected_total_value - current_total_value
    change_pct = (change_amount / current_total_value * 100) if current_total_value > 0 else 0
    
    return {
        'info': details['info'],
        'current_equity': current_total_value,
        'projected_equity': projected_total_value,
        'change_amount': change_amount,
        'change_pct': change_pct,
        'simulated_holdings': simulated_holdings
    }

def get_watchlist_data(): return [] 
def add_to_watchlist(*args): pass
def remove_from_watchlist(id): pass
def get_all_users():
    conn=get_db_connection()
    u=conn.execute('SELECT * FROM users').fetchall()
    conn.close()
    return u
def create_new_user(u,p,f,r):
    conn=get_db_connection()
    try:
        conn.execute('INSERT INTO users (username,password,full_name,role) VALUES (?,?,?,?)',(u,p,f,r))
        conn.commit()
        res=True
    except:
        res=False
    conn.close()
    return res
def delete_user(uid):
    conn=get_db_connection()
    u=conn.execute("SELECT username FROM users WHERE id=?",(uid,)).fetchone()
    if u and u['username']=='admin':
        conn.close()
        return False
    conn.execute("DELETE FROM users WHERE id=?",(uid,))
    conn.commit()
    conn.close()
    return True
def update_user_role(uid,r,p=None):
    conn=get_db_connection()
    if p:
        conn.execute("UPDATE users SET role=?, password=? WHERE id=?", (r, p, uid))
    else:
        conn.execute("UPDATE users SET role=? WHERE id=?", (r, uid))
    conn.commit()
    conn.close()
def get_model_configs():
    conn=get_db_connection()
    rows=conn.execute('SELECT * FROM model_configs').fetchall()
    conn.close()
    return {r['profile_name']:r for r in rows}
def update_model_config(p,f,g,e):
    conn=get_db_connection()
    conn.execute('UPDATE model_configs SET target_fixed_income=?, target_gold=?, target_equity=? WHERE profile_name=?', (f,g,e,p))
    conn.commit()
    conn.close()

def get_model_details():
    """دریافت تنظیمات کلان و ریز دارایی‌ها با پشتیبانی از نام قابل ویرایش"""
    conn = get_db_connection()
    profiles = ['Low', 'Medium', 'High']
    models_data = []
    
    # نام‌های پیش‌فرض برای حالتی که دیتابیس خالی است
    default_names = {
        'Low': 'کم‌ریسک', 
        'Medium': 'متعادل', 
        'High': 'جسورانه'
    }

    for profile in profiles:
        # 1. دریافت وزن‌های کلان + نام نمایشی
        # نکته: فرض بر این است که ستون display_name را به دیتابیس اضافه کرده‌اید
        try:
            config = conn.execute('SELECT * FROM model_configs WHERE profile_name = ?', (profile,)).fetchone()
        except Exception:
            # اگر ستون display_name هنوز نباشد، موقتا خطا ندهد (برای اطمینان)
            config = conn.execute('SELECT profile_name, target_equity, target_gold, target_fixed_income FROM model_configs WHERE profile_name = ?', (profile,)).fetchone()

        if not config:
            # ساخت رکورد پیش‌فرض در صورت نبودن
            d_name = default_names.get(profile, profile)
            conn.execute('''
                INSERT OR IGNORE INTO model_configs 
                (profile_name, display_name, target_equity, target_gold, target_fixed_income) 
                VALUES (?, ?, 30, 30, 40)
            ''', (profile, d_name))
            conn.commit()
            config = {'target_equity': 30, 'target_gold': 30, 'target_fixed_income': 40, 'display_name': d_name}

        # تعیین نام نمایشی (اگر در دیتابیس null بود، از نام پروفایل استفاده کن)
        # استفاده از .keys() برای اطمینان از وجود ستون
        display_name = config['display_name'] if 'display_name' in config.keys() and config['display_name'] else default_names.get(profile, profile)

        # 2. دریافت ریز دارایی‌های پیشنهادی
        assets_query = '''
            SELECT ma.id, ma.symbol, ma.target_weight, m.last_price, m.company_name, 
                   IFNULL(m.asset_type, 'Stock') as asset_type
            FROM model_assets ma
            LEFT JOIN market_prices m ON ma.symbol = m.symbol
            WHERE ma.profile_name = ?
            ORDER BY ma.target_weight DESC
        '''
        assets = conn.execute(assets_query, (profile,)).fetchall()
        
        models_data.append({
            'name': display_name,        # نام فارسی/قابل ویرایش
            'risk_level': profile,       # شناسه فنی (Low/Medium/High)
            'config': {
                'Equity': config['target_equity'],
                'Gold': config['target_gold'],
                'Fixed': config['target_fixed_income']
            },
            'assets': assets
        })
    
    conn.close()
    return models_data

def add_model_asset(d):
    conn=get_db_connection()
    conn.execute('INSERT INTO model_assets (profile_name, symbol, target_weight, stop_loss, target_short, target_mid, target_long, note) VALUES (?,?,?,?,?,?,?,?)', (d['profile'], d['symbol'], d['weight'], d['stop'], d['t_short'], d['t_mid'], d['t_long'], d['note']))
    conn.commit()
    conn.close()
def delete_model_asset(id):
    conn=get_db_connection()
    conn.execute('DELETE FROM model_assets WHERE id=?', (id,))
    conn.commit()
    conn.close()

def get_analysis_signals(current_user_id):
    conn = get_db_connection()
    try:
        uid = int(current_user_id)
        
        query = '''
            SELECT a.*, 
                   m.last_price, 
                   m.company_name, 
                   u.full_name as analyst_name 
            FROM analysis_signals a 
            LEFT JOIN market_prices m ON a.symbol = m.symbol 
            LEFT JOIN users u ON a.owner_id = u.id 
            WHERE a.owner_id = ? 
            ORDER BY a.added_at DESC
        '''
        signals = conn.execute(query, (uid,)).fetchall()
    except Exception as e:
        print(f"DB SELECT ERROR: {e}")
        signals = []
    finally:
        conn.close()
    
    results = []
    for s in signals:
        current_price = s['last_price'] if s['last_price'] is not None else 0
        
        results.append({
            'id': s['id'],
            'symbol': s['symbol'],
            'name': s['company_name'] or s['symbol'],
            'price': current_price,
            'target': s['target_sell_price'] or 0,
            'stop': s['stop_loss_price'] or 0,
            'buy': s['target_buy_price'] or 0,
            'note': s['analysis_note'],
            'analyst': 'من',
            'added_at': s['added_at'],
            'status': 'neutral', # ساده‌سازی برای دیباگ
            'rr_ratio': 0,
            'is_public': s['is_public'] if 'is_public' in s.keys() else 0
        })
    return results

def get_shared_signals(current_user_id):
    """دریافت تحلیل‌های عمومی برای نمایش در بخش جامعه"""
    conn = get_db_connection()
    try:
        # دریافت همه سیگنال‌های عمومی (بدون فیلتر مالک)
        query = '''
            SELECT a.*, 
                   m.last_price, 
                   u.full_name,
                   u.username
            FROM analysis_signals a 
            LEFT JOIN market_prices m ON a.symbol = m.symbol 
            LEFT JOIN users u ON a.owner_id = u.id 
            WHERE a.is_public = 1
            ORDER BY a.added_at DESC
        '''
        signals = conn.execute(query).fetchall()
    except Exception as e:
        print(f"Error fetching shared signals: {e}")
        signals = []
    finally:
        conn.close()
    
    results = []
    for s in signals:
        current_price = s['last_price'] if s['last_price'] is not None else 0
        analyst_name = s['full_name'] if s['full_name'] else s['username']
        
        # تعیین وضعیت
        status = "neutral"
        target = s['target_sell_price'] or 0
        stop = s['stop_loss_price'] or 0
        
        if current_price > 0:
            if target > 0 and current_price >= target: status = "target_hit"
            elif stop > 0 and current_price <= stop: status = "stop_hit"
        
        results.append({
            'id': s['id'],
            'symbol': s['symbol'],
            'price': current_price,
            'target': target,
            'stop': stop,
            'buy': s['target_buy_price'] or 0,
            'note': s['analysis_note'],
            'analyst': analyst_name or 'کاربر',
            'added_at': s['added_at'],
            'status': status,
            'is_public': 1
        })
    return results

def add_analysis_signal(data, owner_id):
    conn = get_db_connection()
    try:
        # حذف فاصله‌های اضافی نماد
        sym = data['symbol'].strip()
        uid = int(owner_id)
        
        conn.execute('''
            INSERT INTO analysis_signals 
            (symbol, target_buy_price, target_sell_price, stop_loss_price, 
             analysis_note, target_profile, asset_class, owner_id, is_public, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, CURRENT_DATE)
        ''', (sym, data['buy'], data['sell'], data['stop'], data['note'], data['profile'], data['asset'], uid))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"DB INSERT ERROR: {e}") # چاپ خطا در کنسول
        raise e
    finally:
        conn.close()

def delete_signal(id):
    conn=get_db_connection()
    conn.execute("DELETE FROM analysis_signals WHERE id=?", (id,))
    conn.commit()
    conn.close()
def update_stock_price(s, p): pass

def get_holding_at_date(portfolio_id, symbol, target_date):
    """محاسبه تعداد سهام یک نماد در یک تاریخ خاص"""
    conn = get_db_connection()
    # جمع خریدها و فروش‌ها تا قبل از تاریخ هدف
    txs = conn.execute('''
        SELECT transaction_type, quantity 
        FROM transactions 
        WHERE portfolio_id = ? AND symbol = ? AND date <= ?
    ''', (portfolio_id, symbol, target_date)).fetchall()
    conn.close()
    
    qty = 0
    for t in txs:
        if t['transaction_type'] == 'buy': qty += t['quantity']
        elif t['transaction_type'] == 'sell': qty -= t['quantity']
    
    return max(0, qty)

def get_aggregate_performance(user_id):
    """محاسبه دقیق عملکرد تجمیعی برای داشبورد"""
    conn = get_db_connection()
    p_ids = conn.execute("SELECT id FROM portfolios WHERE owner_id = ?", (user_id,)).fetchall()
    conn.close()
    
    total_trades = 0
    total_wins = 0
    gross_profit = 0
    gross_loss = 0
    total_net_pnl = 0
    
    for p in p_ids:
        # فراخوانی تابع محاسبه عملکرد هر سبد
        perf = calculate_trade_performance(p['id'])
        if perf:
            total_trades += perf['total_trades']
            total_wins += perf['win_count']
            
            # استخراج سود و زیان از تاریخچه معاملات بسته شده
            for t in perf['trades_history']:
                pnl = t['pnl']
                total_net_pnl += pnl
                if pnl > 0: gross_profit += pnl
                else: gross_loss += abs(pnl)
    
    win_rate = round((total_wins / total_trades * 100), 1) if total_trades > 0 else 0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999 if gross_profit > 0 else 0)
    
    return {
        'win_rate': win_rate,
        'total_pnl': total_net_pnl,
        'profit_factor': profit_factor,
        'total_trades': total_trades
    }

def get_watchlist_alerts(user_id):
    """شناسایی نمادهایی که به نقاط حساس تحلیل نزدیک شده‌اند"""
    conn = get_db_connection()
    
    # دریافت تمام تحلیل‌های فعال (هم شخصی و هم عمومی دیگران)
    query = '''
        SELECT a.*, m.last_price, u.full_name as analyst_name 
        FROM analysis_signals a 
        LEFT JOIN market_prices m ON a.symbol = m.symbol 
        LEFT JOIN users u ON a.owner_id = u.id
        WHERE (a.owner_id = ? OR a.is_public = 1)
    '''
    signals = conn.execute(query, (user_id,)).fetchall()
    conn.close()
    
    alerts = []
    THRESHOLD = 0.02 # 2 درصد فاصله برای هشدار
    
    for s in signals:
        current = s['last_price'] or 0
        if current == 0: continue
        
        # بررسی نزدیکی به نقاط حساس
        points = {
            'buy': s['target_buy_price'],
            'target': s['target_sell_price'],
            'stop': s['stop_loss_price']
        }
        
        status = None
        target_val = 0
        
        for p_name, p_val in points.items():
            if p_val and abs(current - p_val) / current <= THRESHOLD:
                if p_name == 'buy': status = 'در محدوده ورود'
                elif p_name == 'target': status = 'در محدوده هدف'
                elif p_name == 'stop': status = 'در محدوده حد ضرر'
                target_val = p_val
                break
        
        if status:
            is_mine = (s['owner_id'] == user_id)
            tag = 'شخصی' if is_mine else s['analyst_name']
            
            alerts.append({
                'symbol': s['symbol'],
                'current_price': current,
                'target_val': target_val,
                'status': status,
                'tag': tag,
                'is_mine': is_mine
            })
            
    return alerts

def get_screener_data():
    """دریافت داده‌های غربالگر با محاسبه دقیق نقدینگی از روی تراکنش‌ها (نسخه ایمن شده)"""
    conn = get_db_connection()
    try:
        portfolios = conn.execute("SELECT id, name, manager_name FROM portfolios").fetchall()
        results = []
        
        for p in portfolios:
            try:
                pid = p['id']
                
                # 1. محاسبه دقیق نقدینگی از روی تراکنش‌ها (Real-time Calculation)
                # فرمول: (واریز + فروش + سود نقدی) - (برداشت + خرید)
                cash_calc = conn.execute('''
                    SELECT 
                        SUM(CASE WHEN transaction_type IN ('deposit', 'sell', 'dividend') THEN amount ELSE 0 END) -
                        SUM(CASE WHEN transaction_type IN ('withdraw', 'buy') THEN amount ELSE 0 END) as balance
                    FROM transactions 
                    WHERE portfolio_id = ?
                ''', (pid,)).fetchone()
                
                # تبدیل ایمن به float (اگر None بود، 0 شود)
                cash = float(cash_calc['balance']) if cash_calc and cash_calc['balance'] is not None else 0.0
                
                # 2. محاسبه ارزش روز دارایی‌های سهامی/طلا
                holdings = conn.execute('''
                    SELECT symbol, asset_class 
                    FROM transactions 
                    WHERE portfolio_id = ? 
                    GROUP BY symbol
                ''', (pid,)).fetchall()
                
                current_holdings_value = 0.0
                asset_classes = set()
                symbols_list = []
                
                for h in holdings:
                    # محاسبه تعداد مانده سهم
                    qty_row = conn.execute('''
                        SELECT SUM(CASE WHEN transaction_type='buy' THEN quantity ELSE -quantity END) as balance
                        FROM transactions WHERE portfolio_id = ? AND symbol = ?
                    ''', (pid, h['symbol'])).fetchone()
                    
                    qty = float(qty_row['balance']) if qty_row and qty_row['balance'] is not None else 0.0
                    
                    if qty > 0:
                        # دریافت قیمت روز
                        price_row = conn.execute("SELECT last_price FROM market_prices WHERE symbol = ?", (h['symbol'],)).fetchone()
                        price = float(price_row['last_price']) if price_row and price_row['last_price'] is not None else 0.0
                        
                        current_holdings_value += (qty * price)
                        if h['asset_class']: asset_classes.add(h['asset_class'])
                        symbols_list.append(h['symbol'])
                    
                total_value = cash + current_holdings_value
                
                # 3. محاسبه سود/زیان
                # سرمایه آورده = واریز - برداشت
                net_invested_row = conn.execute('''
                    SELECT SUM(CASE WHEN transaction_type='deposit' THEN amount ELSE -amount END) as net
                    FROM transactions WHERE portfolio_id = ? AND transaction_type IN ('deposit', 'withdraw')
                ''', (pid,)).fetchone()
                
                invested = float(net_invested_row['net']) if net_invested_row and net_invested_row['net'] is not None else 0.0
                
                # هندل کردن حالت خاص (سرمایه صفر ولی ارزش مثبت - مثلا سود نقدی مانده)
                if invested <= 0 and total_value > 0:
                     invested = total_value # جلوگیری از تقسیم بر صفر یا درصد اشتباه
                
                pnl = total_value - invested
                pnl_percent = (pnl / invested * 100) if invested > 0 else 0.0
                
                results.append({
                    'id': pid,
                    'name': p['name'],
                    'manager': p['manager_name'],
                    'cash': cash,
                    'total_value': total_value,
                    'pnl': pnl,
                    'pnl_percent': round(pnl_percent, 2),
                    'assets': list(asset_classes),
                    'symbols': " ".join(symbols_list)
                })
            except Exception as inner_e:
                print(f"Error calculating portfolio {p.get('name')}: {inner_e}")
                continue # اگر یک سبد مشکل داشت، بقیه را خراب نکند
                
        return results

    except Exception as e:
        print(f"Global Error in get_screener_data: {e}")
        return []
    finally:
        conn.close()