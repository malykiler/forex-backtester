import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Forex Hedging Backtester", layout="wide")

st.title("📈 Forex Hedging Strategy Backtester")
st.caption("Symulator strategii z Dźwignią 1:500 i trwałym zapisem pliku w pamięci")

FOREX_PAIRS = [
    "USDJPY", "EURUSD", "AUDUSD", "GBPUSD", "USDCAD", "AUDCAD", 
    "AUDCHF", "AUDJPY", "CADJPY", "EURAUD", "CHFJPY", "EURCAD", 
    "EURJPY", "EURNZD", "GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", 
    "GBPNZD", "NZDCAD", "NZDJPY"
]

# --- TRWAŁE BUFOROWANIE DANYCH TICKOWYCH ---
@st.cache_data(show_spinner=False)
def load_and_parse_ticks(file_bytes, filename, custom_spread_pips, use_custom, pip_sz):
    try:
        import io
        uploaded_file = io.BytesIO(file_bytes)
        sample = uploaded_file.read(2048).decode('utf-8', errors='ignore')
        uploaded_file.seek(0)
        sep = ';' if ';' in sample else (',' if ',' in sample else '\t')
        
        df = pd.read_csv(uploaded_file, sep=sep, header=None, engine='python')
        
        if len(df.columns) >= 3 and isinstance(df.iloc[0, 1], (int, float, np.number)):
            df = df.rename(columns={0: 'Timestamp', 1: 'Bid', 2: 'Ask'})
        elif len(df.columns) >= 2 and isinstance(df.iloc[0, 1], (int, float, np.number)):
            df = df.rename(columns={0: 'Timestamp', 1: 'Bid'})
            df['Ask'] = df['Bid'] + (custom_spread_pips * pip_sz)
        else:
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, sep=sep, engine='python')
            col_map = {}
            for c in df.columns:
                cl = str(c).lower()
                if 'bid' in cl or 'close' in cl or 'price' in cl:
                    col_map[c] = 'Bid'
                elif 'ask' in cl:
                    col_map[c] = 'Ask'
                elif 'date' in cl or 'time' in cl:
                    col_map[c] = 'Timestamp'
            df = df.rename(columns=col_map)

        if use_custom or 'Ask' not in df.columns:
            df['Ask'] = df['Bid'] + (custom_spread_pips * pip_sz)
            
        return df[['Timestamp', 'Bid', 'Ask']].dropna()
    except Exception as e:
        return None

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Ustawienia Konta & Dźwigni")

uploaded_file = st.sidebar.file_uploader("📁 Wgraj plik CSV/DAT z tickami", type=["csv", "txt", "dat"])

# Przechowywanie danych w sesji
if uploaded_file is not None:
    file_bytes = uploaded_file.getvalue()
    st.session_state['file_bytes'] = file_bytes
    st.session_state['filename'] = uploaded_file.name

detected_pair = "USDJPY"
if 'filename' in st.session_state:
    current_name = st.session_state['filename'].upper()
    for pair in FOREX_PAIRS:
        if pair in current_name:
            detected_pair = pair
            break

selected_pair = st.sidebar.selectbox("💱 Wybrana para walutowa", FOREX_PAIRS, index=FOREX_PAIRS.index(detected_pair))

is_jpy = "JPY" in selected_pair
default_pip_size = 0.01 if is_jpy else 0.0001
default_pip_val = 6.11 if is_jpy else 10.00

capital = st.sidebar.number_input("Kapitał początkowy ($)", value=10000.0, step=500.0)
leverage = st.sidebar.selectbox("Dźwignia (Leverage)", [500, 200, 100, 30, 10], index=0)
base_lot = st.sidebar.number_input("Bazowa wielkość lota (1x)", value=0.01, step=0.01, format="%.2f")
tp_pips = st.sidebar.number_input("Take Profit (pips)", value=25.0, step=1.0)
sl_pips = st.sidebar.number_input("Stop Loss (pips)", value=20.0, step=1.0)
multiplier = st.sidebar.number_input("Mnożnik progresji", value=2.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.subheader("📐 Ustawienia Rynkowe z cTrader")
use_custom_spread = st.sidebar.checkbox("Użyj własnego spreadu z cTrader (np. 0.1 pipsa)", value=True)
custom_spread_pips = st.sidebar.number_input("Własny spread (pips)", value=0.1, step=0.1, format="%.2f")

pip_size = st.sidebar.number_input("Wielkość 1 pipsa", value=default_pip_size, format="%.4f" if is_jpy else "%.5f")
pip_value_per_lot = st.sidebar.number_input("Wartość 1 pipsa / 1 lot ($)", value=default_pip_val, step=0.1)
margin_per_lot = st.sidebar.number_input("Wymagany depozyt dla 1.0 lota ($)", value=200.0, step=10.0)

# --- SILNIK SYMULACJI ---
def run_backtest(df, initial_capital, base_lot, tp_pips, sl_pips, multiplier, pip_val, pip_sz, margin_per_lot_val):
    tp_dist = tp_pips * pip_sz
    sl_dist = sl_pips * pip_sz
    
    balance = initial_capital
    equity_curve = [initial_capital]
    trades_history = []
    
    next_buy_lot = base_lot
    next_sell_lot = base_lot
    
    current_bid = df['Bid'].iloc[0]
    current_ask = df['Ask'].iloc[0]
    
    positions = [
        {'id': 1, 'type': 'BUY', 'lot': next_buy_lot, 'open': current_ask, 'tp': current_ask + tp_dist, 'sl': current_ask - sl_dist},
        {'id': 2, 'type': 'SELL', 'lot': next_sell_lot, 'open': current_bid, 'tp': current_bid - tp_dist, 'sl': current_bid + sl_dist}
    ]
    
    pos_counter = 2
    stop_out_occurred = False
    
    for idx, row in df.iterrows():
        bid = row['Bid']
        ask = row['Ask']
        timestamp = row['Timestamp']
        
        total_open_lots = sum(p['lot'] for p in positions)
        required_margin = total_open_lots * margin_per_lot_val
        
        if balance <= required_margin * 0.2:
            stop_out_occurred = True
            trades_history.append({
                'Timestamp': timestamp,
                'Type': 'STOP OUT',
                'Lot': total_open_lots,
                'Reason': 'BANKRUTWO',
                'PnL ($)': -balance,
                'Balance': 0.0
            })
            equity_curve.append(0.0)
            break
            
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
            
            closed_ids = [item['pos']['id'] for item in closed_this_tick]
            positions = [p for p in positions if p['id'] not in closed_ids]
            
            if len(closed_this_tick) == 2:
                r1, r2 = closed_this_tick[0]['reason'], closed_this_tick[1]['reason']
                if r1 == 'TP' and r2 == 'TP':
                    next_buy_lot = base_lot
                    next_sell_lot = base_lot
                elif r1 == 'SL' and r2 == 'SL':
                    old_buy = next_buy_lot
                    old_sell = next_sell_lot
                    next_buy_lot = old_sell * multiplier
                    next_sell_lot = old_buy * multiplier
                
                pos_counter += 1
                positions.append({'id': pos_counter, 'type': 'BUY', 'lot': next_buy_lot, 'open': ask, 'tp': ask + tp_dist, 'sl': ask - sl_dist})
                pos_counter += 1
                positions.append({'id': pos_counter, 'type': 'SELL', 'lot': next_sell_lot, 'open': bid, 'tp': bid - tp_dist, 'sl': bid + sl_dist})
            else:
                item = closed_this_tick[0]
                p_type = item['pos']['type']
                reason = item['reason']
                closed_lot = item['pos']['lot']
                
                if reason == 'TP':
                    if p_type == 'BUY':
                        next_buy_lot = base_lot
                        pos_counter += 1
                        positions.append({'id': pos_counter, 'type': 'BUY', 'lot': next_buy_lot, 'open': ask, 'tp': ask + tp_dist, 'sl': ask - sl_dist})
                    else:
                        next_sell_lot = base_lot
                        pos_counter += 1
                        positions.append({'id': pos_counter, 'type': 'SELL', 'lot': next_sell_lot, 'open': bid, 'tp': bid - tp_dist, 'sl': bid + sl_dist})
                elif reason == 'SL':
                    if p_type == 'BUY':
                        next_sell_lot = closed_lot * multiplier
                        pos_counter += 1
                        positions.append({'id': pos_counter, 'type': 'SELL', 'lot': next_sell_lot, 'open': bid, 'tp': bid - tp_dist, 'sl': bid + sl_dist})
                    else:
                        next_buy_lot = closed_lot * multiplier
                        pos_counter += 1
                        positions.append({'id': pos_counter, 'type': 'BUY', 'lot': next_buy_lot, 'open': ask, 'tp': ask + tp_dist, 'sl': ask - sl_dist})

    return pd.DataFrame(trades_history), equity_curve, stop_out_occurred

# --- INTERFEJS GŁÓWNY ---
if 'file_bytes' in st.session_state:
    df = load_and_parse_ticks(
        st.session_state['file_bytes'], 
        st.session_state['filename'], 
        custom_spread_pips, 
        use_custom_spread, 
        pip_size
    )
    
    if df is not None and len(df) > 0:
        st.success(f"DANE ZAPAMIĘTANE W PAMIĘCI! Plik: **{st.session_state['filename']}** | Ticków: **{len(df):,}**")
        
        estimated_profit_001 = 25.0 * (pip_value_per_lot * 0.01)
        dep_001 = margin_per_lot * 0.01
        
        st.info(f"📊 Parametry cTrader ({selected_pair}): Depozyt 0.01 lota = **${dep_001:.2f}** | Zysk z TP 25 pips = **${estimated_profit_001:.2f}**")
        
        if st.button("🚀 Uruchom Symulację"):
            with st.spinner("Przetwarzanie danych..."):
                trades_df, equity_curve, stop_out = run_backtest(
                    df, capital, base_lot, tp_pips, sl_pips, multiplier, pip_value_per_lot, pip_size, margin_per_lot
                )
            
            st.subheader("📊 Wyniki Strategii")
            
            if stop_out:
                st.error("⚠️ NASTĄPIŁ STOP OUT (BANKRUTWO KONTA)! Seria podwojeń przekroczyła wolny depozyt.")
            
            final_balance = equity_curve[-1]
            total_profit = final_balance - capital
            roi = (total_profit / capital) * 100
            
            tp_count = len(trades_df[trades_df['Reason'] == 'TP']) if not trades_df.empty else 0
            sl_count = len(trades_df[trades_df['Reason'] == 'SL']) if not trades_df.empty else 0
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Końcowy Kapitał", f"${final_balance:,.2f}")
            col2.metric("Zysk / Strata", f"${total_profit:,.2f}", f"{roi:.2f}%")
            col3.metric("Liczba TP", tp_count)
            col4.metric("Liczba SL", sl_count)
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(y=equity_curve, mode='lines', name='Equity/Balance', line=dict(color='#00FF7F', width=2)))
            fig.update_layout(title=f"Krzywa Kapitału ({selected_pair} | 1:{leverage})", xaxis_title="Zamknięcia transakcji", yaxis_title="Saldo ($)", template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("📋 Dziennik Zamkniętych Transakcji")
            st.dataframe(trades_df, use_container_width=True)
else:
    st.info("👈 Wgraj plik CSV z tickami z panelu po lewej stronie, aby rozpocząć symulację.")
