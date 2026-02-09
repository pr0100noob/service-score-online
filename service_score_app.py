import streamlit as st
import pandas as pd

def calc_flexible_score_dynamic(N, K, facts):
    if N == 0 or K == 0:
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
        
        expected_progress = ((i+1) / K * 100)
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
            'Выезд': i+1, 'P': round(P_i, 1), 'F': F_i, '%выезд': round(percent_visit, 1),
            'Баллы': score, 'Ожид.%': round(expected_progress, 1), 
            'Факт.%': round(actual_progress, 1), 'Статус': status
        })
        
        remaining_stations -= F_i
        remaining_visits -= 1
        total_done += F_i
        total_score += score
    
    month_percent = round((total_done / N * 100), 1)
    return results, total_score, month_percent

st.set_page_config(page_title="Расчёт баллов", layout="wide")
st.title("🏭 Расчёт баллов сервисных инженеров")

col1, col2 = st.columns([1,2])
with col1:
    st.header("📋 Данные")
    N = st.number_input("Станций по договору (N)", min_value=0, value=47)
    K = st.number_input("Выездов в месяц (K)", min_value=0, value=4)
    
    num_visits = st.number_input("Выездов учесть", min_value=0, max_value=20, value=4)
    
    st.markdown("### Факт по выездам")
    facts = []
    fact_inputs = []
    for i in range(num_visits):
        f = st.number_input(f"Выезд #{i+1}", min_value=0, value=0, key=f"f{i}")
        facts.append(f)

if st.button("🚀 Рассчитать", type="primary"):
    results, total_score, month_percent = calc_flexible_score_dynamic(N, K, facts)
    
    with col2:
        st.header("📊 Детальный расчёт")
        
        df = pd.DataFrame(results)
        st.dataframe(df.style.format({
            '%выезд': '{:.1f}%', 'Ожид.%': '{:.1f}%', 'Факт.%': '{:.1f}%'
        }), use_container_width=True, hide_index=True)
        
        st.markdown("---")
        col1m, col2m, col3m = st.columns(3)
        col1m.metric("**Итого баллов**", total_score)
        col2m.metric("**Месяц**", f"{month_percent}%")
        col3m.metric("**Станций**", f"{sum(facts)}/{N}")

st.markdown("---")
st.caption("💬 Ссылка для коллег")
