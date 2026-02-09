import streamlit as st

def calc_flexible_score_dynamic(N, K, facts):
    results = []
    remaining_stations = N
    remaining_visits = K
    total_done = 0
    total_score = 0
    
    for i in range(len(facts)):
        F_i = facts[i]
        P_i = remaining_stations / remaining_visits if remaining_visits > 0 else 0
        percent_visit = (F_i / P_i * 100) if P_i > 0 else 0
        
        expected_progress = ((i+1) / K * 100) if K > 0 else 0
        actual_progress = (total_done + F_i) / N * 100 if N > 0 else 0
        
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
            'Выезд': f"#{i+1}", 'План': round(P_i, 1), 'Факт': F_i, '%выезд': f"{round(percent_visit, 1)}%",
            'Баллы': score, 'Ожид.%': f"{round(expected_progress, 1)}%", 
            'Факт.%': f"{round(actual_progress, 1)}%", 'Статус': status
        })
        
        remaining_stations -= F_i
        remaining_visits -= 1
        total_done += F_i
        total_score += score
    
    month_percent = round((total_done / N * 100), 1) if N > 0 else 0
    return results, total_score, month_percent

st.set_page_config(page_title="Расчёт баллов инженеров", layout="wide")
st.title("🏭 Расчёт баллов сервисных инженеров")

col1, col2 = st.columns(2)
with col1:
    st.header("📋 Вводные данные")
    N = st.number_input("Станций по договору (N)", min_value=1, value=0)
    K = st.number_input("Выездов в месяц (K)", min_value=1, value=0)

num_visits = st.number_input("Сколько выездов учесть", min_value=1, max_value=20, value=0)

with col2:
    st.header("📈 Результат")
    if 'results' in st.session_state:
        st.dataframe(st.session_state.results, use_container_width=True)

st.markdown("### Фактически проверено по выездам")
facts = []
for i in range(num_visits):
    f = st.number_input(f"Выезд #{i+1}", min_value=0, value=0, key=f"f{i}")
    facts.append(f)

if st.button("🚀 Рассчитать баллы", type="primary"):
    if N > 0 and K > 0 and num_visits > 0:
        results, total_score, month_percent = calc_flexible_score_dynamic(N, K, facts)
        st.session_state.results = results
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Итого баллов", total_score)
        col2.metric("Выполнено по месяцу", f"{month_percent}%")
        col3.metric("Всего станций", f"{sum(facts)}/{N}")
    else:
        st.error("❌ Заполни все поля!")

st.markdown("---")
st.caption("👥 Поделись ссылкой — все увидят расчёт!")
