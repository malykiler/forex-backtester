import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Forex Hedging Backtester", layout="wide")

st.title("📈 Forex Hedging Strategy Backtester")
st.caption("Model Niezależnych Pozycji: Otwieranie przeciwnika natychmiast po wygaśnięciu pojedynczej transakcji")

FOREX_PAIRS = [
    "USDJPY", "EURUSD", "AUDUSD", "GBPUSD", "USDCAD", "AUDCAD", 
    "AUDCHF", "AUDJPY", "CADJPY", "EURAUD", "CHFJPY", "EURCAD", 
    "EURJPY", "EURNZD", "GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", 
    "GBPNZD", "NZDCAD", "NZDJPY"
]

# --- TRWAŁE BUFOROWANIE ---
@st.cache_data(show_spinner=False)
def load_and_combine_ticks(files_dict_sorted, custom_spread_pips, use_custom, pip_sz):
    dfs = []
    for filename, file_bytes in files_dict_sorted.items():
        try:
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
                
            df['Bid'] = df['Bid'].astype(np.float32)
            df['Ask'] = df['Ask'].astype(np.float32)
            dfs.append(df[['Timestamp', 'Bid', 'Ask']].dropna())
        except Exception:
            continue
            
    if dfs:
        combined_df = pd.concat(dfs, ignore_index=True)
        return combined_df
    return None

# --- PANEL BOCZNY ---
st.sidebar.header("⚙️ Ustawienia Konta & Dźwigni")

uploaded_files = st.sidebar.file_uploader(
    "📁 Wgraj plik(i) CSV/DAT z tickami", 
    type=["csv", "txt", "dat"], 
    accept_multiple_files=True
)

if 'files_dict' not in st.session_state:
    st.session_state['files_dict'] = {}

if uploaded_files:
    for f in uploaded_files:
        st.session_state['files_dict'][f.name] = f.getvalue()

detected_pair = "USDJPY"
if st.session_state['files_dict']:
    first_name = list(st.session_state['files_dict'].keys())[0].upper()
    for pair in FOREX_PAIRS:
        if pair in first_name:
            detected_pair = pair
            break

selected_pair = st.sidebar.selectbox("💱 Wybrana para walutowa", FOREX_PAIRS, index=FOREX_PAIRS.index(detected_pair))

is_jpy = "JPY" in selected_pair
default_pip_size = 0.01 if is_jpy else 0.0001
default_pip_val = 6.11 if is_jpy else 10.00

capital = st.sidebar.number_input("Kapitał początkowy ($)", value=10000.0, step=500.0)
leverage = st.sidebar.selectbox("Dźwignia (Leverage)", [500, 200, 100, 30, 10], index=0)
base_lot = st.sidebar.number_input("Bazowa wielkość lota (1x)", value=0.01, step=0.01, format="%.2f")

max_lot_cap = st.sidebar.number_input("🛡️ Maksymalny limit lota", value=0.64, step=0.08, format="%.2f")
commission_per_lot = st.sidebar.number_input("💸 Prowizja / Opłata ($ na 1.0 lot)", value=7.00, step=0.50, format="%.2f")

tp_pips = st.sidebar.number_input("Take Profit (pips)", value=30.0, step=1.0)
sl_pips = st.sidebar.number_input("Stop Loss (pips)", value=25.0, step=1.0)
multiplier = st.sidebar.number_input("Mnożnik progresji", value=2.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.subheader("📐 Ustawienia Rynkowe z cTrader")
use_custom_spread = st.sidebar.checkbox("Użyj własnego spreadu z cTrader", value=True)
custom_spread_pips = st.sidebar.number_input("Własny spread (pips)", value=0.1, step=0.1, format="%.2f")

pip_size = st.sidebar.number_input("Wielkość 1 pipsa", value=default_pip_size, format="%.4f" if is_jpy else "%.5f")
pip_value_per_lot = st.sidebar.number_input("Wartość 1 pipsa / 1 lot ($)", value=default_pip_val, step=0.1)
margin_per_lot = st.sidebar.number_input("Wymagany depozyt dla 1.0 lota ($)", value=200.0, step=10.0)

# --- SILNIK SYMULACJI (INDIVIDUAL ASYNC POSITIONS) ---
def run_independent_positions_backtest(df, initial_capital, base_lot, max_lot_cap_val, comm_per_lot, tp_pips, sl_pips, multiplier, pip_val, pip_sz, margin_per_lot_val):
    tp_dist = tp_pips * pip_sz
    sl_dist = sl_pips * pip_sz
    
    balance = float(initial_capital)
    equity_curve = [balance]
    trades_history = []
    total_commission_paid = 0.0
    
    bids = df['Bid'].values
    asks = df['Ask'].values
    timestamps = df['Timestamp'].values
    
    pos_id_counter = 0
    
    # Inicjalizacja pierwszej, niezależnej pary startowej
    positions = [
        {'id': 1, 'type': 'BUY', 'lot': base_lot, 'tp': asks[0] + tp_dist, 'sl': asks[0] - sl_dist},
        {'id': 2, 'type': 'SELL', 'lot': base_lot, 'tp': bids[0] - tp_dist, 'sl': bids[0] + sl_dist}
    ]
    pos_id_counter = 2
    
    stop_out_occurred = False
    max_lot_used = base_lot
    
    for i in range(len(bids)):
        bid = bids[i]
        ask = asks[i]
        timestamp = timestamps[i]
        
        total_open_lots = sum(p['lot'] for p in positions)
        if total_open_lots > max_lot_used:
            max_lot_used = total_open_lots
            
        required_margin = total_open_lots * margin_per_lot_val
        
        if balance <= required_margin * 0.2:
            stop_out_occurred = True
            trades_history.append({
                'Timestamp': timestamp,
                'Type': 'STOP OUT',
                'Lot': total_open_lots,
                'Reason': 'BANKRUTWO',
                'PnL Czysty ($)': -balance,
                'Prowizja ($)': 0.0,
                'Balance': 0.0
            })
            equity_curve.append(0.0)
            break
            
        closed_this_tick = []
        
        # Sprawdzamy każdą otwartą pozycję z osobna
        for pos in positions:
            p_type = pos['type']
            lot = pos['lot']
            tp_p = pos['tp']
            sl_p = pos['sl']
            
            raw_pnl = 0.0
            closed = False
            reason = None
            
            if p_type == 'BUY':
                if bid >= tp_p:
                    raw_pnl = tp_pips * pip_val * lot
                    closed = True
                    reason = 'TP'
                elif bid <= sl_p:
                    raw_pnl = -sl_pips * pip_val * lot
                    closed = True
                    reason = 'SL'
            elif p_type == 'SELL':
                if ask <= tp_p:
                    raw_pnl = tp_pips * pip_val * lot
                    closed = True
                    reason = 'TP'
                elif ask >= sl_p:
                    raw_pnl = -sl_pips * pip_val * lot
                    closed = True
                    reason = 'SL'
                    
            if closed:
                comm = lot * comm_per_lot
                total_commission_paid += comm
                net_pnl = raw_pnl - comm
                balance += net_pnl
                closed_this_tick.append({'pos': pos, 'reason': reason, 'pnl': net_pnl})
                trades_history.append({
                    'Timestamp': timestamp,
                    'Type': p_type,
                    'Lot': lot,
                    'Reason': reason,
                    'PnL Czysty ($)': net_pnl,
                    'Prowizja ($)': comm,
                    'Balance': balance
                })
        
        # Jeśli jakakolwiek pozycja się zamknęła
        if closed_this_tick:
            equity_curve.append(balance)
            
            # Usuwamy tylko te pozycje, które się zamknęły
            closed_ids = [item['pos']['id'] for item in closed_this_tick]
            positions = [p for p in positions if p['id'] not in closed_ids]
            
            # Dla każdej zamkniętej pozycji otwieramy NOWĄ w PRZECIWNYM kierunku!
            for item in closed_this_tick:
                c_pos = item['pos']
                c_reason = item['reason']
                c_type = c_pos['type']
                c_lot = c_pos['lot']
                
                # Kierunek nowej pozycji jest PRZECIWNY do zamkniętej
                new_type = 'SELL' if c_type == 'BUY' else 'BUY'
                
                if c_reason == 'TP':
                    # Po TP nowa pozycja startuje z bazowym lotem
                    new_lot = base_lot
                else:
                    # Po SL nowa pozycja ma podwojonego lota (do limitu)
                    new_lot = min(c_lot * multiplier, max_lot_cap_val)
                    
                pos_id_counter += 1
                
                if new_type == 'BUY':
                    new_open = ask
                    new_tp = new_open + tp_dist
                    new_sl = new_open - sl_dist
                else:
                    new_open = bid
                    new_tp = new_open - tp_dist
                    new_sl = new_open + sl_dist
                    
                positions.append({
                    'id': pos_id_counter,
                    'type': new_type,
                    'lot': new_lot,
                    'tp': new_tp,
                    'sl': new_sl
                })

    return pd.DataFrame(trades_history), equity_curve, stop_out_occurred, max_lot_used, total_commission_paid

# --- INTERFEJS GŁÓWNY ---
if st.session_state['files_dict']:
    sorted_files = dict(sorted(st.session_state['files_dict'].items()))
    
    with st.spinner("Łączenie i przygotowywanie danych ze wszystkich plików..."):
        df = load_and_combine_ticks(
            sorted_files, 
            custom_spread_pips, 
            use_custom_spread, 
            pip_size
        )
    
    if df is not None and len(df) > 0:
        file_count = len(sorted_files)
        st.success(f"POŁĄCZONO {file_count} PLIKÓW! Ticków: **{len(df):,}**")
        
        estimated_profit = tp_pips * (pip_value_per_lot * base_lot)
        dep_base = margin_per_lot * base_lot
        
        st.info(f"📊 **Niezależny Hedging ({selected_pair}):** Depozyt ({base_lot:.2f} lot) = **${dep_base:.2f}** | Zysk TP ({tp_pips:.1f} pips) = **${estimated_profit:.2f}** | Limit Lota = **{max_lot_cap:.2f}**")
        
        if st.button("🚀 Uruchom Symulację"):
            with st.spinner(f"Symulacja w toku na {len(df):,} tickach..."):
                trades_df, equity_curve, stop_out, max_lot, total_comm = run_independent_positions_backtest(
                    df, capital, base_lot, max_lot_cap, commission_per_lot, tp_pips, sl_pips, multiplier, pip_value_per_lot, pip_size, margin_per_lot
                )
            
            st.subheader("📊 Wyniki Strategii ze Wszystkich Plików")
            
            if stop_out:
                st.error("⚠️ NASTĄPIŁ STOP OUT (BANKRUTWO KONTA)! Seria podwojeń przekroczyła wolny depozyt.")
            
            final_balance = equity_curve[-1]
            total_profit = final_balance - capital
            roi = (total_profit / capital) * 100
            
            tp_count = len(trades_df[trades_df['Reason'] == 'TP']) if not trades_df.empty else 0
            sl_count = len(trades_df[trades_df['Reason'] == 'SL']) if not trades_df.empty else 0
            
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Końcowy Kapitał", f"${final_balance:,.2f}")
            col2.metric("Zysk / Strata", f"${total_profit:,.2f}", f"{roi:.2f}%")
            col3.metric("Pobrane Prowizje", f"${total_comm:,.2f}")
            col4.metric("TP / SL (Liczba)", f"{tp_count} / {sl_count}")
            col5.metric("Największa Transakcja", f"{max_lot:.2f} lot")
            
            if len(equity_curve) > 2000:
                step = len(equity_curve) // 2000
                sampled_equity = equity_curve[::step]
            else:
                sampled_equity = equity_curve

            fig = go.Figure()
            fig.add_trace(go.Scatter(y=sampled_equity, mode='lines', name='Equity/Balance', line=dict(color='#00FF7F', width=2)))
            fig.update_layout(title=f"Krzywa Kapitału ({selected_pair} | Max Lot: {max_lot_cap})", xaxis_title="Zamknięcia transakcji", yaxis_title="Saldo ($)", template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("📋 Pełny Dziennik Transakcji")
            st.dataframe(trades_df, use_container_width=True)
else:
    st.info("👈 Wgraj pliki CSV z tickami w panelu po lewej stronie, aby rozpocząć symulację.")
