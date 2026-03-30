import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

# --- UI SETUP ---
st.set_page_config(page_title="3-Korb-Strategie Profi", layout="wide")
st.title("📊 3-Korb-Strategie: Simulation bis heute")

# --- FUNKTIONEN ---
def berechne_brutto_und_steuer(netto_ziel, gewinn_anteil, ist_aktien_etf=False):
    st_satz = 0.26375 
    eff_st = st_satz * 0.70 * gewinn_anteil if ist_aktien_etf else st_satz * gewinn_anteil
    if eff_st >= 0.9: eff_st = 0.9
    brutto = netto_ziel / (1 - eff_st)
    return round(brutto, 2), round(brutto - netto_ziel, 2)

@st.cache_data
def lade_historische_renditen(ticker, start_date):
    try:
        # Wir laden 1,5 Jahre Puffer für die erste Renditeberechnung
        fetch_start = start_date - timedelta(days=500)
        raw_data = yf.download(ticker, start=fetch_start, interval="1mo")
        
        if raw_data.empty:
            return pd.DataFrame()

        # Yahoo Multi-Index Check
        data = raw_data['Close'][ticker] if isinstance(raw_data.columns, pd.MultiIndex) else raw_data['Close']
        data = data.dropna()
        
        # Renditen berechnen
        annual_data = data.resample('YE').last()
        returns = annual_data.pct_change().dropna()
        
        df = pd.DataFrame({
            "Jahr": returns.index.year.astype(int), 
            "Rendite_Dezimal": returns.values.astype(float)
        })
        
        # Filter auf Startjahr
        df = df[df["Jahr"] >= start_date.year]
        
        # YTD (Year to Date) Check für das laufende Jahr
        letztes_jahr = int(df["Jahr"].max()) if not df.empty else start_date.year - 1
        dieses_jahr = datetime.now().year
        
        if letztes_jahr < dieses_jahr:
            # Letzten Kurs heute vs. Schlusskurs letztes Jahr
            ytd_val = (data.iloc[-1] / data[data.index.year == letztes_jahr].iloc[-1]) - 1
            # Falls ytd_val ein Series Objekt ist, extrahieren
            val = float(ytd_val.iloc[0]) if hasattr(ytd_val, "__len__") else float(ytd_val)
            df = pd.concat([df, pd.DataFrame({"Jahr": [dieses_jahr], "Rendite_Dezimal": [val]})], ignore_index=True)
            
        return df.sort_values("Jahr")
    except Exception as e:
        st.error(f"Fehler beim Laden: {e}")
        return pd.DataFrame()

# --- SIDEBAR ---
INDEX_MAP = {"MSCI World (URTH)": "URTH", "S&P 500 (^GSPC)": "^GSPC", "Nasdaq 100 (^NDX)": "^NDX", "DAX (^GDAXI)": "^GDAXI"}
with st.sidebar:
    st.header("Konfiguration")
    ausgewaehlter_index = st.selectbox("Index wählen", list(INDEX_MAP.keys()))
    ticker_symbol = INDEX_MAP[ausgewaehlter_index]
    start_k1 = float(st.number_input("Korb 1 (€)", value=50000.0))
    start_k2 = float(st.number_input("Korb 2 (€)", value=100000.0))
    start_k3 = float(st.number_input("Korb 3 (€)", value=500000.0))
    start_datum = st.date_input("Simulationsbeginn", value=datetime(2012, 1, 1), min_value=datetime(1990, 1, 1))
    netto_wunsch_monat = st.number_input("Entnahme (€)", value=2500)
    profit_pct_start = st.slider("Gewinnanteil ETF (%)", 0, 100, 30) / 100

# --- HAUPTTEIL ---
st.subheader(f"Schritt 2: Renditen anpassen ({start_datum.year} bis heute)")
hist_df = lade_historische_renditen(ticker_symbol, start_datum)

if not hist_df.empty:
    display_df = hist_df.copy()
    display_df["Rendite (%)"] = (display_df["Rendite_Dezimal"] * 100).round(2)
    
    # Der Editor: Jahr als Text anzeigen, damit kein Tausenderpunkt erscheint
    display_df["Jahr"] = display_df["Jahr"].astype(str)
    
    edited_df = st.data_editor(
        display_df[["Jahr", "Rendite (%)"]],
        hide_index=True,
        use_container_width=True,
        key="main_editor"
    )
    
    if st.button("Simulation starten"):
        k1, k2, k3 = start_k1, start_k2, start_k3
        k3_gewinn = k3 * profit_pct_start
        jahres_ziel_netto = float(netto_wunsch_monat * 12)
        verlauf = []

        # Wir gehen durch die editierten Zeilen
        for _, row in edited_df.iterrows():
            jahr_str = row["Jahr"]
            r_val = float(row["Rendite (%)"]) / 100
            
            euro_rendite_k3 = k3 * r_val
            k3 += euro_rendite_k3
            k3_gewinn += euro_rendite_k3
            
            b_k1, b_k2, b_k3, steuer_jahr, logik_info = 0.0, 0.0, 0.0, 0.0, ""

            if r_val > 0 and euro_rendite_k3 >= jahres_ziel_netto:
                g_quote = max(0.05, min(0.95, k3_gewinn / k3)) if k3 > 0 else 0.5
                f_k1, f_k2 = max(0.0, start_k1 - k1), max(0.0, start_k2 - k2)
                b_k3, steuer_jahr = berechne_brutto_und_steuer(jahres_ziel_netto + f_k1 + f_k2, g_quote, True)
                k3 -= b_k3
                k3_gewinn -= (b_k3 * g_quote)
                k1, k2 = start_k1, start_k2
                logik_info = "K3 deckt alles"
            else:
                b_bedarf, steuer_jahr = berechne_brutto_und_steuer(jahres_ziel_netto, 0.10, False)
                e_k1 = min(k1, b_bedarf)
                k1 -= e_k1
                b_k1 = e_k1
                rest = b_bedarf - e_k1
                if rest > 0:
                    e_k2 = min(k2, rest)
                    k2 -= e_k2
                    b_k2 = e_k2
                f_k1_neu = max(0.0, start_k1 - k1)
                if f_k1_neu > 0 and k2 > 0:
                    transfer = min(k2, f_k1_neu)
                    k2 -= transfer
                    k1 += transfer
                    logik_info = "K2 füllt K1 auf"
                else:
                    logik_info = "Krise"

            k1 *= 1.02
            k2 *= 1.035
            
            verlauf.append({
                "Jahr": jahr_str,
                "Index-Rendite": f"{r_val:.2%}",
                "K1 (Bar)": round(k1),
                "K2 (Anleihen)": round(k2),
                "K3 (ETF)": round(k3),
                "Gesamt": round(k1 + k2 + k3),
                "Aktion": logik_info
            })

        # --- ANZEIGE-FIX ---
        res_df = pd.DataFrame(verlauf)
        
        # Wir setzen das Jahr als Index, um die 0-9 zu entfernen
        res_df.set_index("Jahr", inplace=True)
        
        st.write("---")
        st.subheader("Ergebnisse der Simulation")
        
        # Anzeige der Tabelle (Jahr ist jetzt die linke Spalte)
        st.dataframe(res_df, use_container_width=True)
        
        # Diagramm
        st.area_chart(res_df[["K1 (Bar)", "K2 (Anleihen)", "K3 (ETF)"]])

else:
    st.info("Daten werden geladen oder Startdatum ungültig.")