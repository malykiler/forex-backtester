import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import re

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Forex Hedging Backtester", layout="wide")

st.title("📈 Forex Hedging Strategy Backtester")
st.caption("Symulator strategii hedgingowej z progresją na danych tickowych")

# --- LISTA PAR WALUTOWYCH Z CTRADER ---
FOREX_PAIRS = [
    "EURUSD", "AUDUSD", "GBPUSD", "USDCAD", "USDJPY", "AUDCAD", 
    "AUDCHF", "AUDJPY", "CADJPY", "EURAUD", "CHFJPY", "EURCAD", 
    "EURJPY", "EURNZD", "GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", 
    "GBPNZD", "NZDCAD", "NZDJPY"
]

# --- PANEL BOCZNY / PARAMETRY WEJŚCIOWE ---
st.sidebar.header("⚙️ Parametry Strategii")

# Auto-wykrywanie z nazwy pliku lub ręczny wybór pary
uploaded_file = st.sidebar.file_uploader("📁 Wgraj plik CSV z tickami", type=["csv", "txt"])

detected_pair = "EURUSD"
if uploaded_file is not None:
    filename = uploaded_file.name.upper()
    for pair in FOREX_PAIRS:
        if pair in filename:
            detected_pair = pair
            break

selected_pair = st.sidebar.selectbox("💱 Wybrana para walutowa", FOREX_PAIRS, index=FOREX_PAIRS.index(detected_pair))

# Automatyczne ustawienie pipsa na podstawie pary JPY vs non-JPY
is_jpy = "JPY" in selected_pair
default_pip_size = 0.01 if is_jpy else 0.0001
default_pip_val = 6.50 if is_jpy else 10.00  # Szacunkowa wartość 1 pipsa dla 1.0 lota w USD

capital = st.sidebar.number_input("Kapitał początkowy ($)", value=10000.0, step=500.0)
base_lot = st.sidebar.number_input("Bazowa wielkość lota (1x)", value=0.01, step=0.01, format="%.2f")
tp_pips = st.sidebar.number_input("Take Profit (pips)", value=25.0, step=1.0)
sl_pips = st.sidebar.number_input("Stop Loss (pips)", value=20.0, step=1.0)
multiplier = st.sidebar.number_input("Mnożnik progresji", value=2.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.caption("🔧 Automatyczne ustawienia wymiaru pipsa")
pip_size = st.sidebar.number_input("Wielkość pipsa", value=default_pip_size, format="%.4f" if is_jpy else "%.5f")
pip_value_per_lot = st.sidebar.number_input("Wartość 1 pipsa / 1 lot ($)", value=default_pip_val, step=0.5)

# --- SILNIK SYMULACJI ---
def run_backtest(df, initial_capital, base_lot, tp_pips, sl_pips, multiplier, pip_val, pip_sz):
    tp_dist = tp_pips * pip_sz
    sl_dist = sl_pips * pip_sz
    
    balance = initial_capital
    equity_curve = [initial_capital]
    trades_history = []
    
    buy_lots = base_lot
    sell_lots = base_lot
    
    current_bid = df['Bid'].iloc[0]
    
    positions = [
        {'type': 'BUY', 'lot': buy_lots, 'open': current_bid, 'tp': current_bid + tp_dist, 'sl': current_bid - sl_dist},
        {'type': 'SELL', 'lot': sell_lots, 'open': current_bid, 'tp': current_bid - tp_dist, 'sl': current_bid + sl_dist}
    ]
    
    for idx, row in df.iterrows():
        bid = row['Bid']
        ask = row.get('Ask', bid)
        timestamp = row.get('Timestamp', idx)
        
        closed_this_tick = []
        
        for pos in positions:
            p_type = pos['type']
            lot = pos['lot']
            tp_p = pos['tp']
            sl_p = pos['sl']
            
            pnl = 0.0
            closed = False
            reason = None
            
            if p_type == 'BUY':
                if bid >= tp_p:
                    pnl = tp_pips * pip_val * lot
                    closed = True
                    reason = 'TP'
                elif bid <= sl_p:
                    pnl = -sl_pips * pip_val * lot
                    closed = True
                    reason = 'SL'
            elif p_type == 'SELL':
                if ask <= tp_p:
                    pnl = tp_pips * pip_val * lot
                    closed = True
                    reason = 'TP'
                elif ask >= sl_p:
                    pnl = -sl_pips * pip_val * lot
                    closed = True
                    reason = 'SL'
                    
            if closed:
                balance += pnl
                closed_this_tick.append({'pos': pos, 'reason': reason, 'pnl': pnl})
                trades_history.append({
                    'Timestamp': timestamp,
                    'Type': p_type,
                    'Lot': lot,
                    'Reason': reason,
                    'PnL ($)': pnl,
                    'Balance': balance
                })
        
        if closed_this_tick:
            equity_curve.append(balance)
            reasons = [item['reason'] for item in closed_this_tick]
            
            if len(closed_this_tick) == 2:
                if all(r == 'TP' for r in reasons):
                    buy_lots = base_lot
                    sell_lots = base_lot
                elif all(r == 'SL' for r in reasons):
                    new_buy_lots = sell_lots * multiplier
                    new_sell_lots = buy_lots * multiplier
                    buy_lots = new_buy_lots
                    sell_lots = new_sell_lots
            else:
                item = closed_this_tick[0]
                p_type = item['pos']['type']
                reason = item['reason']
                closed_lot = item['pos']['lot']
                
                if p_type == 'BUY':
                    if reason == 'TP':
                        buy_lots = base_lot
                    else:
                        sell_lots += closed_lot * multiplier
                elif p_type == 'SELL':
                    if reason == 'TP':
                        sell_lots = base_lot
                    else:
                        buy_lots += closed_lot * multiplier

            positions = [
                {'type': 'BUY', 'lot': buy_lots, 'open': bid, 'tp': bid + tp_dist, 'sl': bid - sl_dist},
                {'type': 'SELL', 'lot': sell_lots, 'open': bid, 'tp': bid - tp_dist, 'sl': bid + sl_dist}
            ]

    return pd.DataFrame(trades_history), equity_curve

# --- FUNKCJA PARSUJĄCA ELASTYCZNIE PLIK CSV ---
def parse_csv_file(uploaded_file):
    try:
        df = pd.read_csv(uploaded_file, sep=None, engine='python', nrows=100)
        uploaded_file.seek(0)
        
        # Sprawdzanie braku nagłówków
        if not any(isinstance(col, str) and any(kw in str(col).lower() for kw in ['bid', 'ask', 'price', 'close', 'date', 'time']) for col in df.columns):
            df = pd.read_csv(uploaded_file, sep=None, engine='python', header=None)
            num_cols = df.select_dtypes(include=[np.number]).columns
            if len(num_cols) >= 1:
                df = df.rename(columns={num_cols[0]: 'Bid'})
                if len(num_cols) >= 2:
                    df = df.rename(columns={num_cols[1]: 'Ask'})
        else:
            df = pd.read_csv(uploaded_file, sep=None, engine='python')
            col_map = {}
            for col in df.columns:
                col_lower = str(col).lower()
                if 'bid' in col_lower or 'price' in col_lower or 'close' in col_lower:
                    col_map[col] = 'Bid'
                elif 'ask' in col_lower:
                    col_map[col] = 'Ask'
                elif 'date' in col_lower or 'time' in col_lower or 'timestamp' in col_lower:
                    col_map[col] = 'Timestamp'
            df = df.rename(columns=col_map)
            
        return df
    except Exception as e:
        st.error(f"Błąd odczytu pliku CSV: {e}")
        return None

# --- INTERFEJS GŁÓWNY ---
if uploaded_file is not None:
    st.success(f"Plik CSV załadowany! Wykryta/wybrana para: **{selected_pair}**")
    df = parse_csv_file(uploaded_file)
    
    if df is not None and 'Bid' in df.columns:
        st.write(f"Liczba załadowanych wierszy: **{len(df):,}**")
        st.write("Podgląd początkowych ticków:")
        st.dataframe(df.head(3), use_container_width=True)
        
        if st.button("🚀 Uruchom Symulację"):
            with st.spinner("Przetwarzanie danych tickowych..."):
                trades_df, equity_curve = run_backtest(
                    df, capital, base_lot, tp_pips, sl_pips, multiplier, pip_value_per_lot, pip_size
                )
            
            st.subheader("📊 Wyniki Strategii")
            
            final_balance = equity_curve[-1]
            total_profit = final_balance - capital
            roi = (total_profit / capital) * 100
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Końcowy Kapitał", f"${final_balance:,.2f}")
            col2.metric("Zysk / Strata", f"${total_profit:,.2f}", f"{roi:.2f}%")
            col3.metric("Liczba Zamkniętych Transakcji", len(trades_df))
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(y=equity_curve, mode='lines', name='Equity/Balance', line=dict(color='#00FF7F', width=2)))
            fig.update_layout(title=f"Krzywa Kapitału ({selected_pair})", xaxis_title="Liczba zamknięć", yaxis_title="Saldo ($)", template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("📋 Dziennik Transakcji")
            st.dataframe(trades_df.style.highlight_max(axis=0, color='#1e3d2f'), use_container_width=True)
    else:
        st.error("Nie udało się odczytać kolumny cenowej ('Bid'). Sprawdź strukturę pliku.")
else:
    st.info("👈 Wgraj plik CSV z tickami z panelu po lewej stronie, aby rozpocząć symulację.")
