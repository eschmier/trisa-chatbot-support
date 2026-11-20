"""Entry point. Sets the page name and menu labels; the chat itself is in chat_page.py."""
import streamlit as st

st.set_page_config(page_title="TRISA Support Assistant", page_icon=":speech_balloon:")

pages = [st.Page("chat_page.py", title="TRISA Support Assistant", icon=":material/chat:", default=True),
         st.Page("pages/1_Staff.py", title="Staff", icon=":material/badge:", url_path="Staff")]
st.navigation(pages).run()
