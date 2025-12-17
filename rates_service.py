import requests
import re
import time
import random

def get_latest_rates():
    """
    دریافت قیمت دلار و انس از TGJU با شبیه‌سازی دقیق مرورگر
    """
    rates = {
        'dollar': None,      # دلار بازار آزاد
        'gold_ounce': None   # انس جهانی طلا
    }
    
    # استفاده از لیست User-Agent های مختلف برای جلوگیری از بلاک شدن
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0'
    ]
    
    headers = {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    try:
        # اضافه کردن پارامتر تصادفی برای جلوگیری از کش شدن سمت سرور/کلاینت
        url = f"https://www.tgju.org/?_={int(time.time())}"
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            html = response.text
            
            # 1. استخراج قیمت دلار (price_dollar_rl)
            # الگوی جستجو: دنبال تری که data-market-row="price_dollar_rl" دارد می‌گردیم
            # سپس اولین تگ <td class="nf"> که حاوی قیمت است را برمی‌داریم
            dollar_match = re.search(r'data-market-row="price_dollar_rl".*?<td class="nf">([^<]+)</td>', html, re.DOTALL)
            if dollar_match:
                # حذف کاما و فاصله‌های اضافی
                rates['dollar'] = dollar_match.group(1).replace(',', '').strip()

            # 2. استخراج انس طلا (ons)
            # انس جهانی معمولا اعشار دارد، پس الگوی ما باید نقطه را هم قبول کند
            ons_match = re.search(r'data-market-row="ons".*?<td class="nf">([^<]+)</td>', html, re.DOTALL)
            if ons_match:
                rates['gold_ounce'] = ons_match.group(1).replace(',', '').strip()
                
            print(f"Rates Fetched Successfully: {rates}")

    except Exception as e:
        print(f"Error fetching rates: {e}")
        # در صورت خطا، نال برمی‌گرداند تا در فرانت '---' نشان داده شود
        
    return rates

if __name__ == "__main__":
    # تست تابع هنگام اجرای مستقیم
    print(get_latest_rates())