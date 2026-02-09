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
            'выезд': i+1, 'P': round(P_i, 1), 'F': F_i, '%выезд': round(percent_visit, 1),
            'баллы': score, 'ожидаемый_%': round(expected_progress, 1), 
            'факт_%': round(actual_progress, 1), 'status': status
        })
        
        remaining_stations -= F_i
        remaining_visits -= 1
        total_done += F_i
        total_score += score
    
    month_percent = round((total_done / N * 100), 1) if N > 0 else 0
    return results, total_score, month_percent

st.title("🏭 Расчёт баллов сервисных инженеров")
st.markdown("---")

col1, col2 = st.columns(2)
with col1:
    N = st.number_input("Станций по договору (N)", min_value=1, value=47)
    K = st.number_input("Выездов в месяц (K)", min_value=1, value=4)

num_visits = st.number_input("Сколько выездов учесть", min_value=1, max_value=20, value=4)

st.markdown("### Фактически проверено по выездам")
facts = []
for i in range(num_visits):
    f = st.number_input(f"Выезд {i+1}", min_value=0, value=10, key=f"f{i}")
    facts.append(f)

if st.button("🚀 Рассчитать баллы"):
    results, total_score, month_percent = calc_flexible_score_dynamic(N, K, facts)
    
    st.markdown("---")
    st.subheader("📊 Результаты")
    
    df = st.dataframe(results, use_container_width=True)
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Итого баллов", total_score)
    col2.metric("Выполнено по месяцу", f"{month_percent}%")
    col3.metric("Всего станций", f"{sum(facts)}/{N}")
    
    st.markdown("---")
    st.caption("Поделись ссылкой — все увидят расчёт!")
