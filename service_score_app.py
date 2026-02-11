import streamlit as st
import psycopg2
import json
from datetime import datetime
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials


# ---------------------- КОНФИГУРАЦИЯ ---------------------- #
SPREADSHEET_ID = "1048LAnXOi822I87iLgommj-181thuzktnvdhQmzUfho"
SHEET_NAME = "Клиенты"

# PostgreSQL connection
def get_db_connection():
    if "postgres" in st.secrets:
        return psycopg2.connect(
            host=st.secrets["postgres"]["host"],
            database=st.secrets["postgres"]["database"],
            user=st.secrets["postgres"]["user"],
            password=st.secrets["postgres"]["password"],
            port=st.secrets["postgres"]["port"]
        )
    else:
        # Локальная разработка
        return psycopg2.connect(
            host="localhost",
            database="service_score_journal",
            user="postgres",
            password="postgres"
        )

def get_current_month_report(company_name):
    """Получить отчёт текущего месяца для компании"""
    from datetime import datetime
    current_month = datetime.now().strftime("%Y-%m")
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, facts_json, total_score, max_score, month_percent, visit_dates, planned_visits
        FROM reports 
        WHERE company_name = %s AND month_year = %s
        ORDER BY created_at DESC LIMIT 1
    """, (company_name, current_month))
    
    result = cur.fetchone()
    cur.close()
    conn.close()
    
    if result:
        visit_dates = result[5] if result[5] else []
        planned_visits = result[6] if result[6] else 4
        return {
            'id': result[0],
            'facts': json.loads(result[1]),
            'total_score': result[2],
            'max_score': result[3],
            'month_percent': result[4],
            'visit_dates': visit_dates,
            'planned_visits': planned_visits
        }
    return None

def save_visit_report(company_name, stations_checked, K, N):
    """Сохранить новый выезд и обновить месячный отчёт"""
    from datetime import datetime
    current_month = datetime.now().strftime("%Y-%m")
    current_datetime = datetime.now().isoformat()
    
    # Получаем текущий отчёт месяца
    current = get_current_month_report(company_name)
    
    if current:
        # Добавляем к существующему
        facts = current['facts'] + [stations_checked]
        visit_dates = current.get('visit_dates', []) + [current_datetime]
    else:
        # Первый выезд месяца
        facts = [stations_checked]
        visit_dates = [current_datetime]
    
    # Пересчитываем баллы
    results, total_score, month_percent = calc_flexible_score_dynamic(N, K, facts)
    max_score = len(facts) * 2
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    if current:
        # Обновляем существующий отчёт (K не меняем!)
        cur.execute("""
            UPDATE reports 
            SET facts_json = %s, total_score = %s, max_score = %s, 
                month_percent = %s, visit_dates = %s, created_at = NOW()
            WHERE id = %s
        """, (json.dumps(facts, ensure_ascii=False), total_score, max_score, month_percent, json.dumps(visit_dates), current['id']))
    else:
        # Создаём новый отчёт месяца (сохраняем K!)
        cur.execute("""
            INSERT INTO reports (company_name, month_year, facts_json, total_score, max_score, month_percent, visit_dates, planned_visits)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (company_name, current_month, json.dumps(facts, ensure_ascii=False), total_score, max_score, month_percent, json.dumps(visit_dates), K))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return results, total_score, max_score, month_percent, len(facts)

def update_visit_in_report(company_name, visit_index, new_value, K, N):
    """Обновить конкретный выезд в отчёте"""
    from datetime import datetime
    current_month = datetime.now().strftime("%Y-%m")
    
    current = get_current_month_report(company_name)
    if not current:
        return None
    
    facts = current['facts']
    
    # Обновляем нужный выезд
    if 0 <= visit_index < len(facts):
        facts[visit_index] = new_value
    else:
        return None
    
    # Пересчитываем баллы
    results, total_score, month_percent = calc_flexible_score_dynamic(N, K, facts)
    max_score = len(facts) * 2
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE reports 
        SET facts_json = %s, total_score = %s, max_score = %s, 
            month_percent = %s, created_at = NOW()
        WHERE id = %s
    """, (json.dumps(facts, ensure_ascii=False), total_score, max_score, month_percent, current['id']))
    
    conn.commit()
    cur.close()
    conn.close()
    
    return results, total_score, max_score, month_percent

# ---------------------- GOOGLE SHEETS ---------------------- #

@st.cache_data(ttl=300)
def load_companies_from_gsheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    data = sheet.get_all_values()
    headers = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=headers)
    df = df[["Организация", "Количество раб.мест без серверов и доп.сервисов (обслуживаемых)"]]
    df = df.rename(columns={
        "Организация": "name",
        "Количество раб.мест без серверов и доп.сервисов (обслуживаемых)": "stations"
    })
    df = df[df["name"].str.strip() != ""]
    df["stations"] = pd.to_numeric(df["stations"], errors="coerce").fillna(0).astype(int)
    return df[["name", "stations"]]


# ---------------------- БД (PostgreSQL) ---------------------- #

def save_report(company_name, facts, total_score, max_score, month_percent):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO reports (company_name, facts_json, total_score, max_score, month_percent)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (company_name, json.dumps(facts, ensure_ascii=False), total_score, max_score, month_percent)
    )
    conn.commit()
    cur.close()
    conn.close()


def get_reports(company_name=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if company_name:
            cur.execute("""
                SELECT id, created_at, company_name, facts_json, total_score, max_score, month_percent, visit_dates, planned_visits
                FROM reports WHERE company_name = %s ORDER BY created_at DESC
            """, (company_name,))
        else:
            cur.execute("""
                SELECT id, created_at, company_name, facts_json, total_score, max_score, month_percent, visit_dates, planned_visits
                FROM reports ORDER BY created_at DESC
            """)

        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        df = pd.DataFrame(rows, columns=["id", "created_at", "company_name", "facts_json", "total_score", "max_score", "month_percent", "visit_dates", "planned_visits"])
        return df
    except:
        return pd.DataFrame()


def delete_report(report_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM reports WHERE id = %s", (report_id,))
    conn.commit()
    cur.close()
    conn.close()


# ------------------ РАСЧЁТ БАЛЛОВ ------------------ #

def calc_flexible_score_dynamic(N, K, facts):
    if N == 0 or K == 0 or len(facts) == 0:
        return [], 0, 0

    results = []
    remaining_stations = N
    remaining_visits = K
    total_done = 0
    total_score = 0

    for i in range(len(facts)):
        F_i = facts[i]
        P_i = remaining_stations / remaining_visits if remaining_visits > 0 else 0
        percent_visit = (F_i / P_i * 100) if P_i > 0 else 0

        expected_progress = (i + 1) / K * 100
        actual_progress = (total_done + F_i) / N * 100

        if actual_progress >= expected_progress:
            score = 2
            status = "90+% хорошо (общий OK)"
        else:
            if percent_visit < 50:
                score = 0
                status = "<50% плохо"
            elif percent_visit < 90:
                score = 1
                status = "50-90% нормально"
            else:
                score = 2
                status = "90+% хорошо"

        results.append({
            "Выезд": i + 1,
            "P": round(P_i, 1),
            "F": F_i,
            "%выезд": f"{round(percent_visit, 1)}%",
            "Баллы": score,
            "Ожид.%": f"{round(expected_progress, 1)}%",
            "Факт.%": f"{round(actual_progress, 1)}%",
            "Статус": status,
        })

        remaining_stations -= F_i
        remaining_visits -= 1
        total_done += F_i
        total_score += score

    month_percent = round(total_done / N * 100, 1)
    return results, total_score, month_percent


# ---------------------- UI ---------------------- #

st.set_page_config(page_title="Баллы инженеров", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    * {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    
    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        color: #f1f5f9;
    }
    
    /* Заголовки */
    h1 {
        color: #ffffff !important;
        font-weight: 700 !important;
        font-size: 2.5rem !important;
        letter-spacing: -0.02em;
        margin-bottom: 2rem !important;
        background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    h2, h3 {
        color: #f1f5f9 !important;
        font-weight: 600 !important;
    }
    
    /* Текст */
    p, span, div, li {
        color: #e2e8f0 !important;
    }
    
    /* Лейблы */
    .stSelectbox label, .stNumberInput label {
        color: #cbd5e1 !important;
        font-weight: 600 !important;
        font-size: 0.875rem !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    /* Поля ввода и селекты */
    .stNumberInput > div > div > input {
        background: rgba(30, 41, 59, 0.95) !important;
        color: #f1f5f9 !important;
        border: 1.5px solid rgba(100, 116, 139, 0.5) !important;
        border-radius: 10px !important;
        font-size: 1rem !important;
        font-weight: 500 !important;
        padding: 0.75rem 1rem !important;
    }
    
    .stNumberInput > div > div > input:focus {
        border-color: #60a5fa !important;
        box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.15) !important;
    }
    
    /* Selectbox - основной контейнер */
    .stSelectbox > div > div {
        background: rgba(30, 41, 59, 0.95) !important;
        border: 1.5px solid rgba(100, 116, 139, 0.5) !important;
        border-radius: 10px !important;
    }
    
    /* Selectbox - текст выбранного значения */
    .stSelectbox [data-baseweb="select"] > div {
        background: transparent !important;
        color: #f1f5f9 !important;
        font-weight: 500 !important;
    }
    
    /* Selectbox - иконка стрелки */
    .stSelectbox svg {
        fill: #94a3b8 !important;
    }
    
    /* Selectbox - выпадающее меню (popover) */
    [data-baseweb="popover"] {
        background: #1e293b !important;
        border: 1px solid #334155 !important;
        border-radius: 10px !important;
        box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5) !important;
    }
    
    /* Selectbox - список опций */
    [data-baseweb="menu"] {
        background: #1e293b !important;
    }
    
    /* Selectbox - каждая опция */
    [role="option"],
    [data-baseweb="menu"] li {
        background: transparent !important;
        color: #e2e8f0 !important;
        padding: 0.75rem 1rem !important;
        transition: all 0.2s ease !important;
        font-weight: 500 !important;
    }
    
    /* Selectbox - hover на опции */
    [role="option"]:hover,
    [data-baseweb="menu"] li:hover {
        background: rgba(59, 130, 246, 0.25) !important;
        color: #ffffff !important;
    }
    
    /* Selectbox - выбранная опция */
    [aria-selected="true"],
    [data-baseweb="menu"] li[aria-selected="true"] {
        background: rgba(59, 130, 246, 0.35) !important;
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    
    /* Selectbox - input внутри */
    [data-baseweb="select"] input {
        color: #f1f5f9 !important;
    }
    
    /* Expander карточки */
    .streamlit-expanderHeader {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.95) 0%, rgba(51, 65, 85, 0.95) 100%) !important;
        border: 1px solid rgba(100, 116, 139, 0.4) !important;
        border-left: 3px solid #60a5fa !important;
        border-radius: 12px !important;
        color: #f1f5f9 !important;
        font-weight: 600 !important;
        padding: 1.25rem !important;
        transition: all 0.3s ease;
    }
    
     /* Содержимое expander */
    .streamlit-expanderContent {
        background: rgba(17, 24, 39, 0.5) !important;
        border: 1px solid rgba(100, 116, 139, 0.3) !important;
        border-top: none !important;
        border-radius: 0 0 12px 12px !important;
        padding: 1.5rem !important;
    }
    
    /* Убираем белые фоны при hover */
    .streamlit-expander:hover,
    .streamlit-expanderHeader:hover,
    details:hover {
        background: transparent !important;
    }
    
    details[open] > summary {
        background: linear-gradient(135deg, rgba(51, 65, 85, 0.95) 0%, rgba(71, 85, 105, 0.95) 100%) !important;
    }
    
    /* Кнопки Primary */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%) !important;
        color: #ffffff !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        padding: 0.75rem 2rem !important;
        box-shadow: 0 4px 20px rgba(59, 130, 246, 0.4);
        transition: all 0.3s ease;
    }
    
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%) !important;
        box-shadow: 0 8px 30px rgba(59, 130, 246, 0.6) !important;
        transform: translateY(-2px);
    }
    
    /* Кнопки обычные */
    .stButton > button {
        background: rgba(51, 65, 85, 0.9) !important;
        color: #f1f5f9 !important;
        border: 1px solid rgba(100, 116, 139, 0.5) !important;
        border-radius: 10px !important;
        font-weight: 500 !important;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        background: rgba(71, 85, 105, 1) !important;
        border-color: #60a5fa !important;
    }
    
    /* Таблицы */
    .stDataFrame {
        border: 1px solid rgba(100, 116, 139, 0.3);
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
    }
    
    .stDataFrame thead tr th {
        background: rgba(30, 41, 59, 0.95) !important;
        color: #60a5fa !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    /* Метрики */
    [data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-weight: 700 !important;
        font-size: 2.25rem !important;
    }
    
    [data-testid="stMetricLabel"] {
        color: #cbd5e1 !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    [data-testid="stMetric"] {
        background: rgba(30, 41, 59, 0.6);
        padding: 1.5rem;
        border-radius: 12px;
        border: 1px solid rgba(100, 116, 139, 0.3);
    }
    
    /* Info, Success, Error */
    .stInfo {
        background: rgba(59, 130, 246, 0.1) !important;
        border: 1px solid rgba(96, 165, 250, 0.4) !important;
        border-left: 4px solid #60a5fa !important;
        border-radius: 10px !important;
        color: #f1f5f9 !important;
    }
    
    .stSuccess {
        background: rgba(34, 197, 94, 0.1) !important;
        border: 1px solid rgba(34, 197, 94, 0.4) !important;
        border-left: 4px solid #22c55e !important;
        border-radius: 10px !important;
        color: #f1f5f9 !important;
    }
    
    .stError {
        background: rgba(239, 68, 68, 0.1) !important;
        border: 1px solid rgba(239, 68, 68, 0.4) !important;
        border-left: 4px solid #ef4444 !important;
        border-radius: 10px !important;
        color: #f1f5f9 !important;
    }
    
    /* Табы */
    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
        border-bottom: 1px solid rgba(100, 116, 139, 0.3);
    }
    
    .stTabs [data-baseweb="tab"] {
        border: none;
        border-bottom: 3px solid transparent;
        color: #94a3b8;
        font-weight: 500;
        padding: 1rem 1.5rem;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        color: #e2e8f0;
    }
    
    .stTabs [aria-selected="true"] {
        border-bottom: 3px solid #60a5fa;
        color: #ffffff;
        font-weight: 600;
    }
    
    /* Strong */
    strong {
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    
    /* Caption */
    .stCaption {
        color: #64748b !important;
        text-align: center;
    }
            
    /* УСИЛЕННАЯ ФИКСАЦИЯ SELECTBOX */
    div[data-baseweb="popover"] > div,
    div[data-baseweb="popover"] ul,
    [data-baseweb="menu"],
    ul[role="listbox"] {
        background-color: #1e293b !important;
        background: #1e293b !important;
    }
    
    div[data-baseweb="popover"] li,
    [data-baseweb="menu"] > ul > li,
    ul[role="listbox"] > li,
    li[role="option"] {
        background-color: transparent !important;
        background: transparent !important;
        color: #e2e8f0 !important;
        font-weight: 500 !important;
    }
    
    div[data-baseweb="popover"] li:hover,
    [data-baseweb="menu"] > ul > li:hover,
    ul[role="listbox"] > li:hover,
    li[role="option"]:hover {
        background-color: rgba(59, 130, 246, 0.25) !important;
        background: rgba(59, 130, 246, 0.25) !important;
        color: #ffffff !important;
    }
    
    div[data-baseweb="popover"] li[aria-selected="true"],
    [data-baseweb="menu"] > ul > li[aria-selected="true"],
    ul[role="listbox"] > li[aria-selected="true"] {
        background-color: rgba(59, 130, 246, 0.35) !important;
        background: rgba(59, 130, 246, 0.35) !important;
        color: #ffffff !important;
        font-weight: 600 !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("🏭 Расчёт баллов и журнал отчётов")

tab_calc, tab_journal = st.tabs(["➕ Новый отчёт", "📋 Журнал отчётов"])

with tab_calc:
    st.subheader("Добавить выезд")

    try:
        companies_df = load_companies_from_gsheet()
    except Exception as e:
        st.error(f"❌ Ошибка загрузки: {e}")
        companies_df = pd.DataFrame()

    if companies_df.empty:
        st.info("Нет данных из Google Sheets.")
    else:
        company_names = companies_df["name"].tolist()
        selected_name = st.selectbox("Компания", company_names)
        company_row = companies_df[companies_df["name"] == selected_name].iloc[0]
        N = int(company_row["stations"])
        
        st.write(f"📍 Станций по договору: **{N}**")
        K = st.number_input("Выездов в месяц (K)", min_value=1, value=4)

        # Показываем текущий прогресс
        current_report = get_current_month_report(selected_name)
        
        if current_report:
            facts = current_report['facts']
            visit_num = len(facts) + 1
            total_checked = sum(facts)
            
            st.info(f"""
            **Текущий месяц:**
            - Выездов уже сделано: **{len(facts)} из {K}**
            - Станций проверено: **{total_checked} из {N}** ({current_report['month_percent']}%)
            - Баллы: **{current_report['total_score']} из {current_report['max_score']}**
            """)
            
            st.write(f"🚀 Сейчас: **Выезд #{visit_num}**")
        else:
            visit_num = 1
            st.write(f"🚀 Это будет **первый выезд** в этом месяце")

        stations_checked = st.number_input(
            f"Сколько станций проверено на выезде #{visit_num}?", 
            min_value=0, 
            value=0, 
            key="stations_input"
        )

        if st.button("✅ Сохранить выезд", type="primary"):
            if stations_checked > 0:
                results, total_score, max_score, month_percent, total_visits = save_visit_report(
                    selected_name, stations_checked, K, N
                )

                st.success(f"✅ Выезд #{visit_num} сохранён!")
                
                st.markdown("### 📊 Детальный расчёт")
                st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

                c1, c2, c3 = st.columns(3)
                c1.metric("Итого баллов", f"{total_score} из {max_score}")
                c2.metric("Выполнено", f"{month_percent}%")
                c3.metric("Выездов", f"{total_visits} из {K}")
            else:
                st.error("Укажите количество проверенных станций!")

with tab_journal:
    st.subheader("📋 Журнал всех отчётов")

    try:
        companies_df = load_companies_from_gsheet()
        names = ["Все компании"] + companies_df["name"].tolist()
        filter_company = st.selectbox("Фильтр", names, key="journal_filter")
        filter_company = None if filter_company == "Все компании" else filter_company
    except:
        filter_company = None

    reports_df = get_reports(filter_company)
    
    if reports_df.empty:
        st.info("Отчётов пока нет.")
    else:
        # Группируем по компаниям
        for idx, row in reports_df.iterrows():
            company = row['company_name']
            facts = json.loads(row['facts_json'])
            report_id = row['id']
            
            # Получаем данные компании для расчёта
            try:
                company_row = companies_df[companies_df["name"] == company].iloc[0]
                N = int(company_row["stations"])
            except:
                N = 0
            
            # Раскрывающийся блок для каждой компании
            with st.expander(f"🏢 **{company}** — {row['month_percent']}% выполнено | Баллы: {row['total_score']}/{row['max_score']} | Создан: {row['created_at']}", expanded=False):
                
                st.markdown(f"**Всего выездов:** {len(facts)}")
                st.markdown(f"**Станций по договору:** {N}")
                
                # Получаем сохранённый K (плановое количество выездов)
                K = row.get('planned_visits', 4)  # По умолчанию 4
                if K is None or K == 0:
                    K = 4
                
                # Пересчитываем детальный расчёт с правильным K
                results, _, _ = calc_flexible_score_dynamic(N, K, facts)
                
                # Показываем детальный расчёт
                st.markdown("### 📊 Детальный расчёт:")
                st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
                
                st.markdown("---")

                # Таблица с выездами
                st.markdown("### 📊 Детали по выездам:")
                
                # Получаем даты выездов
                visit_dates_raw = row.get('visit_dates')
                if visit_dates_raw:
                    # PostgreSQL JSONB возвращает уже распарсенный объект
                    if isinstance(visit_dates_raw, str):
                        try:
                            visit_dates = json.loads(visit_dates_raw)
                        except:
                            visit_dates = []
                    elif isinstance(visit_dates_raw, list):
                        visit_dates = visit_dates_raw
                    else:
                        visit_dates = []
                else:
                    visit_dates = []
                
                # Редактируемые поля для каждого выезда
                edited_facts = []
                
                cols = st.columns([1, 2, 3, 1])
                cols[0].write("**№**")
                cols[1].write("**Проверено станций**")
                cols[2].write("**Дата добавления**")
                cols[3].write("**Действия**")
                
                for i, fact in enumerate(facts):
                    cols = st.columns([1, 2, 3, 1])
                    cols[0].write(f"Выезд {i+1}")
                    new_value = cols[1].number_input(
                        f"v{i}", 
                        min_value=0, 
                        value=fact, 
                        key=f"edit_{report_id}_{i}",
                        label_visibility="collapsed"
                    )
                    edited_facts.append(new_value)
                    
                    # Показываем дату
                    if i < len(visit_dates):
                        from datetime import datetime
                        try:
                            dt = datetime.fromisoformat(visit_dates[i])
                            date_str = dt.strftime("%d.%m.%Y %H:%M")
                        except:
                            date_str = "Не указана"
                    else:
                        date_str = "Не указана"
                    
                    cols[2].write(date_str)
                    
                    # Кнопка удаления выезда
                    if cols[3].button("🗑️", key=f"del_visit_{report_id}_{i}", help="Удалить выезд"):
                        # Удаляем выезд из массивов
                        facts.pop(i)
                        if i < len(visit_dates):
                            visit_dates.pop(i)
                        
                        if len(facts) == 0:
                            # Если это последний выезд — удаляем весь отчёт
                            delete_report(report_id)
                            st.success("Отчёт полностью удалён")
                            st.rerun()
                        else:
                            # Пересчитываем баллы
                            results_new, total_score_new, month_percent_new = calc_flexible_score_dynamic(N, K, facts)
                            max_score_new = len(facts) * 2
                            
                            conn = get_db_connection()
                            cur = conn.cursor()
                            cur.execute("""
                                UPDATE reports 
                                SET facts_json = %s, total_score = %s, max_score = %s, 
                                    month_percent = %s, visit_dates = %s, created_at = NOW()
                                WHERE id = %s
                            """, (json.dumps(facts, ensure_ascii=False), total_score_new, max_score_new, month_percent_new, json.dumps(visit_dates), report_id))
                            
                            conn.commit()
                            cur.close()
                            conn.close()
                            
                            st.success(f"Выезд #{i+1} удалён")
                            st.rerun()
                
                # Кнопки действий
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button("💾 Сохранить изменения", key=f"save_{report_id}"):
                        if edited_facts != facts:
                            K = len(facts)
                            results, total_score, month_percent = calc_flexible_score_dynamic(N, K, edited_facts)
                            max_score = len(edited_facts) * 2
                            
                            conn = get_db_connection()
                            cur = conn.cursor()
                            cur.execute("""
                                UPDATE reports 
                                SET facts_json = %s, total_score = %s, max_score = %s, 
                                    month_percent = %s, created_at = NOW()
                                WHERE id = %s
                            """, (json.dumps(edited_facts, ensure_ascii=False), total_score, max_score, month_percent, report_id))
                            
                            conn.commit()
                            cur.close()
                            conn.close()
                            
                            st.success("✅ Изменения сохранены!")
                            st.rerun()
                        else:
                            st.info("Изменений не обнаружено")
                
                with col2:
                    if st.button("🗑 Удалить отчёт", key=f"del_{report_id}"):
                        delete_report(report_id)
                        st.success(f"Удалён отчёт ID={report_id}")
                        st.rerun()

st.caption("🔗 Данные обновляются из Google Sheets каждые 5 минут - НЕ ГУБИ СВОЙ КПИ !")
