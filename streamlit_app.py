import streamlit as st
import pandas as pd
import datetime
import io
import time

from mg_weather_openmeteo import resolvetimezoneandelevation, getweatherdatamixed
from mg_pv_core import (
    GeneratorConfig, defaultobstacles, defaultlosssettings,
    lossparamsforgenerator, computepvforgenerator, LOSSPARAMS
)

st.set_page_config(page_title="PV-Forecast Studio", layout="wide", page_icon="☀️")

# --- Session State 초기화 ---
if 'generators' not in st.session_state:
    st.session_state.generators = [
        GeneratorConfig(
            name="Generator 1",
            obstacles=[{"enabled": True, "centerazdeg": 200.0, "distm": 123.0, "heightm": 60.0, "widthm": 122.0}],
            losssettings=defaultlosssettings(),
        )
    ]
if 'results' not in st.session_state:
    st.session_state.results = None
if 'capped_message' not in st.session_state:
    st.session_state.capped_message = False
if 'calc_end_date' not in st.session_state:
    st.session_state.calc_end_date = None

# --- UI 헤더 ---
st.title("☀️ 소규모 전력망 최적화")
st.markdown("태양광 발전량을 예측하는 프로그램입니다. 좌측 사이드바에서 설정을 변경하고 실행해보세요!")

# --- 사이드바 (입력부) ---
with st.sidebar:
    st.header("⚙️ 설정")
    
    st.subheader("📅 기간 설정")
    start_date = st.date_input("시작일 (Start Date)", datetime.date.today())
    end_date = st.date_input("종료일 (End Date)", datetime.date.today() + datetime.timedelta(days=7))
    
    st.subheader("🌍 위치 설정")
    lat = st.number_input("위도 (Latitude)", value=37.4317862, format="%.7f")
    lon = st.number_input("경도 (Longitude)", value=126.6485109, format="%.7f")
    
    st.subheader("⚡ 발전기 목록")
    for i, gen in enumerate(st.session_state.generators):
        with st.expander(f"🔋 {gen.name}"):
            gen.name = st.text_input("이름", gen.name, key=f"name_{i}")
            
            st.markdown("**모듈 설정**")
            col1, col2 = st.columns(2)
            gen.modulepdcstcw = col1.number_input("모듈 STC (W)", value=float(gen.modulepdcstcw), key=f"modw_{i}")
            gen.modulecount = col2.number_input("모듈 개수", value=int(gen.modulecount), key=f"modcnt_{i}")
            gen.gammapctperc = col1.number_input("Gamma (%/°C)", value=float(gen.gammapctperc), key=f"gamma_{i}")
            
            face_options = ["Monofacial", "Bifacial"]
            face_idx = face_options.index(gen.facetype) if gen.facetype in face_options else 1
            gen.facetype = col2.selectbox("모듈 타입", face_options, index=face_idx, key=f"face_{i}")
            
            if gen.facetype == "Bifacial":
                gen.bifacialityfactorpct = st.number_input("양면 발전 계수 (%)", value=float(getattr(gen, 'bifacialityfactorpct', 70.0)), key=f"bifi_{i}")
            
            st.markdown("**인버터 설정**")
            col3, col4 = st.columns(2)
            gen.invacratedwper = col3.number_input("인버터 용량 (kW)", value=float(gen.invacratedwper)/1000.0, key=f"invkw_{i}") * 1000.0
            gen.invertercount = col4.number_input("인버터 개수", value=int(gen.invertercount), key=f"invcnt_{i}")
            gen.etainvnom = st.number_input("인버터 효율 (%)", value=float(gen.etainvnom)*100.0, key=f"eff_{i}") / 100.0
            
            st.markdown("**환경 설정**")
            col5, col6 = st.columns(2)
            gen.surfaceazimuth = col5.number_input("방위각 (deg)", value=float(gen.surfaceazimuth), key=f"az_{i}")
            gen.surfacetilt = col6.number_input("경사각 (deg)", value=float(gen.surfacetilt), key=f"tilt_{i}")
            
            mount_options = ["Open rack", "Close mount"]
            mount_idx = mount_options.index(gen.mounting) if gen.mounting in mount_options else 0
            gen.mounting = col5.selectbox("설치 형태", mount_options, index=mount_idx, key=f"mount_{i}")
            gen.albedo = col6.number_input("알베도 (반사율)", value=float(gen.albedo), key=f"albedo_{i}")
            gen.plannedavailability = st.number_input("가동률 (%)", value=float(gen.plannedavailability)*100.0, key=f"avail_{i}") / 100.0
            
            with st.expander("🚧 장애물 (Obstacles)"):
                obstacles_to_remove = []
                for j, obs in enumerate(gen.obstacles):
                    st.markdown(f"**장애물 {j+1}**")
                    en = st.checkbox("활성화", value=obs.get("enabled", False), key=f"obs_en_{i}_{j}")
                    if en:
                        c1, c2 = st.columns(2)
                        obs["centerazdeg"] = c1.number_input("방위각 (deg)", value=float(obs.get("centerazdeg") or 0), key=f"obs_az_{i}_{j}")
                        obs["distm"] = c2.number_input("거리 (m)", value=float(obs.get("distm") or 0), key=f"obs_d_{i}_{j}")
                        c3, c4 = st.columns(2)
                        obs["heightm"] = c3.number_input("높이 (m)", value=float(obs.get("heightm") or 0), key=f"obs_h_{i}_{j}")
                        obs["widthm"] = c4.number_input("너비 (m)", value=float(obs.get("widthm") or 0), key=f"obs_w_{i}_{j}")
                    obs["enabled"] = en
                    
                    if st.button(f"🗑️ 장애물 {j+1} 삭제", key=f"del_obs_{i}_{j}"):
                        obstacles_to_remove.append(j)
                        
                    st.divider()
                
                for j in reversed(obstacles_to_remove):
                    gen.obstacles.pop(j)
                    st.rerun()
                    
                if st.button("➕ 장애물 추가", key=f"add_obs_{i}"):
                    gen.obstacles.append({"enabled": True, "centerazdeg": 0, "distm": 0, "heightm": 0, "widthm": 0})
                    st.rerun()

            with st.expander("📉 손실 (Losses)"):
                for k, label in [
                    ("soiling", "Soiling"), ("mismatch", "Mismatch"), 
                    ("wiring", "Wiring"), ("connections", "Connections"), 
                    ("lid", "LID"), ("nameplate_rating", "Nameplate"), 
                    ("age", "Age"), ("availability", "Avail. loss")
                ]:
                    cur = gen.losssettings.get(k, {"enabled": True, "value": float(LOSSPARAMS.get(k, 0.0))})
                    c1, c2 = st.columns([1, 4])
                    with c1:
                        st.markdown("<div style='margin-top: 35px;'></div>", unsafe_allow_html=True)
                        en = st.checkbox(" ", value=cur.get("enabled", True), key=f"loss_en_{i}_{k}")
                    with c2:
                        val = st.number_input(f"{label} (%)", value=float(cur.get("value", 0.0)), disabled=not en, key=f"loss_val_{i}_{k}")
                    gen.losssettings[k] = {"enabled": en, "value": val}
            
            if st.button("❌ 발전기 삭제", key=f"del_{i}"):
                st.session_state.generators.pop(i)
                st.rerun()

    if st.button("➕ 발전기 추가"):
        st.session_state.generators.append(
            GeneratorConfig(
                name=f"Generator {len(st.session_state.generators) + 1}",
                obstacles=[{"enabled": True, "centerazdeg": 200.0, "distm": 123.0, "heightm": 60.0, "widthm": 122.0}],
                losssettings=defaultlosssettings(),
            )
        )
        st.rerun()

# --- 메인 화면 (결과 출력부) ---
st.subheader("🚀 시뮬레이션 실행")
st.markdown("좌측 사이드바에서 설정을 마친 후 아래 버튼을 눌러 발전량을 예측하세요.")

if st.button("🚀 실행 (Execute)", type="primary", use_container_width=True):
    if not st.session_state.generators:
        st.error("최소 1개의 발전기를 추가해주세요.")
    elif start_date > end_date:
        st.error("종료일은 시작일 이후여야 합니다.")
    else:
        today = datetime.date.today()
        max_forecast_date = today + datetime.timedelta(days=15)
        
        capped = False
        calc_end_date = end_date
        if end_date > max_forecast_date:
            calc_end_date = max_forecast_date
            capped = True
            
        st.session_state.capped_message = capped
        st.session_state.calc_end_date = calc_end_date
        
        with st.status("⚙️ 발전량 시뮬레이션 실행 중...", expanded=True) as status:
            try:
                start_s = start_date.strftime("%Y-%m-%d")
                end_s = calc_end_date.strftime("%Y-%m-%d")
                
                status.write("📡 Open-Meteo API를 통한 과거/예보 기상 데이터 수집 중...")
                tz, alt = resolvetimezoneandelevation(lat, lon)
                weatherhourly, weatherdaily = getweatherdatamixed(lat, lon, start_s, end_s, tz)
                
                results = {}
                total_hourly = None
                
                for i, gen in enumerate(st.session_state.generators):
                    status.write(f"⛰️ [{gen.name}] 주변 지형 및 장애물(Obstacles) 음영 효과 분석 중...")
                    obstaclesenabled = [o for o in gen.obstacles if o.get("enabled")]
                    lossparams = lossparamsforgenerator(gen)
                    
                    status.write(f"⚡ [{gen.name}] 태양광 모듈 용량, 인버터 효율 및 시스템 손실 파라미터 반영 중...")
                    status.write(f"🔄 [{gen.name}] 시간대별 일사량(GHI, DNI, DHI) 기반 발전량(kWh) 시뮬레이션 중...")
                    hourly, daily = computepvforgenerator(
                        weatherhourly, gen, obstaclesenabled, lossparams,
                        lat, lon, tz, alt
                    )
                    results[gen.name] = {"hourly": hourly, "daily": daily}
                    
                    cur = hourly[["acpowerw", "generationkwh"]].copy()
                    if total_hourly is None:
                        total_hourly = cur
                    else:
                        total_hourly = total_hourly.add(cur, fill_value=0.0)
                
                status.write("📊 전체 시스템 통합 발전량 및 통계 산출 중...")
                total_daily = total_hourly["generationkwh"].resample("D").sum().to_frame(name="dailygenerationkwh")
                results["Total"] = {"hourly": total_hourly, "daily": total_daily}
                
                st.session_state.results = results
                status.update(label="✅ 계산 완료!", state="complete", expanded=False)
            except Exception as e:
                status.update(label="❌ 오류 발생", state="error", expanded=True)
                st.error(f"오류 발생: {e}")

st.markdown("---")

if st.session_state.results:
    if st.session_state.get("capped_message"):
        st.warning(f"⚠️ Open-Meteo는 최대 16일간의 예보 데이터만 제공합니다. 따라서 발전량은 {st.session_state.calc_end_date.strftime('%Y-%m-%d')}까지만 계산되었습니다.")
        
    st.header("📊 분석 결과")
    
    tabs = st.tabs(list(st.session_state.results.keys()))
    
    for tab, key in zip(tabs, st.session_state.results.keys()):
        with tab:
            hourly = st.session_state.results[key]["hourly"]
            daily = st.session_state.results[key]["daily"]
            
            st.subheader(f"📈 {key} 발전량 요약")
            total_kwh = daily["dailygenerationkwh"].sum()
            st.metric("총 예상 발전량", f"{total_kwh:,.2f} kWh")
            
            st.line_chart(daily["dailygenerationkwh"])
            
            st.subheader("📅 시간대별 상세 데이터 (kWh)")
            df = hourly["generationkwh"].copy()
            try:
                df.index = df.index.tz_localize(None)
            except:
                pass
            df = df.reset_index()
            df.columns = ["time", "generationkwh"]
            df["date"] = df["time"].dt.date
            df["hour"] = df["time"].dt.hour
            
            mat = df.pivot(index="hour", columns="date", values="generationkwh").fillna(0.0)
            st.dataframe(mat.style.format("{:.2f}").background_gradient(cmap="YlOrRd"), use_container_width=True)

    st.markdown("---")
    st.subheader("💾 데이터 내보내기")
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for key, data in st.session_state.results.items():
            h = data["hourly"].copy()
            d = data["daily"].copy()
            try:
                h.index = h.index.tz_localize(None)
                d.index = d.index.tz_localize(None)
            except:
                pass
            h.to_excel(writer, sheet_name=f"{key}_Hourly"[:31])
            d.to_excel(writer, sheet_name=f"{key}_Daily"[:31])
            
    st.download_button(
        label="📥 엑셀 파일 다운로드",
        data=output.getvalue(),
        file_name=f"PV_Forecast_{start_date.strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary"
    )
