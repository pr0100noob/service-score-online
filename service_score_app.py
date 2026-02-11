import streamlit as st
import sqlite3
import json
from datetime import datetime
import pandas as pd

DB_PATH = "service_score.db"


# ---------------------- БЛОК БД ---------------------- #

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            stations INTEGER NOT NULL,
            visits INTEGER NOT NULL
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            facts_json TEXT NOT NULL,
            total_score INTEGER NOT NULL,
            max_score INTEGER NOT NULL,
            month_percent REAL NOT NULL,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        );
    """)
    conn.commit()
    conn.close()


def get_connection():
    return sqlite3.connect(DB_PATH)


def get_companies():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM companies ORDER BY name", conn)
    conn.close()
    return df


def add_company(name, stations, visits):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO companies (name, stations, visits) VALUES (?, ?, ?)",
        (name, stations, visits),
    )
    conn.commit()
    conn.close()


def save_report(company_id, facts, total_score, max_score, month_percent):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO reports (company_id, created_at, facts_json, total_score, max_score, month_percent)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            datetime.utcnow().isoformat(timespec="seconds"),
            json.dumps(facts, ensure_ascii=False),
            total_score,
            max_score,
            month_percent,
        ),
    )
    conn.commit()
    conn.close()


def get_reports(company_id=None):
    conn = get_connection()
    if company_id:
        df = pd.read_sql_query(
            """
            SELECT r.id, r.created_at, c.name AS company, r.facts_json,
                   r.total_score, r.max_score, r.month_percent
            FROM reports r
            JOIN companies c ON r.company_id = c.id
            WHERE c.id = ?
            ORDER BY r.created_at DESC
            """,
            conn,
            params=(company_id,),
        )
    else:
        df = pd.read_sql_query(
            """
            SELECT r.id, r.created_at, c.name AS company, r.facts_json,
                   r.total_score, r.max_score, r.month_percent
            FROM reports r
            JOIN companies c ON r.company_id = c.id
            ORDER BY r.created_at DESC
            """,
            conn,
        )
    conn.close()
    return df


def delete_report(report_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
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

init_db()
st.set_page_config(page_title="Баллы инженеров", layout="wide")
st.title("🏭 Расчёт баллов и журнал отчётов")

tab_calc, tab_log, tab_companies = st.tabs(["➕ Новый отчёт", "📜 Журнал", "🏢 Компании"])

# ---- Таб Компании ---- #
with tab_companies:
    st.subheader("Добавить / просмотреть компании")
    col_nc1, col_nc2, col_nc3 = st.columns(3)
    with col_nc1:
        new_name = st.text_input("Название компании")
    with col_nc2:
        new_N = st.number_input("Станций по договору (N)", min_value=1, value=47)
    with col_nc3:
        new_K = st.number_input("Выездов в месяц (K)", min_value=1, value=4)

    if st.button("💾 Сохранить компанию"):
        if new_name.strip():
            add_company(new_name.strip(), int(new_N), int(new_K))
            st.success("Компания сохранена")
        else:
            st.error("Введите название компании")

    st.markdown("### Список компаний")
    companies_df = get_companies()
    st.dataframe(companies_df, use_container_width=True)

# ---- Таб Новый отчёт ---- #
with tab_calc:
    st.subheader("Создать отчёт по компании")

    companies_df = get_companies()
    if companies_df.empty:
        st.info("Сначала добавьте компанию на вкладке 'Компании'.")
    else:
        company_names = companies_df["name"].tolist()
        selected_name = st.selectbox("Компания", company_names)
        company_row = companies_df[companies_df["name"] == selected_name].iloc[0]
        N = int(company_row["stations"])
        K = int(company_row["visits"])

        st.write(f"Станций по договору: **{N}**, выездов в месяц: **{K}**")

        num_visits = st.number_input(
            "Сколько выездов учесть в этом отчёте",
            min_value=1,
            max_value=K,
            value=K,
        )

        st.markdown("**Факт по выездам:**")
        facts = []
        for i in range(num_visits):
            f = st.number_input(f"Выезд #{i+1}", min_value=0, value=0, key=f"calc_f{i}")
            facts.append(int(f))

        if st.button("🚀 Рассчитать и сохранить отчёт", type="primary"):
            results, total_score, month_percent = calc_flexible_score_dynamic(
                N, K, facts
            )
            max_score = num_visits * 2

            st.markdown("### Детальный расчёт")
            st.markdown(
                """
**Легенда:**
- **Выезд** — номер выезда в месяце  
- **P** — план на выезд (остаток/оставшиеся)  
- **F** — факт станций  
- **%выезд** — % выполнения плана выезда  
- **Баллы** — KPI (0/1/2)  
- **Ожид.%** — ожидаемый % от всех станций  
- **Факт.%** — фактический % от всех станций  
- **Статус** — итоговая оценка выезда
"""
            )
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

            c1, c2, c3 = st.columns(3)
            c1.metric("Итого баллов", f"{total_score} из {max_score}")
            c2.metric("Выполнено по месяцу", f"{month_percent}%", f"{sum(facts)}/{N}")
            c3.metric("Компания", selected_name)

            # сохранить в БД
            save_report(int(company_row["id"]), facts, total_score, max_score, month_percent)
            st.success("Отчёт сохранён в журнал.")

# ---- Таб Журнал ---- #
with tab_log:
    st.subheader("Журнал отчётов")

    companies_df = get_companies()
    filter_company = None
    if not companies_df.empty:
        names = ["Все компании"] + companies_df["name"].tolist()
        name_choice = st.selectbox("Фильтр по компании", names)
        if name_choice != "Все компании":
            filter_company = int(
                companies_df[companies_df["name"] == name_choice]["id"].iloc[0]
            )

    reports_df = get_reports(filter_company)
    if reports_df.empty:
        st.info("Отчётов пока нет.")
    else:
        # красиво развернуть facts_json в отдельный столбец
        reports_df["Факты по выездам"] = reports_df["facts_json"].apply(
            lambda x: ", ".join(map(str, json.loads(x)))
        )
        reports_df_view = reports_df[
            ["id", "created_at", "company", "Факты по выездам", "total_score", "max_score", "month_percent"]
        ].rename(
            columns={
                "id": "ID",
                "created_at": "Создан",
                "company": "Компания",
                "total_score": "Баллы",
                "max_score": "Макс. баллов",
                "month_percent": "% месяц",
            }
        )

        st.dataframe(reports_df_view, use_container_width=True, hide_index=True)

        del_id = st.number_input("ID отчёта для удаления", min_value=0, value=0, step=1)
        if st.button("🗑 Удалить отчёт"):
            if del_id > 0:
                delete_report(int(del_id))
                st.success(f"Отчёт ID={del_id} удалён. Обновите страницу (R).")
            else:
                st.error("Укажите корректный ID (>0).")
