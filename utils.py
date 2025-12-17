import jdatetime

def to_persian_num(num):
    if num is None: return ""
    return str(num).replace('0', '۰').replace('1', '۱').replace('2', '۲').replace('3', '۳').replace('4', '۴').replace('5', '۵').replace('6', '۶').replace('7', '۷').replace('8', '۸').replace('9', '۹')

def clean_input_number(str_num):
    """تبدیل رشته عددی (با کاما و فارسی) به عدد صحیح"""
    if not str_num: return 0
    # حذف کاما
    s = str(str_num).replace(',', '')
    # تبدیل فارسی به انگلیسی
    eng = s.replace('۰','0').replace('۱','1').replace('۲','2').replace('۳','3').replace('۴','4').replace('۵','5').replace('۶','6').replace('۷','7').replace('۸','8').replace('۹','9')
    try:
        return float(eng)
    except:
        return 0

def format_currency(value):
    """فرمت پول: جداکننده هزارگان + بدون اعشار"""
    if value is None: return "۰"
    try:
        val = float(value)
        # {:,.0f} یعنی: جداکننده کاما (,) و صفر رقم اعشار (.0f)
        return "{:,.0f}".format(val)
    except:
        return str(value)

def format_large_number(value):
    """
    جایگزین شده: قبلاً M/B نشان میداد، الان همان فرمت کامل پول را نشان میدهد
    """
    return format_currency(value)

def to_jalali(date_str):
    if not date_str: return ''
    try:
        y, m, d = map(int, str(date_str).split('-'))
        jdate = jdatetime.date.fromgregorian(day=d, month=m, year=y)
        return jdate.strftime('%Y/%m/%d')
    except:
        return date_str