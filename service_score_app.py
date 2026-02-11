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
    return psycopg2.connect(
        host="localhost",
        database="service_score_journal",
        user="postgres",
        password="postgres"  # ЗАМЕНИ!
    )


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
                SELECT id, created_at, company_name, facts_json, total_score, max_score, month_percent
                FROM reports WHERE company_name = %s ORDER BY created_at DESC
            """, (company_name,))
        else:
            cur.execute("""
                SELECT id, created_at, company_name, facts_json, total_score, max_score, month_percent
                FROM reports ORDER BY created_at DESC
            """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        df = pd.DataFrame(rows, columns=["id", "created_at", "company_name", "facts_json", "total_score", "max_score", "month_percent"])
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
st.title("🏭 Расчёт баллов и журнал отчётов")

tab_calc, tab_journal = st.tabs(["➕ Новый отчёт", "📋 Журнал отчётов"])

with tab_calc:
    st.subheader("Создать отчёт по компании")

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
        
        st.write(f"Станций по договору: **{N}**")
        K = st.number_input("Выездов в месяц (K)", min_value=1, value=4)

        num_visits = st.number_input("Сколько выездов учесть", min_value=1, max_value=K, value=K)

        st.markdown("**Факт по выездам:**")
        facts = []
        for i in range(num_visits):
            f = st.number_input(f"Выезд #{i+1}", min_value=0, value=0, key=f"calc_f{i}")
            facts.append(int(f))

        if st.button("🚀 Рассчитать и сохранить", type="primary"):
            results, total_score, month_percent = calc_flexible_score_dynamic(N, K, facts)
            max_score = num_visits * 2

            st.markdown("### Детальный расчёт")
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

            c1, c2, c3 = st.columns(3)
            c1.metric("Итого баллов", f"{total_score} из {max_score}")
            c2.metric("Выполнено", f"{month_percent}%")
            c3.metric("Компания", selected_name)

            # Сохраняем в PostgreSQL
            save_report(selected_name, facts, total_score, max_score, month_percent)
            st.success("✅ Отчёт сохранён в БД!")

with tab_journal:
    st.subheader("📋 Журнал всех отчётов")

    try:
        companies_df = load_companies_from_gsheet()
        names = ["Все компании"] + companies_df["name"].tolist()
        filter_company = st.selectbox("Фильтр", names)
        filter_company = None if filter_company == "Все компании" else filter_company
    except:
        filter_company = None

    reports_df = get_reports(filter_company)
    if reports_df.empty:
        st.info("Отчётов пока нет.")
    else:
        reports_df["Факты"] = reports_df["facts_json"].apply(lambda x: ", ".join(map(str, json.loads(x))))
        reports_df_view = reports_df[["id", "created_at", "company_name", "Факты", "total_score", "max_score", "month_percent"]]
        reports_df_view = reports_df_view.rename(columns={
            "id": "ID", "created_at": "Создан", "company_name": "Компания",
            "total_score": "Баллы", "max_score": "Макс", "month_percent": "% месяц"
        })

        st.dataframe(reports_df_view, use_container_width=True, hide_index=True)

        del_id = st.number_input("ID для удаления", min_value=0, value=0)
        if st.button("🗑 Удалить"):
            if del_id > 0:
                delete_report(int(del_id))
                st.success(f"Удалён ID={del_id}")
                st.rerun()

st.caption("🔗 Данные обновляются из Google Sheets каждые 5 минут")
