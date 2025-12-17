/* =========================================
   Kinko PMS Global Logic (v3.1 - Fixed Autocomplete)
   ========================================= */

// --- Utils ---
function toPersianNum(num) { return String(num).replace(/\d/g, d => "۰۱۲۳۴۵۶۷۸۹"[d]); }
function cleanNumber(str) { if (!str) return 0; let eng = str.toString().replace(/[۰-۹]/g, d => "۰۱۲۳۴۵۶۷۸۹".indexOf(d)).replace(/[^0-9\.-]/g, ''); return parseFloat(eng) || 0; }
function formatLargeNumber(val) { return toPersianNum(parseInt(val).toLocaleString('en-US')); }
function normalizePersian(str) { if (!str) return ""; return str.toString().replace(/ي/g, "ی").replace(/ك/g, "ک"); }

document.addEventListener('input', function (e) {
    if (e.target.classList.contains('money-input')) {
        let val = e.target.value.replace(/[۰-۹]/g, d => "۰۱۲۳۴۵۶۷۸۹".indexOf(d)).replace(/[^0-9]/g, '');
        if (val === "") { e.target.value = ""; return; }
        e.target.value = parseInt(val).toLocaleString('en-US');
    }
});

// --- 1. Central Dropdown Logic ---
function toggleSelect(btn) {
    event.stopPropagation();
    const container = btn.closest('.custom-select-container');
    const options = container.querySelector('.select-options');
    document.querySelectorAll('.select-options.active').forEach(el => { if (el !== options) el.classList.remove('active'); });
    options.classList.toggle('active');
}

function selectOption(item, inputId, value) {
    event.stopPropagation();
    const container = item.closest('.custom-select-container');
    const input = document.getElementById(inputId);
    const display = container.querySelector('.selected-text');
    
    input.value = value;
    display.innerHTML = item.innerHTML; 
    
    container.querySelectorAll('.select-option').forEach(el => el.classList.remove('selected'));
    item.classList.add('selected');
    container.querySelector('.select-options').classList.remove('active');
}


// --- 2. Central Datepicker Logic ---
const monthNames = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];
function toggleDatepicker(id) {
    event.stopPropagation();
    const picker = document.getElementById(id);
    document.querySelectorAll('[id^="datepicker-"]').forEach(el => { if(el.id !== id) el.classList.add('hidden'); });
    picker.classList.toggle('hidden');
}
function renderCalendar(containerId, year, month, dispId, inpId, pickerId, labelId) {
    const container = document.getElementById(containerId);
    if(!container) return;
    container.innerHTML = '';
    if(labelId) { const labelEl = document.getElementById(labelId); if(labelEl) labelEl.innerText = toPersianNum(`${monthNames[month-1]} ${year}`); }
    const daysInMonth = jalaali.jalaaliMonthLength(year, month);
    const gDate = jalaali.toGregorian(year, month, 1);
    const dayOfWeek = new Date(gDate.gy, gDate.gm - 1, gDate.gd).getDay();
    const padding = {6:0, 0:1, 1:2, 2:3, 3:4, 4:5, 5:6}[dayOfWeek];
    for(let i=0; i<padding; i++) container.appendChild(document.createElement('div'));
    const today = new Date(); const jToday = jalaali.toJalaali(today);
    for(let i=1; i<=daysInMonth; i++) {
        const btn = document.createElement('button'); btn.type='button'; btn.innerText=toPersianNum(i);
        btn.className = "w-8 h-8 rounded-lg text-xs hover:bg-gray-100 transition flex items-center justify-center text-gray-700 font-medium";
        if(year===jToday.jy && month===jToday.jm && i===jToday.jd) btn.className += " border border-[#5E2BFF] text-[#5E2BFF] font-bold";
        btn.onclick = (e) => {
            e.stopPropagation();
            const dStr = `${year}/${String(month).padStart(2,'0')}/${String(i).padStart(2,'0')}`;
            document.getElementById(dispId).value = toPersianNum(dStr);
            const g = jalaali.toGregorian(year, month, i);
            const gString = `${g.gy}-${String(g.gm).padStart(2,'0')}-${String(g.gd).padStart(2,'0')}`;
            document.getElementById(inpId).value = gString;
            document.getElementById(pickerId).classList.add('hidden');
            if (typeof onDateSelected === 'function') { onDateSelected(containerId, gString); }
        };
        container.appendChild(btn);
    }
}

// --- 3. Global Click Handler ---
document.addEventListener('click', function(e) {
    if (!e.target.closest('.custom-select-container')) { document.querySelectorAll('.select-options.active').forEach(el => el.classList.remove('active')); }
    if (!e.target.closest('[id^="datepicker-"]') && !e.target.matches('input[onclick^="toggleDatepicker"]')) { document.querySelectorAll('[id^="datepicker-"]').forEach(el => el.classList.add('hidden')); }
    if (!e.target.closest('.autocomplete-wrapper')) { document.querySelectorAll('.autocomplete-dropdown').forEach(el => el.classList.remove('active')); }
});

// --- 4. Financial Core ---
const FinancialCore = {
    RATES: { 'TSE': { 'Stock': { buy: 0.003712, sell: 0.0088 }, 'Rights': { buy: 0.003712, sell: 0.0088 } }, 'IFB': { 'Stock': { buy: 0.003632, sell: 0.00891 }, 'Rights': { buy: 0.003632, sell: 0.00891 }, 'Bonds': { buy: 0.000725, sell: 0.000725 } }, 'ETF': { 'Equity': { buy: 0.00116, sell: 0.0011875 }, 'Fixed': { buy: 0.0001875, sell: 0.0001875 }, 'Gold': { buy: 0.0011, sell: 0.0011 } } },
    calculate: function(price, qty, type, assetClass, marketType = 'TSE') {
        const totalValue = price * qty; let rate = 0;
        if (assetClass === 'Gold') rate = this.RATES.ETF.Gold[type]; else if (assetClass === 'Fixed') rate = this.RATES.ETF.Fixed[type]; else if (assetClass === 'ETF_Equity') rate = this.RATES.ETF.Equity[type]; else { const mkt = (marketType === 'IFB') ? 'IFB' : 'TSE'; rate = this.RATES[mkt].Stock[type]; }
        const commission = Math.floor(totalValue * rate);
        let finalAmount = (type === 'buy') ? totalValue + commission : totalValue - commission;
        return { baseValue: totalValue, commission: commission, finalAmount: finalAmount, rateUsed: rate };
    }
};

/* =========================================
   5. Autocomplete System (Revised)
   ========================================= */
function calculateSearchScore(item, query) {
    // اصلاح شده: اگر نماد نداشت، خالی در نظر بگیر (جلوگیری از خطا)
    const sym = item.symbol ? normalizePersian(item.symbol).toLowerCase().replace(/\s/g, '') : '';
    const name = item.name ? normalizePersian(item.name).toLowerCase() : '';
    const q = query.toLowerCase().replace(/\s/g, '');
    
    // منطق امتیازدهی
    if (sym === q) return 100;
    if (name === q) return 90;
    if (sym.startsWith(q)) return 80;
    if (name.startsWith(q)) return 70;
    if (sym.includes(q)) return 50;
    if (name.includes(q)) return 30;
    
    // جستجو در نام مدیر (برای پرتفوی‌ها)
    if (item.manager && normalizePersian(item.manager).toLowerCase().includes(q)) return 20;
    
    return 0;
}

function initGlobalAutocomplete(inputId, dataList, onSelect) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const wrapper = input.closest('.autocomplete-wrapper');
    if (!wrapper) return; 
    let dropdown = wrapper.querySelector('.autocomplete-dropdown');
    if (!dropdown) {
        dropdown = document.createElement('div');
        dropdown.className = 'autocomplete-dropdown custom-scrollbar';
        wrapper.appendChild(dropdown);
    }
    input.addEventListener('input', function() {
        const query = normalizePersian(this.value).trim();
        dropdown.innerHTML = '';
        if (query.length < 1) { dropdown.classList.remove('active'); return; }
        
        const results = dataList
            .map(item => ({ item, score: calculateSearchScore(item, query) }))
            .filter(res => res.score > 0)
            .sort((a, b) => b.score - a.score)
            .slice(0, 7);
            
        if (results.length > 0) {
            dropdown.classList.add('active');
            results.forEach(({ item }) => {
                const div = document.createElement('div'); div.className = 'ac-item';
                
                // >>> اصلاح اصلی اینجاست: تشخیص نوع دیتا <<<
                let mainText = '';
                let subText = '';
                
                if (item.symbol) {
                    // حالت سهام (نماد + نام شرکت)
                    mainText = item.symbol;
                    subText = item.name;
                } else {
                    // حالت پرتفوی (نام سبد + نام مدیر)
                    mainText = item.name;
                    subText = item.manager ? `مدیر: ${item.manager}` : '';
                }
                
                div.innerHTML = `<span class="ac-symbol">${mainText}</span><span class="ac-name">${subText}</span>`;
                
                div.onclick = (e) => { 
                    e.stopPropagation(); 
                    // مقدار اینپوت را برابر با متن اصلی (نماد یا نام سبد) قرار بده
                    input.value = mainText; 
                    dropdown.classList.remove('active'); 
                    if (typeof onSelect === 'function') onSelect(item); 
                };
                dropdown.appendChild(div);
            });
        } else { dropdown.classList.remove('active'); }
    });
}
