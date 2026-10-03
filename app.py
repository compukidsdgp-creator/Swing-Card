"""SwingScope 21-Day Batch Tracker — Streamlit entry point.

Run:  streamlit run app.py
Pages:
  📡 Live dashboard  — read-only, 24x7: live prices in market hours + 21-day performance + research & sentiment
  🛠 Manage & update — upload batches, update prices, edit research, downloads, Telegram
"""
import streamlit as st

st.set_page_config(page_title="SwingScope Live", page_icon="📈", layout="wide")

pg = st.navigation([
    st.Page("views/live.py", title="Live dashboard", icon="📡", default=True),
    st.Page("views/manage.py", title="Manage & update", icon="🛠"),
])
pg.run()
