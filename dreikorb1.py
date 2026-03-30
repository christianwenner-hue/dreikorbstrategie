import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import date

# 1. Seite konfigurieren
st.set_page_config(page_title="Vibe Coding: Strategie-Check", layout="wide")
st.title("📊 Meine CC-Strategie vs. Benchmark")

# 2. Sidebar für die Steuerung
with st.sidebar:
    st.header("Start-Einstellungen")
    start_datum = st.date_input("Start-Datum", date(2015, 1, 1))
    total_kapital = st.number_input("Gesamtkapital (€)", value=800000)
    
    st.header("Entnahme & Logik")
    wunsch_netto = st.number_input("Monatliche Auszahlung (€)", value=6000)
    # Cash-Puffer Initialisierung auf 12 Monate Netto (Korb 1)
    cash_puffer_start = st.number_input("Start-Cash-Puffer (€)", value=wunsch_netto * 12) 
    
    st.header("Vergleich")
    benchmarks = {"Nasdaq 100": "QQQ", "S&P 500": "SPY", "MSCI World": "IWDA.AS"}
    wahl_name = st.selectbox("Benchmark-Linie:", list(benchmarks.keys()))
    bench_ticker = benchmarks[wahl_name]

    st.header("Parameter")
    div_rendite_pa = st.number_input("Dividende p.a. (%)", value=10.0) / 100
    crash_trigger = st.slider("Crash-Schutz bei Drawdown (%)", 10, 40, 20) / 100

# 3. Daten laden
@st.cache_data
def get_data(start_date, ticker):
    data = yf.download([ticker, "QQQ", "QYLD"], start=start_date, auto_adjust=True)
    if isinstance(data.columns, pd.MultiIndex):
        data = data["Close"]
    return data.ffill()

df_raw = get_data(start_datum, bench_ticker)
df_m = df_raw.resample("ME").last().ffill()

# 4. Simulation initialisieren
cap_cc = float(total_kapital - cash_puffer_start)
cash_cc = float(cash_puffer_start)
cap_bh = float(total_kapital)
einstand_cc = cap_cc
modus_cc = True

STEUER = 0.26375 
FREI = 0.70      
history = []
events = []
entnommen_total = 0.0

# Simulations-Schleife
for i in range(len(df_m) - 1):
    akt_d, fol_d = df_m.index[i], df_m.index[i+1]
    
    # --- A: Marktwert-Veränderung (Korb 3 Performance) ---
    depot_wert_start_monat = cap_cc
    
    qy_p = (df_m["QYLD"].iloc[i+1] / df_m["QYLD"].iloc[i]) - 1
    qqq_p = (df_m["QQQ"].iloc[i+1] / df_m["QQQ"].iloc[i]) - 1
    bench_p = (df_m[bench_ticker].iloc[i+1] / df_m[bench_ticker].iloc[i]) - 1
    
    # Performance anwenden (Korrektur: Klammern geschlossen)
    if modus_cc:
        cap_cc *= (1 + qy_p)
    else: 
        cap_cc *= (1 + qqq_p)
    
    # Reine Kursbewegung (Delta) festhalten
    marktwert_delta = cap_cc - depot_wert_start_monat
    
    # Crash-Logik prüfen
    peak = df_m["QQQ"][:fol_d].max()
    dd = (peak - df_m["QQQ"].iloc[i+1]) / peak
    
    steuer_monat = 0.0

    # Steuer-Event bei Verkauf (Crash-Trigger)
    if dd >= crash_trigger and modus_cc:
        gewinn = cap_cc - einstand_cc
        if gewinn > 0: 
            steuer_fall = gewinn * FREI * STEUER
            cap_cc -= steuer_fall
            steuer_monat += steuer_fall
        modus_cc = False
        events.append({"Datum": fol_d, "Typ": "Verkauf", "Drawdown": dd})
    elif dd < 0.05 and not modus_cc:
        modus_cc, einstand_cc = True, cap_cc
        events.append({"Datum": fol_d, "Typ": "Kauf", "Drawdown": dd})

    # --- B: Dividenden & Entnahme ---
    if modus_cc:
        brutto_div = cap_cc * (div_rendite_pa / 12)
        steuer_div = brutto_div * (FREI * STEUER) 
        netto_div = brutto_div - steuer_div
        cash_cc += netto_div
        steuer_monat += steuer_div

    cash_cc -= wunsch_netto
    entnommen_total += wunsch_netto
    
    # --- C: Rebalancing (Bewegung Korb 3 <-> Puffer) ---
    depot_cash_flow = 0.0
    max_puffer = wunsch_netto * 12
    
    # Fall 1: Puffer über Limit -> Überschuss zurück in Korb 3 (Depot)
    if cash_cc > max_puffer:
        ueberschuss = cash_cc - max_puffer
        cap_cc += ueberschuss
        cash_cc = max_puffer
        depot_cash_flow = -ueberschuss # Negativ = Geld fließt INS Depot
        
    # Fall 2: Puffer leer -> Geld aus Korb 3 (Depot) entnehmen
    elif cash_cc < 0:
        bedarf = abs(cash_cc)
        anteil_gewinn = (cap_cc - einstand_cc) / cap_cc if cap_cc > einstand_cc else 0
        if anteil_gewinn > 0:
            steuer_v = (bedarf * anteil_gewinn) * FREI * STEUER
            cap_cc -= (bedarf + steuer_v)
            steuer_monat += steuer_v
            depot_cash_flow = bedarf + steuer_v # Positiv = Geld kommt AUS Depot
        else:
            cap_cc -= bedarf
            depot_cash_flow = bedarf
        cash_cc = 0.0

    # Benchmark Buy & Hold
    cap_bh = (cap_bh * (1 + bench_p)) - wunsch_netto

    # Snapshot speichern
    history.append({
        "Datum": fol_d,
        "Jahr": fol_d.year,
        "CC_Gesamt": cap_cc + cash_cc,
        "Depotwert": cap_cc,
        "Cashpuffer": cash_cc,
        "Marktwert_Delta": marktwert_delta,
        "Depot_Cash_Flow": depot_cash_flow,
        "Entnommen_Total": entnommen_total,
        "BH_Gesamt": cap_bh,
        "Steuern_Monat": steuer_monat,
        "Modus": "CC" if modus_cc else "Index"
    })

results = pd.DataFrame(history)

# 5. Visualisierung: Chart
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["CC_Gesamt"], name="CC-Strategie Gesamt", 
    line=dict(width=3, color='#1f77b4'),
    customdata=results[["Depotwert", "Cashpuffer", "Entnommen_Total"]],
    hovertemplate="<b>%{x|%b %Y}</b><br>Gesamt: %{y:,.0f}€<br>Depot: %{customdata[0]:,.0f}€<br>Cash: %{customdata[1]:,.0f}€<extra></extra>"
))
fig.add_trace(go.Scatter(
    x=results["Datum"], y=results["BH_Gesamt"], name=f"B&H {wahl_name}", 
    line=dict(dash='dash', color='#ff7f0e'),
    hovertemplate="B&H: %{y:,.0f}€<extra></extra>"
))
fig.update_layout(margin=dict(t=60), hovermode="x unified", height=600)
st.plotly_chart(fig, use_container_width=True)

# 6. Visualisierung: Tabelle
st.subheader("📅 Jährliche Details & Bewegungen")

# Gruppieren für Jahreswerte (Stand Jahresende + Jahressummen)
yearly_last = results.groupby("Jahr").last().reset_index()
yearly_sums = results.groupby("Jahr")[["Marktwert_Delta", "Depot_Cash_Flow", "Steuern_Monat"]].sum().reset_index()

# Merge für die finale Ansicht
yearly = pd.merge(yearly_last[["Jahr", "CC_Gesamt", "Depotwert", "Cashpuffer", "Modus"]], 
                  yearly_sums, on="Jahr")

st.dataframe(
    yearly.style.format({
        "CC_Gesamt": "{:,.0f} €",
        "Depotwert": "{:,.0f} €", 
        "Cashpuffer": "{:,.0f} €",
        "Marktwert_Delta": "{:+,.0f} €",
        "Depot_Cash_Flow": "{:+,.0f} €",
        "Steuern_Monat": "{:,.0f} €"
    }).background_gradient(subset=["Marktwert_Delta"], cmap="RdYlGn", align='mid')
      .background_gradient(subset=["Depot_Cash_Flow"], cmap="RdGy_r", align='mid'),
    width='stretch', height=500
)

st.info("**Legende:**\n"
        "* **Marktwert_Delta**: Kursveränderung des Depots (Korb 3) durch Marktbewegung.\n"
        "* **Depot_Cash_Flow**: (+) Entnahme aus Depot wegen leerem Puffer | (-) Reinvestition von Überschuss ins Depot.")