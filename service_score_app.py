import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ---------------------- КОНФИГУРАЦИЯ ---------------------- #
SPREADSHEET_ID = "1048LAnXOi822I87iLgommj-181thuzktnvdhQmzUfho"
SHEET_NAME = "Клиенты"

# ---------------------- GOOGLE SHEETS ---------------------- #

@st.cache_data(ttl=300)  # кеш на 5 минут
def load_companies_from_gsheet():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # Проверяем: локально или Streamlit Cloud
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    else:
        creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    
    # Читаем все данные
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

        results.append(
            {
                "Выезд": i + 1,
                "P": round(P_i, 1),
                "F": F_i,
                "%выезд": f"{round(percent_visit, 1)}%",
                "Баллы": score,
                "Ожид.%": f"{round(expected_progress, 1)}%",
                "Факт.%": f"{round(actual_progress, 1)}%",
                "Статус": status,
            }
        )

        remaining_stations -= F_i
        remaining_visits -= 1
        total_done += F_i
        total_score += score

    month_percent = round(total_done / N * 100, 1)
    return results, total_score, month_percent

# ---------------------- UI ---------------------- #

st.set_page_config(page_title="Баллы инженеров", layout="wide")
st.title("🏭 Расчёт баллов выездных инженеров")

try:
    companies_df = load_companies_from_gsheet()
except Exception as e:
    st.error(f"❌ Ошибка загрузки компаний из Google Sheets: {e}")
    companies_df = pd.DataFrame()

if companies_df.empty:
    st.info("Нет данных из Google Sheets. Проверь доступ и название листа.")
else:
    company_names = companies_df["name"].tolist()
    selected_name = st.selectbox("Компания", company_names)
    company_row = companies_df[companies_df["name"] == selected_name].iloc[0]
    N = int(company_row["stations"])
    
    st.write(f"Станций по договору: **{N}**")
    K = st.number_input("Выездов в месяц (K)", min_value=1, value=4)

    num_visits = st.number_input(
        "Сколько выездов учесть в отчёте",
        min_value=1,
        max_value=K,
        value=K,
    )

    st.markdown("**Факт по выездам:**")
    facts = []
    for i in range(num_visits):
        f = st.number_input(f"Выезд #{i+1}", min_value=0, value=0, key=f"f{i}")
        facts.append(int(f))

    if st.button("🚀 Рассчитать баллы", type="primary"):
        results, total_score, month_percent = calc_flexible_score_dynamic(N, K, facts)
        max_score = num_visits * 2

        st.markdown("---")
        st.markdown("### 📊 Детальный расчёт")
        st.markdown("""
**📋 Легенда:**
- **Выезд** — номер выезда в месяце  
- **P** — план на выезд (остаток/оставшиеся выезды)
- **F** — факт станций
- **%выезд** — выполнение плана выезда
- **Баллы** — баллы KPI (макс. 2 за выезд)
- **Ожид.%** — ожидаемый % от всех станций
- **Факт.%** — фактический % от всех станций  
- **Статус** — итоговая оценка
        """)
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("Итого баллов", f"{total_score} из {max_score}")
        c2.metric("Выполнено по месяцу", f"{month_percent}%", f"{sum(facts)}/{N}")
        c3.metric("Компания", selected_name)

st.markdown("---")
st.caption("🔗 Данные компаний обновляются из Google Sheets каждые 5 минут")
