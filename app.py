import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# --- KONFIGURACJA STRONY (ZOPTYMALIZOWANA POD TELEFON) ---
st.set_page_config(page_title="Forex Hedging Backtester", layout="wide")

st.title("📈 Forex Hedging Strategy Backtester")
st.caption("Symulator strategii hedgingowej z progresją na danych tickowych")

# --- PANEL BOCZNY / PARAMETRY WEJŚCIOWE ---
st.sidebar.header("⚙️ Parametry Strategii")

capital = st.sidebar.number_input("Kapitał początkowy ($)", value=10000.0, step=500.0)
base_lot = st.sidebar.number_input("Bazowa wielkość lota (1x)", value=0.01, step=0.01, format="%.2f")
tp_pips = st.sidebar.number_input("Take Profit (pips)", value=25.0, step=1.0)
sl_pips = st.sidebar.number_input("Stop Loss (pips)", value=20.0, step=1.0)
multiplier = st.sidebar.number_input("Mnożnik progresji", value=2.0, step=0.5)
pip_value_per_lot = st.sidebar.number_input("Wartość 1 pipsa dla 1.0 lota ($)", value=10.0, step=1.0)
pip_size = st.sidebar.number_input("Wielkość pipsa (np. 0.0001 dla EURUSD)", value=0.0001, format="%.5f")

st.sidebar.header("📁 Dane Historyczne")
uploaded_file = st.sidebar.file_uploader("Wgraj plik CSV z tickami", type=["csv"])

# --- SILNIK SYMULACJI ---
def run_backtest(df, initial_capital, base_lot, tp_pips, sl_pips, multiplier, pip_val, pip_sz):
    # Konwersja pipsów na dystans cenowy
    tp_dist = tp_pips * pip_sz
    sl_dist = sl_pips * pip_sz
    
    # Stan konta
    balance = initial_capital
    equity = initial_capital
    
    # Historia do wykresu i raportów
    equity_curve = [initial_capital]
    trades_history = []
    
    # Aktualne pozycje: [typ, lot, price_open, tp_price, sl_price]
    # Domyślnie startujemy od 1x BUY + 1x SELL
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
            open_p = pos['open']
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
        
        # Jeśli zamknęła się przynajmniej jedna pozycja, aktualizujemy stan i otwieramy nowe
        if closed_this_tick:
            # Rejestrujemy stan bilansu
            equity_curve.append(balance)
            
            # Określamy co się stało
            reasons = [item['reason'] for item in closed_this_tick]
            
            # Jeśli obie pozycje zamknęły się w tym samym ticku
            if len(closed_this_tick) == 2:
                if all(r == 'TP' for r in reasons):
                    # Obie na TP -> Start od nowa (1:1)
                    buy_lots = base_lot
                    sell_lots = base_lot
                elif all(r == 'SL' for r in reasons):
                    # Obie na SL -> Zmieniamy strony i podwajamy obie!
                    new_buy_lots = sell_lots * multiplier
                    new_sell_lots = buy_lots * multiplier
                    buy_lots = new_buy_lots
                    sell_lots = new_sell_lots
            else:
                # Tylko jedna pozycja się zamknęła
                item = closed_this_tick[0]
                p_type = item['pos']['type']
                reason = item['reason']
                closed_lot = item['pos']['lot']
                
                if p_type == 'BUY':
                    if reason == 'TP':
                        # BUY trafił TP -> reset pozycji BUY na bazową
                        buy_lots = base_lot
                    else:
                        # BUY trafił SL -> podwajamy i zmieniamy na SELL
                        sell_lots += closed_lot * multiplier
                elif p_type == 'SELL':
                    if reason == 'TP':
                        # SELL trafił TP -> reset pozycji SELL na bazową
                        sell_lots = base_lot
                    else:
                        # SELL trafił SL -> podwajamy i zmieniamy na BUY
                        buy_lots += closed_lot * multiplier

            # Otwieramy nowe pozycje z zaktualizowanymi lotami
            positions = [
                {'type': 'BUY', 'lot': buy_lots, 'open': bid, 'tp': bid + tp_dist, 'sl': bid - sl_dist},
                {'type': 'SELL', 'lot': sell_lots, 'open': bid, 'tp': bid - tp_dist, 'sl': bid + sl_dist}
            ]

    return pd.DataFrame(trades_history), equity_curve

# --- MAIN APP INTERFACE ---
if uploaded_file is not None:
    st.success("Plik CSV załadowany pomyślnie!")
    df = pd.read_csv(uploaded_file)
    
    # Prosta weryfikacja kolumn
    if 'Bid' not in df.columns:
        st.error("Plik CSV musi zawierać kolumnę 'Bid'!")
    else:
        st.write(f"Liczba załadowanych ticków: **{len(df):,}**")
        
        if st.button("🚀 Uruchom Symulację"):
            with st.spinner("Przetwarzanie danych tickowych..."):
                trades_df, equity_curve = run_backtest(
                    df, capital, base_lot, tp_pips, sl_pips, multiplier, pip_value_per_lot, pip_size
                )
            
            # --- WYNIKI SYMULACJI ---
            st.subheader("📊 Wyniki Strategii")
            
            final_balance = equity_curve[-1]
            total_profit = final_balance - capital
            roi = (total_profit / capital) * 100
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Końcowy Kapitał", f"${final_balance:,.2f}")
            col2.metric("Zysk / Strata", f"${total_profit:,.2f}", f"{roi:.2f}%")
            col3.metric("Liczba Zamkniętych Transakcji", len(trades_df))
            
            # Wykres kapitału
            fig = go.Figure()
            fig.add_trace(go.Scatter(y=equity_curve, mode='lines', name='Equity/Balance', line=dict(color='#00FF7F', width=2)))
            fig.update_layout(title="Krzywa Kapitału w Czasie", xaxis_title="Liczba zamknięć", yaxis_title="Saldo ($)", template="plotly_dark")
            st.plotly_chart(fig, use_container_width=True)
            
            # Tabela transakcji
            st.subheader("📋 Dziennik Transakcji")
            st.dataframe(trades_df.style.highlight_max(axis=0, color='#1e3d2f'), use_container_width=True)
else:
    st.info("👈 Wgraj plik CSV z tickami z panelu po lewej stronie, aby rozpocząć symulację.")
