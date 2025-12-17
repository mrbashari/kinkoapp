import requests
import sqlite3
import urllib3
import re
import time
import sys
import jdatetime
from datetime import datetime
from database import DB_NAME, set_market_index, get_db_connection

# غیرفعال کردن اخطار امنیتی SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# لیست آدرس‌های دیتای بورس
URLS = [
    "http://old.tsetmc.com/tsev2/data/MarketWatchPlus.aspx?h=0&r=0",
    "http://members.tsetmc.com/tsev2/data/MarketWatchPlus.aspx?h=0&r=0"
]

# هدرهای قوی برای شبیه‌سازی مرورگر واقعی
GLOBAL_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Connection': 'keep-alive',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
}

def log_debug(message):
    """چاپ پیام در لاگ‌های سرور (Standard Error)"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_msg = f"[TSETMC {timestamp}] {message}"
    print(log_msg, file=sys.stderr) # برای دیده شدن در لاگ‌های PythonAnywhere
    print(log_msg)

def fix_persian_chars(text):
    if not text: return ""
    text = str(text)
    return text.replace('ك', 'ک').replace('ي', 'ی').replace('ى', 'ی').strip()

def get_asset_details(symbol, name):
    """تشخیص نوع دارایی و بازار"""
    symbol = fix_persian_chars(symbol)
    name = fix_persian_chars(name)
    asset_type = 'Stock'
    market_type = 'TSE'
    
    if 'صندوق' in name or 'ETF' in name:
        market_type = 'ETF' # نرخ ثابت
        if any(x in name for x in ['طلا', 'زر', 'نابی', 'گنج', 'عیار', 'کهربا', 'آلتون', 'نفیس']):
            asset_type = 'ETF_Gold'
        elif any(x in name for x in ['درآمد ثابت', 'اعتماد', 'آفاق', 'تصمیم', 'کارا', 'افران', 'یاقوت']):
            asset_type = 'ETF_Fixed'
        else:
            asset_type = 'ETF_Equity'
            
    elif symbol.startswith('اخزا') or symbol.startswith('اراد') or symbol.startswith('گام'):
        asset_type = 'Bond'
        market_type = 'IFB'
    elif symbol.startswith('تسه') or symbol.startswith('تملی'):
        asset_type = 'Housing'
        market_type = 'IFB'
    
    return asset_type, market_type

def fetch_market_data():
    """دریافت قیمت‌ها و بروزرسانی دیتابیس"""
    log_debug("--- Starting Market Data Update ---")
    content = None
    
    for url in URLS:
        try:
            log_debug(f"Connecting to: {url}")
            response = requests.get(url, headers=GLOBAL_HEADERS, timeout=20, verify=False)
            
            if response.status_code == 200:
                content = response.text
                log_debug("Connection Successful.")
                break
            else:
                log_debug(f"Failed with status: {response.status_code}")
        except Exception as e:
            log_debug(f"Connection Error: {e}")
            continue

    if not content:
        log_debug("All URLs failed to return data.")
        return False, "خطای اتصال به سرور بورس"

    try:
        parts = content.split('@')
        if len(parts) < 3:
            return False, "فرمت دیتای دریافتی نامعتبر است."
            
        raw_data = parts[2]
        rows = raw_data.split(';')
        
        conn = get_db_connection()
        c = conn.cursor()
        
        updated_count = 0
        
        for row in rows:
            cols = row.split(',')
            if len(cols) > 22:
                try:
                    raw_symbol = cols[2]
                    raw_name = cols[3]
                    symbol = fix_persian_chars(raw_symbol)
                    name = fix_persian_chars(raw_name)
                    
                    close_price = float(cols[6])
                    last_trade = float(cols[7])
                    final_price = close_price if close_price > 0 else last_trade
                    
                    if final_price > 0:
                        asset_type, market_type = get_asset_details(symbol, name)
                        
                        # استفاده از REPLACE برای کدنویسی تمیزتر
                        c.execute('''
                            INSERT OR REPLACE INTO market_prices 
                            (symbol, company_name, sector, asset_type, market_type, last_price, close_price_yesterday, updated_at)
                            VALUES (?, ?, 'بازار بورس', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ''', (symbol, name, asset_type, market_type, final_price, final_price))
                        
                        updated_count += 1
                except:
                    continue

        conn.commit()
        conn.close()
        log_debug(f"Database updated: {updated_count} symbols.")
        
        # پس از قیمت‌ها، شاخص را هم آپدیت می‌کنیم
        get_market_index()
        
        return True, f"بروزرسانی موفق: {updated_count} نماد"

    except Exception as e:
        log_debug(f"Processing Error: {e}")
        return False, f"خطا در پردازش: {str(e)}"

def get_market_index():
    """دریافت شاخص کل (لحظه‌ای)"""
    log_debug(">>> Fetching Current Total Index...")
    index_val = None

    # روش 1: API
    try:
        url_api = "http://cdn.tsetmc.com/api/MarketData/GetMarketOverview/1"
        resp = requests.get(url_api, headers=GLOBAL_HEADERS, timeout=10, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            if 'marketOverview' in data and 'indexLastValue' in data['marketOverview']:
                index_val = float(data['marketOverview']['indexLastValue'])
                log_debug(f"API Success: {index_val}")
    except Exception as e:
        log_debug(f"API Failed: {e}")

    # روش 2: HTML Scraping
    if not index_val:
        try:
            url_html = "http://old.tsetmc.com/Loader.aspx?ParTree=15"
            resp = requests.get(url_html, headers=GLOBAL_HEADERS, timeout=15, verify=False)
            if resp.status_code == 200:
                match = re.search(r'شاخص کل.*?<div[^>]*>([\d,]+)</div>', resp.text, re.DOTALL)
                if match:
                    index_val = float(match.group(1).replace(',', ''))
                    log_debug(f"HTML Success: {index_val}")
        except Exception as e:
            log_debug(f"HTML Failed: {e}")

    # ذخیره در دیتابیس
    if index_val:
        try:
            set_market_index(index_val)
            log_debug("Index saved to DB.")
        except Exception as e:
            log_debug(f"DB Save Error: {e}")
    else:
        log_debug("!!! Could not fetch Index !!!")

    return index_val

def get_index_history_by_date(jalali_date_str):
    """
    دریافت شاخص کل تاریخی برای یک روز خاص
    ورودی: 1402/05/10
    """
    log_debug(f"Fetching History for: {jalali_date_str}")
    try:
        # تبدیل تاریخ
        j_date_str = jalali_date_str.replace('/', '-')
        jy, jm, jd = map(int, j_date_str.split('-'))
        g_date = jdatetime.date(jy, jm, jd).togregorian()
        target_int_date = int(g_date.strftime('%Y%m%d'))
        
        url = "http://cdn.tsetmc.com/api/MarketData/GetOverallIndexHistory/600"
        
        # هدر Referer برای عبور از برخی فایروال‌ها
        headers = GLOBAL_HEADERS.copy()
        headers['Referer'] = 'http://cdn.tsetmc.com'

        resp = requests.get(url, headers=headers, timeout=15, verify=False)
        
        if resp.status_code == 200:
            data = resp.json()
            if 'marketOverviewHistory' in data:
                history = data['marketOverviewHistory']
                
                # جستجوی دقیق
                for day in history:
                    if day['tarikh'] == target_int_date:
                        log_debug(f"History Found (Exact): {day['indexLastValue']}")
                        return day['indexLastValue']
                        
                # جستجوی روزهای قبل (اگر تعطیل بوده)
                for i in range(1, 7):
                    target_backup = target_int_date - i
                    for day in history:
                        if day['tarikh'] == target_backup:
                            log_debug(f"History Found (Backup -{i} days): {day['indexLastValue']}")
                            return day['indexLastValue']
                            
        log_debug(f"History API status: {resp.status_code}")
        
    except Exception as e:
        log_debug(f"History Fetch Error: {e}")
        
    return None

if __name__ == "__main__":
    # تست اجرا
    fetch_market_data()
