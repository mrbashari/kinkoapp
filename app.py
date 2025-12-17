import os
import json
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message

# ایمپورت‌های دیتابیس و تحلیل
from database import init_db, add_new_transaction, get_all_market_prices, update_stock_price, get_db_connection

from analysis import (
    get_portfolio_summary, get_portfolio_details, calculate_trade_performance, 
    calculate_risk_analysis, get_portfolio_chart_data, filter_portfolios, 
    calculate_advanced_metrics, generate_smart_insights, 
    get_model_configs, update_model_config, get_analysis_signals, add_analysis_signal, delete_signal,
    get_model_details, add_model_asset, delete_model_asset,
    get_portfolio_events, add_event, process_dividend_payment, delete_event, distribute_corporate_action, 
    perform_stress_test, create_new_portfolio, update_portfolio_info, 
    delete_portfolio_full, get_transaction_history, delete_transaction, get_symbol_transactions, update_transaction,
    get_all_users, create_new_user, delete_user, update_event, update_user_role,
    get_all_market_events, get_all_dashboard_events, get_watchlist_alerts, get_shared_signals, get_screener_data
)
from utils import format_currency, to_jalali, to_persian_num, format_large_number, clean_input_number
from models import User
from tsetmc_service import fetch_market_data

app = Flask(__name__)
app.secret_key = 'my_super_secret_key_123'

log_handler = logging.StreamHandler()
log_handler.setLevel(logging.INFO)
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.INFO)

# تنظیمات جیمیل (Gmail)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'bash.mehdi@gmail.com'  # ایمیل خودتان را اینجا بنویسید
app.config['MAIL_PASSWORD'] = 'fppf anle bigf vazc'     # رمز عبور اپلیکیشن (توضیح در مرحله ۳)
app.config['MAIL_DEFAULT_SENDER'] = 'bash.mehdi@gmail.com'

mail = Mail(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id): return User.get(user_id)

app.jinja_env.filters['currency'] = format_currency
app.jinja_env.filters['jalali'] = to_jalali
app.jinja_env.filters['persian_num'] = to_persian_num
app.jinja_env.filters['large_fmt'] = format_large_number

@app.context_processor
def inject_global_vars():
    vars_dict = {'holidays': ["2024-03-20", "2024-03-21"]}
    if current_user.is_authenticated:
        try:
            is_admin = (current_user.role == 'admin')
            portfolios = get_portfolio_summary(current_user.id, is_admin)
            vars_dict['global_aum'] = sum(p['total_value'] for p in portfolios)
        except: vars_dict['global_aum'] = 0
    return vars_dict

def check_portfolio_access(portfolio_id):
    if current_user.role == 'admin': return True
    from database import get_db_connection
    conn = get_db_connection()
    p = conn.execute("SELECT owner_id FROM portfolios WHERE id=?", (portfolio_id,)).fetchone()
    conn.close()
    if p and p['owner_id'] == current_user.id: return True
    return False

# --- Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_data = User.find_by_username(request.form['username'])
        if user_data and user_data['password'] == request.form['password']:
            login_user(User(id=user_data['id'], username=user_data['username'], full_name=user_data['full_name'], role=user_data['role']))
            return redirect(url_for('dashboard'))
        else: flash('اطلاعات ورود اشتباه است.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    is_admin = (current_user.role == 'admin')
    portfolios = get_portfolio_summary(current_user.id, is_admin)
    calendar_events = get_all_dashboard_events()
    total_aum = sum(p['total_value'] for p in portfolios)
    watchlist = get_watchlist_alerts(current_user.id) # دریافت هشدارها
    
    # داده‌های جدید برای داشبورد مدیریتی
    from analysis import get_aggregate_performance
    agg_perf = get_aggregate_performance(current_user.id)
    shared_signals = get_shared_signals(current_user.id)
    
    return render_template('dashboard.html', 
                           portfolios=portfolios, 
                           total_aum=total_aum, 
                           all_events=calendar_events,
                           agg_perf=agg_perf,
                           shared_signals=shared_signals,
                           watchlist=watchlist,
                           market_data=get_all_market_prices())
                           

@app.route('/portfolios/manage', methods=['GET', 'POST'])
@login_required
def manage_portfolios():
    # --- بخش ایجاد پرتفوی جدید (POST) ---
    if request.method == 'POST':
        try:
            # 1. جمع‌آوری اطلاعات فرم در یک دیکشنری تمیز
            data = {
                'name': request.form['name'],
                'manager': request.form['manager'],
                'broker': request.form.get('broker', ''), # این فیلد حالا خوانده می‌شود
                'national_id': request.form.get('national_id', ''),
                'risk_level': request.form.get('risk_level', 'Medium'),
                'desc': request.form.get('description', ''),
                'date': request.form.get('delivery_date'),
                'initial_index': clean_input_number(request.form.get('initial_index')),
                'initial_cash': clean_input_number(request.form.get('initial_cash'))
            }
            
            # 2. دریافت لیست سهام
            stocks_json = request.form.get('stocks_json', '[]')
            try:
                initial_stocks = json.loads(stocks_json)
            except:
                initial_stocks = []
            
            from analysis import create_new_portfolio
            
            success = create_new_portfolio(data, initial_stocks, current_user.id)
            
            if success:
                flash(f"پرتفوی «{data['name']}» با موفقیت افتتاح شد.", "success")
            else:
                flash("خطا در ثبت اطلاعات در دیتابیس.", "error")
            
        except Exception as e:
            app.logger.error(f"FATAL ERROR during portfolio creation: {e}", exc_info=True)
            flash(f"خطا در سرور: {e}", "error")
            
        # ریدایرکت برای جلوگیری از ارسال مجدد فرم
        return redirect(url_for('manage_portfolios'))

    # --- بخش نمایش (GET) ---
    is_admin = (current_user.role == 'admin')
    return render_template('manage_portfolios.html', 
                           portfolios=get_portfolio_summary(current_user.id, is_admin), 
                           market_data=get_all_market_prices(), 
                           managers=get_all_users())


@app.route('/portfolios/delete/<int:portfolio_id>')
@login_required
def delete_portfolio_route(portfolio_id):
    if not check_portfolio_access(portfolio_id): return redirect(url_for('manage_portfolios'))
    delete_portfolio_full(portfolio_id)
    flash("پرتفوی حذف شد.", "success")
    return redirect(url_for('manage_portfolios'))

@app.route('/portfolios/edit/<int:portfolio_id>', methods=['POST'])
@login_required
def edit_portfolio_route(portfolio_id):
    if not check_portfolio_access(portfolio_id): 
        return redirect(url_for('manage_portfolios'))

    # Collect all form data, including the new risk_level field
    data_to_update = {
        'name': request.form['name'],
        'manager': request.form['manager'],
        'risk_level': request.form.get('risk_level', 'Medium'), # ADDED
        'broker': request.form.get('broker', ''),
        'national_id': request.form.get('national_id', ''),
        'capital': clean_input_number(request.form['capital']),
        'date': request.form['delivery_date'],
        'desc': request.form.get('description', ''),
        'index': clean_input_number(request.form.get('initial_index'))
    }
    
    update_portfolio_info(portfolio_id, data_to_update)
    flash("اطلاعات ویرایش شد.", "success")
    return redirect(url_for('manage_portfolios'))

@app.route('/portfolio/<int:portfolio_id>')
@login_required
def portfolio_details(portfolio_id):
    if not check_portfolio_access(portfolio_id): return "Access Denied", 403
    result = get_portfolio_details(portfolio_id)
    if result is None: return "پرتفوی یافت نشد", 404
    chart_data = get_portfolio_chart_data(portfolio_id)
    insights = generate_smart_insights(portfolio_id)
    return render_template('portfolio_details.html', my_portfolio=result, target_config=result['target_config'], my_alignment_score=result['alignment_score'], current_allocation=result['current_allocation'], chart_data=chart_data, insights=insights, market_data=get_all_market_prices())

# --- روت تقویم و یادداشت ---
# در app.py جایگزین روت قبلی portfolio_calendar شود
@app.route('/portfolio/<int:portfolio_id>/calendar', methods=['GET', 'POST'])
@login_required
def portfolio_calendar(portfolio_id):
    if not check_portfolio_access(portfolio_id): return "Access Denied", 403
    
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        if form_type == 'note':
            title = request.form['note_text']
            date = datetime.now().strftime('%Y-%m-%d')
            add_event(portfolio_id, title, date, 'note', '', 0)
            flash("یادداشت ذخیره شد.", "success")
            
        else:
            title_raw = request.form['title']
            date = request.form['date'] # تاریخ پرداخت سود
            record_date = request.form.get('record_date') # تاریخ مجمع (جدید)
            ev_type = request.form['type']
            symbol = request.form.get('symbol', '')
            amount_per_share = clean_input_number(request.form.get('amount')) # DPS
            
            final_amount = amount_per_share
            final_title = title_raw

            # لاجیک جدید: محاسبه سود کل
            if ev_type == 'dividend' and symbol:
                from analysis import get_holding_at_date
                # اگر تاریخ مجمع وارد شده بود استفاده کن، وگرنه همان تاریخ پرداخت
                calc_date = record_date if record_date else date
                qty = get_holding_at_date(portfolio_id, symbol, calc_date)
                
                if qty > 0:
                    total_div = qty * amount_per_share
                    final_amount = total_div
                    # عنوان خطی و جذاب
                    final_title = f"واریز سود نقدی {symbol}"
                else:
                    final_amount = 0
                    flash(f"هشدار: در تاریخ {calc_date} سهامی از {symbol} نداشتید.", "warning")

            add_event(portfolio_id, final_title, date, ev_type, symbol, final_amount)
            flash("رویداد ثبت شد.", "success")
            
        return redirect(url_for('portfolio_calendar', portfolio_id=portfolio_id))
    
    events = get_portfolio_events(portfolio_id)
    details = get_portfolio_details(portfolio_id)

    return render_template('calendar.html', events=events, portfolio=details['info'], market_data=get_all_market_prices())

# --- روت ثبت تراکنش داخلی سبد (جایگزین تابع قبلی شود) ---
@app.route('/portfolio/<int:portfolio_id>/add_transaction', methods=['POST'])
@login_required
def add_portfolio_transaction(portfolio_id):
    try:
        # 1. تشخیص اینکه کاربر در تب "معامله" بوده یا "امور مالی"
        action_mode = request.form.get('action_mode', 'trade')
        
        # داده‌های پایه
        data = {
            'portfolio_id': portfolio_id,
            'date': request.form.get('date')
        }

        if action_mode == 'cash':
            # === حالت واریز / برداشت ===
            tx_type = request.form.get('type_cash') # deposit یا withdraw
            amount = clean_input_number(request.form.get('price_cash'))
            
            data.update({
                'type': tx_type,
                'symbol': 'CASH', # نماد قراردادی
                'quantity': 1,
                'price': amount,  # در واریز/برداشت، قیمت همان مبلغ است
                'asset_class': 'Cash'
            })
            
        else:
            # === حالت خرید / فروش ===
            data.update({
                'type': request.form.get('type'), # buy یا sell
                'symbol': request.form.get('symbol'),
                'quantity': clean_input_number(request.form.get('quantity')),
                'price': clean_input_number(request.form.get('price')),
                # کلاس دارایی به صورت اتوماتیک از فیلد مخفی HTML می‌آید
                'asset_class': request.form.get('asset_class', 'Stock') 
            })

        # 2. ارسال به تابع دیتابیس (که نقدینگی را هم آپدیت می‌کند)
        if add_new_transaction(data):
            flash("تراکنش با موفقیت ثبت شد.", "success")
        else:
            flash("خطا در ثبت تراکنش.", "error")

    except Exception as e:
        print(f"Portfolio Add Error: {e}")
        flash(f"خطا: {e}", "error")

    # بازگشت به همان صفحه سبد
    return redirect(url_for('portfolio_details', portfolio_id=portfolio_id))

@app.route('/portfolio/<int:portfolio_id>/turnover')
@login_required
def portfolio_turnover(portfolio_id):
    if not check_portfolio_access(portfolio_id): return "Access Denied", 403
    filters = {'type': request.args.get('type'), 'start_date': request.args.get('start_date'), 'end_date': request.args.get('end_date')}
    history = get_transaction_history(portfolio_id, filters)
    details = get_portfolio_details(portfolio_id)
    return render_template('turnover.html', portfolio=details['info'], transactions=history, filters=filters)

@app.route('/api/portfolio/<int:pid>/history')
@login_required
def get_full_history_api(pid):
    try:
        # بررسی دسترسی
        if not check_portfolio_access(pid): 
            return jsonify({"error": "Access Denied"}), 403
        
        # دریافت داده‌ها از تابع کمکی
        history = get_transaction_history(pid) 
        
        # تبدیل داده‌های دیتابیس به فرمت قابل ارسال (JSON)
        history_list = []
        for row in history:
            # تبدیل هر ردیف به دیکشنری
            r_dict = dict(row)
            # اطمینان از اینکه مقادیر نال نیستند
            if not r_dict.get('symbol'): r_dict['symbol'] = 'CASH'
            history_list.append(r_dict)

        return jsonify({"transactions": history_list})

    except Exception as e:
        # در صورت بروز خطا، آن را در کنسول چاپ کن و به فرانت اطلاع بده
        print(f"History API Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/portfolio/<int:pid>/transactions/<string:symbol>')
@login_required
def get_symbol_history_api(pid, symbol):
    if not check_portfolio_access(pid): return {"error": "Access Denied"}, 403
    trans = get_symbol_transactions(pid, symbol)
    return jsonify({"transactions": trans})
    
# --- روت تست استرس ---
@app.route('/api/portfolio/<int:portfolio_id>/stress_test', methods=['POST'])
@login_required
def api_stress_test(portfolio_id):
    if not check_portfolio_access(portfolio_id): return {"error": "Access Denied"}, 403
    scenario = request.json
    from analysis import perform_stress_test
    result = perform_stress_test(portfolio_id, scenario)
    if result: return jsonify(result)
    return {"error": "Failed"}, 400

@app.route('/transaction/edit', methods=['POST'])
@login_required
def edit_transaction_route():
    update_transaction(request.form['trans_id'], request.form['type'], clean_input_number(request.form['quantity']), clean_input_number(request.form['price']), request.form['date'])
    flash("تراکنش اصلاح شد.", "success")
    return redirect(request.referrer)

@app.route('/transaction/delete/<int:transaction_id>')
@login_required
def remove_transaction(transaction_id):
    delete_transaction(transaction_id)
    flash("تراکنش حذف شد.", "success")
    return redirect(request.referrer)

# --- روت حذف گروهی ---
@app.route('/transaction/delete/bulk', methods=['POST'])
@login_required
def delete_transactions_bulk():
    try:
        data = request.json
        ids = data.get('ids', [])
        count = 0
        for trans_id in ids:
            delete_transaction(trans_id)
            count += 1
        return jsonify({"status": "success", "message": f"{count} تراکنش حذف شد."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/portfolio/<int:portfolio_id>/performance')
@login_required
def portfolio_performance(portfolio_id):
    if not check_portfolio_access(portfolio_id): return "Access Denied", 403
    return render_template('performance.html', portfolio=get_portfolio_details(portfolio_id)['info'], perf=calculate_trade_performance(portfolio_id), metrics=calculate_advanced_metrics(portfolio_id))

@app.route('/portfolio/<int:portfolio_id>/report')
@login_required
def portfolio_report(portfolio_id):
    if not check_portfolio_access(portfolio_id): return "Access Denied", 403
    return render_template('report_print.html', portfolio=get_portfolio_details(portfolio_id)['info'], data=get_portfolio_details(portfolio_id), perf=calculate_trade_performance(portfolio_id), metrics=calculate_advanced_metrics(portfolio_id), chart_data=get_portfolio_chart_data(portfolio_id), report_date=datetime.now().strftime('%Y/%m/%d'), report_time=datetime.now().strftime('%H:%M'))

# --- روت چاپ تاریخچه ---
@app.route('/portfolio/<int:portfolio_id>/history/print')
@login_required
def portfolio_history_print(portfolio_id):
    if not check_portfolio_access(portfolio_id): return "Access Denied", 403
    history = get_transaction_history(portfolio_id) 
    details = get_portfolio_details(portfolio_id)
    return render_template('history_print.html', portfolio=details['info'], transactions=history, report_date=datetime.now().strftime('%Y/%m/%d'), report_time=datetime.now().strftime('%H:%M'))

# --- مدیریت دارایی‌های مدل (Model Assets Management) ---

@app.route('/analysis/model/add', methods=['POST'])
@login_required
def add_model_asset():
    if current_user.username != 'admin': return "Access Denied", 403
    
    profile = request.form['profile']
    symbol = request.form['symbol']
    weight = clean_input_number(request.form['weight'])
    
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO model_assets (profile_name, symbol, target_weight) VALUES (?, ?, ?)", 
                     (profile, symbol, weight))
        conn.commit()
        flash("دارایی با موفقیت به مدل اضافه شد.", "success")
    except Exception as e:
        flash(f"خطا: {e}", "error")
    finally:
        conn.close()
    return redirect(url_for('market_analysis'))

@app.route('/analysis/model/edit', methods=['POST'])
@login_required
def edit_model_asset():
    if current_user.username != 'admin': return "Access Denied", 403
    
    asset_id = request.form['asset_id']
    weight = clean_input_number(request.form['weight'])
    
    conn = get_db_connection()
    conn.execute("UPDATE model_assets SET target_weight = ? WHERE id = ?", (weight, asset_id))
    conn.commit()
    conn.close()
    flash("وزن دارایی بروزرسانی شد.", "success")
    return redirect(url_for('market_analysis'))

@app.route('/analysis/model/delete/<int:asset_id>')
@login_required
def delete_model_asset(asset_id):
    if current_user.username != 'admin': return "Access Denied", 403
    
    conn = get_db_connection()
    conn.execute("DELETE FROM model_assets WHERE id = ?", (asset_id,))
    conn.commit()
    conn.close()
    flash("دارایی از مدل حذف شد.", "success")
    return redirect(url_for('market_analysis'))

@app.route('/analysis/config/edit', methods=['POST'])
@login_required
def edit_model_config():
    if current_user.username != 'admin': return "Access Denied", 403
    
    profile = request.form['profile_name']
    
    # دریافت نام نمایشی جدید (با مقدار پیش‌فرض پروفایل اگر خالی بود)
    display_name = request.form.get('display_name', profile)
    
    equity = clean_input_number(request.form['equity'])
    gold = clean_input_number(request.form['gold'])
    fixed = clean_input_number(request.form['fixed'])
    
    # چک کردن اینکه جمع 100 شود
    total = equity + gold + fixed
    if total != 100:
        flash(f"هشدار: جمع درصدها {total}% است (باید ۱۰۰٪ باشد).", "warning")
    
    conn = get_db_connection()
    try:
        conn.execute('''
            UPDATE model_configs 
            SET display_name = ?, target_equity = ?, target_gold = ?, target_fixed_income = ? 
            WHERE profile_name = ?
        ''', (display_name, equity, gold, fixed, profile))
        conn.commit()
        flash(f"تنظیمات مدل «{display_name}» با موفقیت بروزرسانی شد.", "success")
    except Exception as e:
        print(f"Update Config Error: {e}")
        flash("خطا در بروزرسانی تنظیمات. (آیا ستون display_name در دیتابیس موجود است؟)", "error")
    finally:
        conn.close()
    
    return redirect(url_for('market_analysis'))

@app.route('/analysis', methods=['GET', 'POST'])
@login_required
def market_analysis():
    # --- ثبت سیگنال (POST) ---
    if request.method == 'POST':
        try:
            symbol = request.form.get('symbol')
            buy = clean_input_number(request.form.get('buy_price'))
            sell = clean_input_number(request.form.get('target_price'))
            stop = clean_input_number(request.form.get('stop_loss'))
            note = request.form.get('note', '')
            asset = request.form.get('asset_class', 'Stock')
            
            if not symbol or buy == 0:
                flash("وارد کردن نماد و قیمت ورود الزامی است.", "warning")
            else:
                data = {
                    'symbol': symbol, 
                    'buy': buy, 
                    'sell': sell, 
                    'stop': stop, 
                    'note': note, 
                    'profile': 'Medium', 
                    'asset': asset
                }
                # تبدیل ID به عدد برای اطمینان
                add_analysis_signal(data, int(current_user.id))
                flash("تحلیل جدید با موفقیت ثبت شد.", "success")
                
        except Exception as e:
            # فقط خطای واقعی را در کنسول نگه می‌داریم
            print(f"Error saving signal: {e}")
            flash("خطا در ثبت اطلاعات.", "error")
            
        return redirect(url_for('market_analysis'))

    # --- نمایش صفحه (GET) ---
    try:
        uid = int(current_user.id)
        
        # دریافت تمام داده‌های مورد نیاز
        model_details = get_model_details()
        my_signals = get_analysis_signals(uid)
        shared_signals = get_shared_signals(uid)
        
    except Exception as e:
        print(f"Error loading analysis data: {e}")
        model_details, my_signals, shared_signals = [], [], []

    return render_template('analysis.html', 
                           models=model_details, 
                           signals=my_signals, 
                           shared_signals=shared_signals,
                           market_data=get_all_market_prices())

@app.route('/screener')
@login_required
def screener():
    try:
        data = get_screener_data()
        
        # >>> ردیاب سرور <<<
        print(f"\n🕵️‍♂️ SCREENER DEBUG: Found {len(data)} portfolios.")
        if len(data) > 0:
            print(f"   - Sample Portfolio: {data[0]['name']} (Cash: {data[0]['cash']})")
        else:
            print("   - ❌ LIST IS EMPTY!")
            
    except Exception as e:
        print(f"Error in Screener: {e}")
        data = []

    return render_template('screener.html', portfolios=data)

def safe_float(value):
    """تابع کمکی برای تبدیل امن داده‌ها به عدد (جلوگیری از خطای NoneType)"""
    if value is None or value == '' or value == 'None':
        return 0.0
    try:
        return float(value)
    except:
        return 0.0

@app.route('/api/screener/search', methods=['POST'])
@login_required
def search_screener():
    try:
        filters = request.json
        conn = get_db_connection()
        
        # دریافت همه نمادها
        stocks = conn.execute("SELECT * FROM market_prices").fetchall()
        conn.close()
        
        results = []
        
        # آماده‌سازی عبارت جستجو (حذف فاصله و تبدیل حروف عربی به فارسی)
        search_query = ""
        if filters.get('query'):
            search_query = filters['query'].replace('ك', 'ک').replace('ي', 'ی').strip().lower()

        for stock in stocks:
            try:
                # تبدیل امن داده‌ها به عدد
                raw_price = stock['last_price']
                raw_pe = stock['pe_ratio']
                
                price = float(raw_price) if raw_price is not None else 0.0
                pe = float(raw_pe) if raw_pe is not None else 0.0
                
                # --- اعمال فیلترها ---
                match = True
                
                # 1. فیلتر قیمت
                if filters.get('min_price') and price < float(filters['min_price']): match = False
                if filters.get('max_price') and price > float(filters['max_price']): match = False
                    
                # 2. فیلتر P/E
                if filters.get('min_pe'):
                    # معمولاً PE صفر یا منفی در فیلتر حداقل لحاظ نمی‌شود مگر کاربر بخواهد
                    if pe == 0 or pe < float(filters['min_pe']): match = False
                if filters.get('max_pe'):
                    if pe > float(filters['max_pe']): match = False

                # 3. جستجوی متنی (نام نماد یا شرکت)
                if match and search_query:
                    # استانداردسازی مقادیر دیتابیس برای مقایسه دقیق
                    s_sym = str(stock['symbol'] or '').replace('ك', 'ک').replace('ي', 'ی').lower()
                    s_name = str(stock['company_name'] or '').replace('ك', 'ک').replace('ي', 'ی').lower()
                    
                    if (search_query not in s_sym) and (search_query not in s_name):
                        match = False

                if match:
                    results.append({
                        'symbol': stock['symbol'],
                        'name': stock['company_name'],
                        'price': price,
                        'pe': pe,
                        'sector': stock['sector'] if stock['sector'] else ''
                    })
            except:
                continue

        return jsonify({'results': results, 'count': len(results)}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/analysis/delete/<int:id>')
@login_required
def delete_signal_route(id): delete_signal(id); return redirect(url_for('market_analysis'))

@app.route('/analysis/model/delete/<int:id>')
@login_required
def delete_model_asset_route(id): 
    if current_user.username != 'admin': return "Access Denied", 403
    delete_model_asset(id); return redirect(url_for('market_analysis'))

@app.route('/update-prices')
@login_required
def update_prices_route(): 
    # اول قیمت سهام
    fetch_market_data()
    
    # دوم شاخص کل (اضافه شده)
    from tsetmc_service import get_market_index
    get_market_index()
    
    flash("قیمت‌ها و شاخص بازار با موفقیت به‌روزرسانی شدند.", "success")
    return redirect(request.referrer or url_for('dashboard'))


@app.route('/api/rates')
def api_rates():
    from rates_service import get_latest_rates
    from tsetmc_service import get_market_index
    rates = get_latest_rates(); rates['total_index'] = get_market_index() or 0
    return rates

@app.route('/calendar/global', methods=['GET', 'POST'])
@login_required
def global_calendar():
    if request.method == 'POST':
        try:
            event_id = request.form.get('event_id')
            ev_type = request.form['type']
            symbol = request.form.get('symbol', '').strip()
            payment_date = request.form['date']
            
            # اطلاعات جدید
            record_date = request.form.get('record_date')
            dps = clean_input_number(request.form.get('dps'))
            url = request.form.get('url', '')
            note_priority = request.form.get('note_priority', 'normal')
            title_override = request.form.get('title', '') # برای یادداشت

            if ev_type == 'note':
                add_event(None, title_override, payment_date, 'note', priority=note_priority)
                flash("یادداشت با موفقیت ثبت شد.", "success")
            else:
                # توزیع هوشمند
                count = distribute_corporate_action(symbol, payment_date, record_date, ev_type, dps, url)
                if count > 0:
                    flash(f"رویداد برای {count} سبد واجد شرایط ثبت شد.", "success")
                else:
                    flash("رویداد عمومی ثبت شد (هیچ سبدی سهم را در تاریخ مجمع نداشت).", "info")

        except Exception as e:
            print(f"Error processing event: {e}")
            flash("خطا در ثبت اطلاعات.", "error")
            
        return redirect(url_for('global_calendar'))


    events = get_all_market_events()
    return render_template('global_calendar.html', events=events, market_data=get_all_market_prices())

@app.route('/event/edit', methods=['POST'])
@login_required
def edit_event_route(): return redirect(url_for('global_calendar'))

@app.route('/event/delete/<int:event_id>')
@login_required
def remove_event(event_id): delete_event(event_id); flash("رویداد حذف شد.", "success"); return redirect(request.referrer)

@app.route('/event/process_dividend/<int:event_id>')
@login_required
def process_dividend(event_id):
    if process_dividend_payment(event_id): flash("سود واریز شد.", "success"); return redirect(request.referrer)
    return "خطا", 400

# ==========================================
# بخش مدیریت کاربران 
# ==========================================

@app.route('/users', methods=['GET', 'POST'])
@login_required
def manage_users():
    # بررسی دسترسی ادمین
    if current_user.username != 'admin':
        flash("شما به این بخش دسترسی ندارید.", "error")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()

    # --- افزودن کاربر جدید (POST) ---
    if request.method == 'POST':
        try:
            full_name = request.form['full_name']
            username = request.form['username']
            password = request.form['password']
            email = request.form.get('email')
            role = request.form['role']

            # FIX: جلوگیری از ساخت کاربر جدید با نقش "ادمین"
            if role == 'ادمین':
                flash('امکان تخصیص نقش "ادمین" به کاربر جدید وجود ندارد.', 'error')
                return redirect(url_for('manage_users'))

            # چک تکراری بودن نام کاربری
            exist = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if exist:
                flash("این نام کاربری قبلاً ثبت شده است.", "error")
            else:
                conn.execute('''
                    INSERT INTO users (username, password, full_name, email, role) 
                    VALUES (?, ?, ?, ?, ?)
                ''', (username, password, full_name, email, role))
                conn.commit()
                flash(f"کاربر {full_name} با موفقیت ایجاد شد.", "success")
        except Exception as e:
            flash(f"خطا در ثبت کاربر: {e}", "error")

    # --- نمایش لیست کاربران (GET) ---
    users = conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    conn.close()
    
    return render_template('manage_users.html', users=users)

@app.route('/users/edit', methods=['POST'])
@login_required
def edit_user():
    # بررسی دسترسی ادمین
    if current_user.role != 'ادمین':
        return "Access Denied", 403

    user_id = request.form['user_id']
    role = request.form['role']
    password = request.form.get('password')

    conn = get_db_connection()
    try:
        # FIX: جلوگیری از ویرایش کاربر ادمین اصلی
        target_user = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if target_user and target_user['username'] == 'admin':
            flash("امکان ویرایش مدیر کل سیستم وجود ندارد.", "error")
            return redirect(url_for('manage_users'))

        # اگر رمز عبور جدید وارد شده بود، آن را هم آپدیت کن
        if password and password.strip():
            conn.execute("UPDATE users SET role = ?, password = ? WHERE id = ?", (role, password, user_id))
            flash("نقش و رمز عبور کاربر بروزرسانی شد.", "success")
        else:
            # فقط نقش را آپدیت کن
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
            flash("نقش کاربر بروزرسانی شد.", "success")
            
        conn.commit()
    except Exception as e:
        flash("خطا در ویرایش اطلاعات.", "error")
        print(e)
    finally:
        conn.close()

    return redirect(url_for('manage_users'))


@app.route('/users/delete/<int:user_id>')
@login_required
def delete_user(user_id):
    # بررسی دسترسی ادمین
    if current_user.username != 'admin':
        return "Access Denied", 403
        
    conn = get_db_connection()
    user = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    
    # جلوگیری از حذف ادمین اصلی
    if user and user['username'] == 'admin':
        flash("حذف مدیر کل سیستم امکان‌پذیر نیست.", "error")
    else:
        # حذف کاربر و داده‌های مرتبط (در دیتابیس واقعی بهتر است سافت دیلیت باشد، اما اینجا حذف کامل می‌کنیم)
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        flash("کاربر با موفقیت حذف شد.", "success")
        
    conn.close()
    return redirect(url_for('manage_users'))

@app.route('/settings')
@login_required
def settings():
    if current_user.username != 'admin': return redirect(url_for('dashboard'))
    return render_template('settings.html')

@app.route('/backup/download')
@login_required
def download_backup():
    if current_user.username != 'admin': return "Access Denied", 403
    return send_file("portfolio_manager.db", as_attachment=True, download_name=f"backup.db")

@app.route('/backup/restore', methods=['POST'])
@login_required
def restore_backup():
    if current_user.username != 'admin': return "Access Denied", 403
    if 'file' in request.files: request.files['file'].save("portfolio_manager.db"); return render_template('settings.html', message="بازیابی شد.")
    return "Error", 400

@app.route('/system/reset', methods=['POST'])
@login_required
def reset_system():
    if current_user.username != 'admin': return "Access Denied", 403
    init_db(); from seed_data import seed_database; seed_database()
    return render_template('settings.html', message="راه‌اندازی مجدد انجام شد.")

@app.route('/transaction/quick_add', methods=['POST'])
@login_required
def quick_add_transaction():
    try:
        # دریافت و چاپ داده‌های فرم برای دیباگ
        print("\n>>> Transaction Form Data:")
        print(request.form)
        
        # این فیلد تعیین می‌کند کاربر در کدام تب بوده (trade یا cash)
        action_mode = request.form.get('action_mode')
        print(f">>> DETECTED MODE: {action_mode}")

        data = {
            'portfolio_id': request.form.get('portfolio_id'),
            'date': request.form.get('date')
        }

        if action_mode == 'cash':
            # --- منطق واریز / برداشت ---
            print(">>> Processing as CASH transaction...")
            tx_type = request.form.get('type_cash') # deposit / withdraw
            amount = clean_input_number(request.form.get('price_cash'))
            
            data.update({
                'type': tx_type,
                'symbol': 'CASH', # نماد ثابت برای پول نقد
                'quantity': 1,
                'price': amount, # مبلغ را در فیلد قیمت می‌گذاریم
                'asset_class': 'Cash'
            })
            
        else:
            # --- منطق خرید / فروش ---
            print(">>> Processing as TRADE transaction...")
            data.update({
                'type': request.form.get('type'), # buy / sell
                'symbol': request.form.get('symbol'),
                'quantity': clean_input_number(request.form.get('quantity')),
                'price': clean_input_number(request.form.get('price')),
                'asset_class': request.form.get('asset_class', 'Stock')
            })

        # ثبت در دیتابیس
        if add_new_transaction(data):
            flash("تراکنش با موفقیت ثبت شد.", "success")
        else:
            flash("خطا در ثبت تراکنش در دیتابیس.", "error")
            
    except Exception as e:
        print(f"Server Error: {e}")
        flash(f"خطا: {e}", "error")
        
    return redirect(url_for('dashboard'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        identifier = request.form['identifier']
        conn = get_db_connection()
        
        # جستجو در دیتابیس
        try:
            # اول چک میکنیم آیا با ایمیل وارد شده
            user = conn.execute("SELECT * FROM users WHERE email = ?", (identifier,)).fetchone()
            # اگر با ایمیل نبود، با نام کاربری چک میکنیم
            if not user:
                user = conn.execute("SELECT * FROM users WHERE username = ?", (identifier,)).fetchone()
        except:
            conn.close()
            flash("خطا در برقراری ارتباط با دیتابیس.", "error")
            return render_template('forgot_password.html')
            
        conn.close()

        if user and user['email']: # حتما باید ایمیل داشته باشد
            # ساخت لینک بازیابی
            reset_link = url_for('reset_password', token=f"reset-{user['id']}-token", _external=True)
            
            try:
                # ارسال ایمیل واقعی
                msg = Message("بازیابی رمز عبور سامانه کینکو", recipients=[user['email']])
                msg.body = f"""سلام {user['full_name']}،
                
برای بازیابی رمز عبور خود روی لینک زیر کلیک کنید:
{reset_link}

اگر شما این درخواست را نداده‌اید، این ایمیل را نادیده بگیرید.
                """
                mail.send(msg)
                flash(f"لینک بازیابی به ایمیل {user['email']} ارسال شد.", "success")
            except Exception as e:
                print(e)
                flash("خطا در ارسال ایمیل. لطفاً تنظیمات سرور را چک کنید.", "error")
        
        elif user and not user['email']:
            flash("برای این حساب کاربری ایمیلی ثبت نشده است.", "error")
        else:
            flash("کاربری با این مشخصات یافت نشد.", "error")
            
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # لاجیک ساده برای دمو: توکن شامل ID کاربر است
    try:
        user_id = token.split('-')[1]
    except:
        return "لینک نامعتبر است."

    if request.method == 'POST':
        new_pass = request.form['password']
        from database import get_db_connection
        conn = get_db_connection()
        conn.execute("UPDATE users SET password = ? WHERE id = ?", (new_pass, user_id))
        conn.commit()
        conn.close()
        flash("رمز عبور تغییر کرد. لطفاً وارد شوید.", "success")
        return redirect(url_for('login'))

    return render_template('reset_password.html')

# --- روت جدید: تغییر وضعیت اشتراک‌گذاری ---
@app.route('/analysis/toggle_share/<int:signal_id>')
@login_required
def toggle_analysis_share(signal_id):
    conn = get_db_connection()
    try:
        # 1. بررسی مالکیت
        signal = conn.execute("SELECT owner_id, is_public FROM analysis_signals WHERE id = ?", (signal_id,)).fetchone()
        
        if signal and signal['owner_id'] == current_user.id:
            # 2. تغییر وضعیت (اگر 0 است بشود 1 و برعکس)
            new_status = 0 if signal['is_public'] else 1
            conn.execute("UPDATE analysis_signals SET is_public = ? WHERE id = ?", (new_status, signal_id))
            conn.commit()
            
            msg = "تحلیل عمومی شد." if new_status else "تحلیل خصوصی شد."
            flash(msg, "success")
        else:
            flash("شما اجازه تغییر این تحلیل را ندارید.", "error")
            
    except Exception as e:
        print(f"Error toggling share: {e}")
        flash("خطا در تغییر وضعیت.", "error")
    finally:
        conn.close()

    return redirect(url_for('market_analysis'))

@app.route('/force_add')
@login_required
def force_add():
    conn = get_db_connection()
    try:
        uid = int(current_user.id)
        print(f">>> FORCING INSERT FOR USER {uid} <<<")
        
        conn.execute('''
            INSERT INTO analysis_signals 
            (symbol, target_buy_price, target_sell_price, stop_loss_price, 
             analysis_note, target_profile, asset_class, owner_id, is_public, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, CURRENT_DATE)
        ''', ('TEST_SIGNAL', 1000, 2000, 500, 'تست دستی', 'Medium', 'Stock', uid))
        
        conn.commit()
        return f"✅ سیگنال تستی با موفقیت برای کاربر {uid} ثبت شد. <a href='/analysis'>بازگشت به تحلیل</a>"
    except Exception as e:
        return f"❌ خطا در ثبت دستی: {e}"
    finally:
        conn.close()

@app.route('/transaction/delete_event/<int:event_id>', methods=['POST'])
@login_required
def delete_event_ajax(event_id):
    try:
        # استفاده از تابع موجود در analysis.py
        delete_event(event_id)
        return jsonify({'success': True, 'message': 'رویداد حذف شد'}), 200
    except Exception as e:
        print(f"Error deleting event: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/event/delete/bulk', methods=['POST'])
@login_required
def delete_bulk_events_route():
    try:
        data = request.json
        event_ids = data.get('ids', [])
        
        if not event_ids:
            return jsonify({'error': 'هیچ رویدادی انتخاب نشده است'}), 400
            
        conn = get_db_connection()
        # ایجاد کانکشن برای حذف گروهی
        # ترفند: تبدیل لیست [1, 2] به رشته "1, 2" برای SQL
        placeholders = ', '.join(['?'] * len(event_ids))
        query = f"DELETE FROM calendar_events WHERE id IN ({placeholders})"
        
        conn.execute(query, event_ids)
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'ids': event_ids}), 200
        
    except Exception as e:
        print(f"Bulk Delete Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get-index-by-date')
@login_required
def api_get_index_by_date():
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'error': 'Date required'}), 400
    
    from tsetmc_service import get_index_history_by_date
    val = get_index_history_by_date(date_str)
    
    if val:
        return jsonify({'success': True, 'index': val})
    else:
        return jsonify({'success': False, 'message': 'Not found'}), 404


if __name__ == '__main__':
    print("--- Server Running ---")
    app.run(debug=True, port=5000)
