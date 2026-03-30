import streamlit as st
import pandas as pd
import yfinance as yf
import altair as alt
from datetime import datetime, timedelta
import io

# --- UI SETUP ---
st.set_page_config(page_title="Strategiecheck", layout="wide")
st.title("Vergleich: Dreikorb vs. Vollinvestition")

# --- 1. FUNKTIONEN ---
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
def lade_marktdaten(ticker, start_date):
    try:
        fetch_start = start_date - timedelta(days=500)
        raw = yf.download(
            ticker, 
            start=fetch_start, 
            interval="1mo", 
            progress=False
        )
        
        if raw.empty: 
            return pd.DataFrame()
            
        if isinstance(raw.columns, pd.MultiIndex):
            data = raw['Close'][ticker]
        else:
            data = raw['Close']
            
        data = data.dropna()
        annual = data.resample('YE').last()
        returns = annual.pct_change().dropna()
        
        df = pd.DataFrame({
            "Jahr": returns.index.year.astype(int), 
            "R_Dez": returns.values.astype(float)
        })
        
        df = df[df["Jahr"] >= start_date.year]
        
        max_jahr = int(df["Jahr"].max()) if not df.empty else start_date.year - 1
        akt_jahr = datetime.now().year
        
        if max_jahr < akt_jahr:
            ytd = (data.iloc[-1] / data[data.index.year == max_jahr].iloc[-1]) - 1
            y_v = float(ytd.iloc[0]) if hasattr(ytd, "__len__") else float(ytd)
            ytd_df = pd.DataFrame({
                "Jahr": [akt_jahr], 
                "R_Dez": [y_v]
            })
            df = pd.concat([df, ytd_df], ignore_index=True)
            
        return df.sort_values("Jahr")
    except Exception:
        return pd.DataFrame()

# --- 2. SIDEBAR ---
I_MAP = {
    "MSCI World": "URTH", 
    "S&P 500": "^GSPC", 
    "Nasdaq 100": "^NDX", 
    "DAX": "^GDAXI"
}

with st.sidebar:
    st.header("Parameter")
    idx_name = st.selectbox("Index", list(I_MAP.keys()))
    t_sym = I_MAP[idx_name]
    
    k1_s = st.number_input("K1 Bar", value=50000.0)
    k2_s = st.number_input("K2 Anl", value=100000.0)
    k3_s = st.number_input("K3 Akt", value=500000.0)
    
    s_dat = st.date_input("Startdatum", value=datetime(2012, 1, 1))
    n_monat = st.number_input("Netto Rente", value=2500)
    p_pct = st.slider("Gewinnanteil %", 0, 100, 30) / 100

# --- 3. EDITOR & SIMULATION ---
hist_df = lade_marktdaten(t_sym, s_dat)

if not hist_df.empty:
    hist_df["Rendite (%)"] = (hist_df["R_Dez"] * 100).round(2)
    hist_df["Jahr_Str"] = hist_df["Jahr"].astype(str)
    
    e_key = f"ed_v10_{t_sym}_{s_dat.year}"
    ed_df = st.data_editor(
        hist_df[["Jahr_Str", "Rendite (%)"]], 
        hide_index=True, 
        use_container_width=True, 
        key=e_key
    )
    
    if st.button("Simulation starten", type="primary"):
        k1 = k1_s
        k2 = k2_s
        k3 = k3_s
        k3_g = k3 * p_pct
        
        kv = k1_s + k2_s + k3_s
        kv_g = kv * p_pct
        
        m_3k = []
        m_v = []
        j_graf = []

        for _, row in ed_df.iterrows():
            jahr = row["Jahr_Str"]
            rj = float(row["Rendite (%)"]) / 100
            rm = (1 + rj)**(1/12) - 1
            
            for m in range(1, 13):
                k3_v = k3 * (1 + rm)
                k3_g += (k3_v - k3)
                k3 = k3_v
                
                kv_v = kv * (1 + rm)
                kv_g += (kv_v - kv)
                kv = kv_v
                
                b_m = 0.0
                s_m = 0.0
                q = ""
                
                if rj > 0:
                    gq = max(0.1, min(0.9, k3_g/k3)) if k3 > 0 else 0.5
                    b_m, s_m = berechne_brutto_und_steuer(n_monat, gq, True)
                    k3 -= b_m
                    k3_g -= (b_m * gq)
                    q = "K3 (Aktien)"
                else:
                    b_m, s_m = berechne_brutto_und_steuer(n_monat, 0.1, False)
                    if k1 >= b_m:
                        k1 -= b_m
                        q = "K1 (Cash)"
                    elif (k1 + k2) >= b_m:
                        rest = b_m - k1
                        k1 = 0
                        k2 -= rest
                        q = "K1 und K2"
                    else:
                        k3 -= b_m
                        q = "K3 (Notverkauf)"
                
                if m == 12 and rj > 0:
                    fehlbetrag = (k1_s - k1) + (k2_s - k2)
                    if fehlbetrag > 0:
                        gqf = max(0.1, min(0.9, k3_g/k3)) if k3 > 0 else 0.5
                        bf, _ = berechne_brutto_und_steuer(fehlbetrag, gqf, True)
                        k3 -= bf
                        k3_g -= (bf * gqf)
                        k1 = k1_s
                        k2 = k2_s
                        q += " + Auffuellen"
                
                gv = max(0.1, min(0.9, kv_g/kv)) if kv > 0 else 0.5
                bv, sv = berechne_brutto_und_steuer(n_monat, gv, True)
                kv -= bv
                kv_g -= (bv * gv)
                
                m_3k.append({
                    "Jahr": jahr,
                    "Monat": m,
                    "Index_Rendite": f"{rm:.4%}",
                    "Depot_Vor_Entnahme": round(k3_v, 2),
                    "Netto_Entnahme": n_monat,
                    "Steuer_Gezahlt": s_m,
                    "Brutto_Entnahme": b_m,
                    "Entnahme_Topf": q,
                    "Bestand_K1": round(k1, 2),
                    "Bestand_K2": round(k2, 2),
                    "Bestand_K3": round(k3, 2),
                    "Gesamtvermoegen": round(k1+k2+k3, 2)
                })
                
                m_v.append({
                    "Jahr": jahr,
                    "Monat": m,
                    "Index_Rendite": f"{rm:.4%}",
                    "Depot_Vor_Entnahme": round(kv_v, 2),
                    "Netto_Entnahme": n_monat,
                    "Steuer_Gezahlt": sv,
                    "Brutto_Entnahme": bv,
                    "Gesamtvermoegen": round(kv, 2)
                })
                
            j_graf.append({
                "Jahr": jahr,
                "Jahr_Int": int(jahr),
                "Dreikorb": round(k1+k2+k3),
                "Vollinvestition": round(kv),
                "Aktion": q,
                "Rendite": f"{rj:.2%}"
            })

        # Daten in Session State speichern, damit der Download-Button nicht verschwindet
        st.session_state["m_3k"] = m_3k
        st.session_state["m_v"] = m_v
        st.session_state["j_graf"] = j_graf
        st.session_state["sim_berechnet"] = True

    # --- 4. ANZEIGE DER ERGEBNISSE & DOWNLOAD ---
    if st.session_state.get("sim_berechnet", False):
        
        # Daten aus dem Cache holen
        df_plot = pd.DataFrame(st.session_state["j_graf"])
        df_plot["DK_Euro"] = df_plot["Dreikorb"].map('{:,.0f} €'.format)
        df_plot["VL_Euro"] = df_plot["Vollinvestition"].map('{:,.0f} €'.format)
        
        st.divider()
        st.subheader("Strategievergleich (Mouseover fuer Details)")
        
        # Grafik mit Mouseover
        selector = alt.selection_point(
            fields=['Jahr_Int'], 
            nearest=True, 
            on='mouseover', 
            empty=False
        )
        
        base_chart = alt.Chart(df_plot).encode(
            x=alt.X('Jahr_Int:O', title='Jahr')
        )
        
        line_dk = base_chart.mark_line(size=3, color='#1f77b4').encode(
            y=alt.Y('Dreikorb:Q', title='Vermoegen')
        )
        
        line_vl = base_chart.mark_line(
            size=3, 
            color='#ff7f0e', 
            strokeDash=[5,5]
        ).encode(
            y='Vollinvestition:Q'
        )
        
        tooltip_liste = [
            alt.Tooltip('Jahr:N', title='Jahr'),
            alt.Tooltip('Rendite:N', title='Rendite'),
            alt.Tooltip('DK_Euro:N', title='Wert Dreikorb'),
            alt.Tooltip('VL_Euro:N', title='Wert Vollinvest'),
            alt.Tooltip('Aktion:N', title='Aktion')
        ]
        
        points = base_chart.mark_point(
            size=100, 
            opacity=0
        ).encode(
            y='Dreikorb:Q',
            tooltip=tooltip_liste
        ).add_params(selector)
        
        st.altair_chart(line_dk + line_vl + points, use_container_width=True)

        # Excel generieren
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            pd.DataFrame(st.session_state["m_3k"]).to_excel(
                writer, 
                index=False, 
                sheet_name='Dreikorb_Details'
            )
            pd.DataFrame(st.session_state["m_v"]).to_excel(
                writer, 
                index=False, 
                sheet_name='Vollinvestition'
            )
        
        # Dauerhafter Download Button
        st.success("Simulation erfolgreich! Lade hier die Detail-Daten herunter:")
        st.download_button(
            label="📥 Excel-Details herunterladen", 
            data=excel_buffer.getvalue(), 
            file_name="Simulation_Details.xlsx", 
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        # Tabelle anzeigen
        spalten = ["Jahr", "Dreikorb", "Vollinvestition", "Aktion", "Rendite"]
        st.dataframe(
            df_plot[spalten].set_index("Jahr"), 
            use_container_width=True
        )

else:
    st.info("Lade Daten...")