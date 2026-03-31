import streamlit as st
import pandas as pd
import yfinance as yf
import altair as alt
from datetime import datetime
import io

# --- UI SETUP ---
st.set_page_config(page_title="Strategiecheck: Dreikorb", layout="wide")
st.title("Vergleich: Dreikorb vs. Vollinvestition")

# --- 1. FUNKTIONEN (Logik ausgelagert) ---
def berechne_brutto_und_steuer(netto_ziel, gewinn_anteil, ist_etf=False):
    st_satz = 0.26375 
    if ist_etf:
        eff_st = st_satz * 0.70 * gewinn_anteil
    else:
        eff_st = st_satz * gewinn_anteil
        
    if eff_st >= 0.9: 
        eff_st = 0.9 
        
    brutto = netto_ziel / (1 - eff_st)
    return round(brutto, 2), round(brutto - netto_ziel, 2)

@st.cache_data(show_spinner=False, ttl=60)
def lade_marktdaten(ticker):
    try:
        # HIER GEÄNDERT: period="max" holt alle Daten, die Yahoo Finance jemals für diesen Ticker hat!
        raw = yf.download(ticker, period="max", interval="1mo", progress=False)
        
        if raw.empty: return pd.DataFrame()
            
        if isinstance(raw.columns, pd.MultiIndex):
            data = raw['Close'][ticker]
        else:
            data = raw['Close']
            
        data = data.dropna()
        returns = data.pct_change().dropna()
        
        df = pd.DataFrame({
            "Datum": returns.index,
            "Jahr": returns.index.year.astype(int), 
            "Monat": returns.index.month.astype(int),
            "Rendite_Monat": returns.values.astype(float)
        })
        
        return df.sort_values(["Jahr", "Monat"])
    except Exception:
        return pd.DataFrame()

def simuliere_strategie(hist_df, start_jahr, k1_start, k2_start, k3_start, rente_start, p_pct, infl_pa, zins_k1_pa, zins_k2_pa):
    df_sim = hist_df[hist_df["Jahr"] >= start_jahr]
    if df_sim.empty: return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None, None

    k1, k2, k3 = k1_start, k2_start, k3_start
    k3_g = k3 * p_pct
    
    kv = k1_start + k2_start + k3_start
    kv_g = kv * p_pct
    
    rm_k1 = (1 + zins_k1_pa/100)**(1/12) - 1
    rm_k2 = (1 + zins_k2_pa/100)**(1/12) - 1
    rm_infl = (1 + infl_pa/100)**(1/12) - 1
    
    aktuelle_rente = rente_start
    
    m_3k, m_v, j_graf = [], [], []
    pleite_jahr_3k = None
    pleite_jahr_vl = None

    jahre = df_sim["Jahr"].unique()

    for jahr in jahre:
        df_jahr = df_sim[df_sim["Jahr"] == jahr]
        rj = (df_jahr["Rendite_Monat"] + 1).prod() - 1 
        q_letzte_aktion = ""
        
        for _, row in df_jahr.iterrows():
            m = int(row["Monat"])
            rm = float(row["Rendite_Monat"]) 
            
            aktuelle_rente *= (1 + rm_infl)
            
            if k1 > 0: k1 *= (1 + rm_k1)
            if k2 > 0: k2 *= (1 + rm_k2)
            
            if k3 > 0:
                k3_v = k3 * (1 + rm)
                k3_g += (k3_v - k3)
                k3 = k3_v
            else:
                k3_v = 0
                
            if kv > 0:
                kv_v = kv * (1 + rm)
                kv_g += (kv_v - kv)
                kv = kv_v
            else:
                kv_v = 0
            
            b_m, s_m = 0.0, 0.0
            q = "Pleite"
            gesamt_3k = k1 + k2 + k3
            
            if gesamt_3k > 0:
                if rj > 0 and k3 > aktuelle_rente:
                    gq = max(0.1, min(0.9, k3_g/k3)) if k3 > 0 else 0.5
                    b_m, s_m = berechne_brutto_und_steuer(aktuelle_rente, gq, True)
                    k3 = max(0, k3 - b_m)
                    k3_g -= (b_m * gq)
                    q = "K3 (Aktien)"
                else:
                    b_m, s_m = berechne_brutto_und_steuer(aktuelle_rente, 0.1, False)
                    if k1 >= b_m:
                        k1 -= b_m
                        q = "K1 (Cash)"
                    elif (k1 + k2) >= b_m:
                        rest = b_m - k1
                        k1 = 0
                        k2 -= rest
                        q = "K1 und K2"
                    else:
                        k3 = max(0, k3 - b_m)
                        q = "K3 (Notverkauf)"
            elif not pleite_jahr_3k:
                pleite_jahr_3k = jahr
            
            if m == 12 and rj > 0 and gesamt_3k > 0:
                fehlbetrag = max(0, (k1_start - k1)) + max(0, (k2_start - k2))
                if fehlbetrag > 0 and k3 > fehlbetrag:
                    gqf = max(0.1, min(0.9, k3_g/k3)) if k3 > 0 else 0.5
                    bf, _ = berechne_brutto_und_steuer(fehlbetrag, gqf, True)
                    k3 -= bf
                    k3_g -= (bf * gqf)
                    k1 = k1_start
                    k2 = k2_start
                    q += " + Auffuellen"
            
            bv, sv = 0.0, 0.0
            if kv > 0:
                gv = max(0.1, min(0.9, kv_g/kv)) if kv > 0 else 0.5
                bv, sv = berechne_brutto_und_steuer(aktuelle_rente, gv, True)
                kv = max(0, kv - bv)
                kv_g -= (bv * gv)
            elif not pleite_jahr_vl:
                pleite_jahr_vl = jahr
                
            q_letzte_aktion = q
            
            m_3k.append({"Jahr": str(jahr), "Monat": m, "Rendite_Markt": f"{rm:.4%}", "Rente_Inflationsbereinigt": round(aktuelle_rente, 2), "Aktion": q, "K1": round(k1, 2), "K2": round(k2, 2), "K3": round(k3, 2), "Gesamt": round(k1+k2+k3, 2)})
            m_v.append({"Jahr": str(jahr), "Monat": m, "Gesamt": round(kv, 2)})
            
        j_graf.append({
            "Jahr_Int": int(jahr),
            "Datum": f"{jahr}-12-31",
            "K1_Wert": round(k1), "K2_Wert": round(k2), "K3_Wert": round(k3),
            "Dreikorb": round(k1+k2+k3),
            "Vollinvestition": round(kv),
            "Aktion": q_letzte_aktion,
            "Rendite": f"{rj:.2%}"
        })

    return pd.DataFrame(m_3k), pd.DataFrame(m_v), pd.DataFrame(j_graf), pleite_jahr_3k, pleite_jahr_vl

# --- 2. SIDEBAR ---
I_MAP = {"MSCI World": "URTH", "S&P 500": "^GSPC", "Nasdaq 100": "^NDX", "DAX": "^GDAXI"}

with st.sidebar:
    st.header("Startkapital & Körbe")
    idx_name = st.selectbox("Index für K3", list(I_MAP.keys()))
    t_sym = I_MAP[idx_name]
    
    k1_s = st.number_input("K1 Cash (€)", value=50000.0, step=5000.0)
    k2_s = st.number_input("K2 Anleihen (€)", value=100000.0, step=5000.0)
    k3_s = st.number_input("K3 Aktien (€)", value=500000.0, step=10000.0)
    
    st.divider()
    st.header("Entnahme & Parameter")
    s_dat = st.date_input("Startdatum Simulation", value=datetime(2012, 1, 1))
    n_monat = st.number_input("Netto Rente im 1. Monat (€)", value=2500)
    p_pct = st.slider("Aktueller Gewinnanteil im Depot (%)", 0, 100, 30) / 100
    
    st.divider()
    st.header("Erweiterte Annahmen")
    infl = st.number_input("Inflation p.a. (%)", value=2.0, step=0.1)
    zins_k1 = st.number_input("Zins K1 Cash p.a. (%)", value=1.5, step=0.1)
    zins_k2 = st.number_input("Zins K2 Anleihen p.a. (%)", value=3.0, step=0.1)

# --- 3. ANZEIGE & SIMULATION ---

st.info("👈 **Tipp:** Wähle links den S&P 500, um historische Szenarien bis weit ins letzte Jahrhundert zu testen!")

with st.spinner("Lade maximale historische Marktdaten von Yahoo Finance..."):
    # HIER GEÄNDERT: Wir übergeben das Startdatum nicht mehr, die Funktion holt einfach alles
    hist_df = lade_marktdaten(t_sym)

if hist_df.empty:
    st.error(f"⚠️ Es konnten keine Marktdaten geladen werden.")
else:
    erstes_jahr = hist_df["Jahr"].min()
    st.success(f"✅ Maximale Historie geladen! Daten für **{idx_name}** reichen zurück bis ins Jahr **{erstes_jahr}**.")
    
    if st.button("🚀 Simulation jetzt starten", type="primary", use_container_width=True):
        
        # 1. Die Hauptsimulation (für das gewählte Startjahr in der Sidebar)
        df_3k, df_v, df_plot, pleite_3k, pleite_vl = simuliere_strategie(
            hist_df, s_dat.year, k1_s, k2_s, k3_s, n_monat, p_pct, infl, zins_k1, zins_k2
        )
        
        st.divider()
        
        if df_plot.empty:
            st.error("Das gewählte Startdatum liegt vor dem Auflegungsdatum dieses Index/ETFs. Bitte wähle ein jüngeres Startdatum oder einen Index mit längerer Historie (z.B. S&P 500).")
        else:
            start_gesamt = k1_s + k2_s + k3_s
            end_3k = df_plot["Dreikorb"].iloc[-1]
            end_vl = df_plot["Vollinvestition"].iloc[-1]
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Startkapital", f"{start_gesamt:,.0f} €".replace(",", "."))
            with col2:
                delta_3k = end_3k - start_gesamt
                st.metric("Endvermögen Dreikorb", f"{end_3k:,.0f} €".replace(",", "."), f"{delta_3k:,.0f} €", delta_color="normal")
                if pleite_3k: st.error(f"🚨 Dreikorb pleite im Jahr {pleite_3k}")
            with col3:
                delta_vl = end_vl - start_gesamt
                st.metric("Endvermögen Vollinvestition", f"{end_vl:,.0f} €".replace(",", "."), f"{delta_vl:,.0f} €", delta_color="normal")
                if pleite_vl: st.error(f"🚨 Vollinvestition pleite im Jahr {pleite_vl}")

            st.divider()

            st.subheader("Entwicklung der drei Körbe (Gestapelt)")
            df_area = df_plot[["Datum", "K1_Wert", "K2_Wert", "K3_Wert"]].melt(
                id_vars="Datum", var_name="Korb", value_name="Kapital"
            )
            area_chart = alt.Chart(df_area).mark_area().encode(
                x=alt.X("Datum:T", title="Jahr"),
                y=alt.Y("Kapital:Q", title="Kapital in €", stack=True),
                color=alt.Color("Korb:N", scale=alt.Scale(domain=["K3_Wert", "K2_Wert", "K1_Wert"], range=["#2ca02c", "#ff7f0e", "#1f77b4"])),
                tooltip=["Datum:T", "Korb:N", alt.Tooltip("Kapital:Q", format=",.0f")]
            ).interactive()
            st.altair_chart(area_chart, use_container_width=True)

            st.subheader("Vergleich: Dreikorb vs. Vollinvestition")
            df_plot["DK_Euro"] = df_plot["Dreikorb"].map('{:,.0f} €'.format)
            df_plot["VL_Euro"] = df_plot["Vollinvestition"].map('{:,.0f} €'.format)
            
            base_chart = alt.Chart(df_plot).encode(x=alt.X('Jahr_Int:O', title='Jahr'))
            line_dk = base_chart.mark_line(size=3, color='#1f77b4').encode(y=alt.Y('Dreikorb:Q', title='Vermögen'))
            line_vl = base_chart.mark_line(size=3, color='#ff7f0e', strokeDash=[5,5]).encode(y='Vollinvestition:Q')
            
            selector = alt.selection_point(fields=['Jahr_Int'], nearest=True, on='mouseover', empty=False)
            points = base_chart.mark_point(size=100, opacity=0).encode(
                y='Dreikorb:Q',
                tooltip=[
                    alt.Tooltip('Jahr_Int:N', title='Jahr'),
                    alt.Tooltip('Rendite:N', title='Marktrendite'),
                    alt.Tooltip('DK_Euro:N', title='Dreikorb'),
                    alt.Tooltip('VL_Euro:N', title='Vollinvest'),
                    alt.Tooltip('Aktion:N', title='Letzte Aktion')
                ]
            ).add_params(selector)
            st.altair_chart(line_dk + line_vl + points, use_container_width=True)
            
            # --- 7. EXCEL EXPORT ---
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df_3k.to_excel(writer, index=False, sheet_name='Dreikorb_Details')
                df_v.to_excel(writer, index=False, sheet_name='Vollinvestition')
                df_plot.drop(columns=["Datum", "DK_Euro", "VL_Euro"]).to_excel(writer, index=False, sheet_name='Jahresübersicht')
            
            st.download_button(
                label="📥 Detaillierte Excel-Simulation herunterladen", 
                data=excel_buffer.getvalue(), 
                file_name="Dreikorb_Simulation.xlsx", 
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            # --- 8. ROLLIERENDE STARTJAHRE ---
            st.divider()
            st.header("🎯 Szenario-Analyse: Welches Startjahr begünstigt welche Strategie?")
            st.write("Diese Auswertung simuliert den Renteneintritt für **jedes historisch verfügbare Jahr** (bis vor 5 Jahren) und zeigt dir den Vermögensunterschied am Ende der Laufzeit.")
            
            with st.spinner("Berechne alle historischen Szenarien..."):
                alle_jahre = sorted(hist_df["Jahr"].unique())
                letztes_erlaubtes_jahr = datetime.now().year - 4 
                test_jahre = [j for j in alle_jahre if j <= letztes_erlaubtes_jahr]
                
                szenarien_ergebnisse = []
                
                for test_jahr in test_jahre:
                    _, _, temp_plot, _, _ = simuliere_strategie(
                        hist_df, test_jahr, k1_s, k2_s, k3_s, n_monat, p_pct, infl, zins_k1, zins_k2
                    )
                    
                    if not temp_plot.empty:
                        end_dk_test = temp_plot["Dreikorb"].iloc[-1]
                        end_vl_test = temp_plot["Vollinvestition"].iloc[-1]
                        differenz = end_dk_test - end_vl_test
                        
                        if differenz > 0:
                            gewinner = "Dreikorb"
                            farbe = "#1f77b4"
                        elif differenz < 0:
                            gewinner = "Vollinvestition"
                            farbe = "#ff7f0e"
                        else:
                            gewinner = "Gleichstand"
                            farbe = "#808080"
                            
                        szenarien_ergebnisse.append({
                            "Startjahr": test_jahr,
                            "Gewinner": gewinner,
                            "Mehrwert der Gewinnerstrategie (€)": abs(differenz),
                            "Differenz_Plot": differenz, 
                            "Farbe": farbe
                        })
                
                df_szenarien = pd.DataFrame(szenarien_ergebnisse)
                
                if not df_szenarien.empty:
                    st.write("**Differenz am Laufzeitende (Balken nach Oben = Dreikorb gewinnt | Balken nach Unten = Vollinvestition gewinnt):**")
                    bar_chart = alt.Chart(df_szenarien).mark_bar().encode(
                        x=alt.X("Startjahr:O", title="Simulierter Rentenbeginn (Startjahr)"),
                        y=alt.Y("Differenz_Plot:Q", title="Vermögensdifferenz in €"),
                        color=alt.Color("Farbe:N", scale=None), 
                        tooltip=[
                            alt.Tooltip("Startjahr:O"),
                            alt.Tooltip("Gewinner:N"),
                            alt.Tooltip("Mehrwert der Gewinnerstrategie (€):Q", format=",.0f")
                        ]
                    ).interactive()
                    
                    st.altair_chart(bar_chart, use_container_width=True)
                    
                    siege_dk = len(df_szenarien[df_szenarien["Gewinner"] == "Dreikorb"])
                    siege_vl = len(df_szenarien[df_szenarien["Gewinner"] == "Vollinvestition"])
                    st.info(f"**Fazit der Simulationen ({erstes_jahr} bis {letztes_erlaubtes_jahr}):** Bei {len(df_szenarien)} getesteten historischen Startjahren war die **Dreikorbstrategie in {siege_dk} Fällen** am Ende überlegen, die **Vollinvestition in {siege_vl} Fällen**.")

# --- 9. README ---
st.divider()
with st.expander("📖 Erklärung lesen: Das Konzept & die Rebalancing-Logik", expanded=False):
    st.markdown("""
    ## 🧺 Das Konzept der Dreikorbstrategie
    Die Strategie teilt das Vermögen in drei Töpfe (Körbe) auf, um in schlechten Börsenphasen keine Aktien mit Verlust verkaufen zu müssen:
    * **Korb 1 (Cash / Tagesgeld):** Dient der kurzfristigen Liquidität. Hier liegt das Geld für die Entnahmen der nächsten Jahre.
    * **Korb 2 (Anleihen / Festgeld):** Mittelfristige Anlage. Bringt etwas mehr Zinsen als Korb 1 und dient als Puffer.
    * **Korb 3 (Aktien / ETFs):** Der Renditemotor. Hier liegt der größte Teil des Geldes langfristig investiert.

    ## 🔄 Rebalancing-Logik
    * **Börse steigt:** Rente wird aus Korb 3 (Aktien) entnommen (Gewinnmitnahme). Am Jahresende wird geprüft, ob K1 und K2 aufgefüllt werden müssen.
    * **Börse fällt:** Korb 3 wird geschont. Rente kommt aus Korb 1 (Cash). Ist dieser leer, aus Korb 2. Erst wenn K1 und K2 leer sind, droht ein Notverkauf aus Korb 3.
    """)
