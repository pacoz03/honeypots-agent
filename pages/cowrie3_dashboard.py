import streamlit as st
import pandas as pd
import json
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
from collections import Counter
import re

# Configurazione della pagina
st.set_page_config(
    page_title="Cowrie3 Dashboard",
    page_icon="⚡",
    layout="wide"
)

# Titolo della dashboard
st.title("⚡ Cowrie3 Honeypot Dashboard")
st.markdown("---")

# Funzione per leggere e parsare i log JSON
@st.cache_data
def load_cowrie_logs():
    log_file = "honeypots/cowrie3/log/cowrie.json"
    logs = []
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    log_entry = json.loads(line.strip())
                    logs.append(log_entry)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        st.error(f"File di log non trovato: {log_file}")
        return []
    
    return logs

# Caricamento dei log
logs = load_cowrie_logs()

if not logs:
    st.warning("Nessun log trovato per Cowrie3")
    st.stop()

# Converti in DataFrame
df = pd.DataFrame(logs)

# Converti timestamp in datetime
df['timestamp'] = pd.to_datetime(df['timestamp'])
df['date'] = df['timestamp'].dt.date
df['hour'] = df['timestamp'].dt.hour

# Sidebar con filtri
st.sidebar.header("Filtri")

# Filtro per tipo di evento
event_types = sorted(df['eventid'].unique())
selected_events = st.sidebar.multiselect(
    "Seleziona tipi di evento:",
    event_types,
    default=event_types
)

# Filtro per data
date_range = st.sidebar.date_input(
    "Intervallo date:",
    value=(df['timestamp'].min().date(), df['timestamp'].max().date())
)

# Filtro per IP sorgente
ip_addresses = sorted(df['src_ip'].dropna().unique())
selected_ips = st.sidebar.multiselect(
    "Filtra per IP sorgente:",
    ip_addresses,
    default=ip_addresses
)

# Applica filtri
filtered_df = df[
    (df['eventid'].isin(selected_events)) &
    (df['timestamp'].dt.date >= date_range[0]) &
    (df['timestamp'].dt.date <= date_range[1]) &
    (df['src_ip'].isin(selected_ips) if selected_ips else True)
]

# Statistiche generali
col1, col2, col3, col4 = st.columns(4)

with col1:
    total_events = len(filtered_df)
    st.metric("Eventi Totali", total_events)

with col2:
    unique_ips = filtered_df['src_ip'].nunique()
    st.metric("IP Unici", unique_ips)

with col3:
    sessions = filtered_df['session'].nunique()
    st.metric("Sessioni", sessions)

with col4:
    latest_event = filtered_df['timestamp'].max()
    st.metric("Ultimo Evento", latest_event.strftime('%Y-%m-%d %H:%M'))

st.markdown("---")

# Grafico temporale degli eventi
st.subheader("Attività Temporale")

events_by_hour = filtered_df.groupby(['date', 'hour']).size().reset_index(name='count')
if not events_by_hour.empty:
    fig, ax = plt.subplots(figsize=(12, 6))
    events_by_hour['datetime'] = pd.to_datetime(
        events_by_hour['date'].astype(str) + ' ' + events_by_hour['hour'].astype(str) + ':00'
    )
    ax.plot(events_by_hour['datetime'], events_by_hour['count'], marker='o', linewidth=2)
    ax.set_xlabel('Data e Ora')
    ax.set_ylabel('Numero di Eventi')
    ax.set_title('Eventi per Ora')
    plt.xticks(rotation=45)
    plt.tight_layout()
    st.pyplot(fig)
else:
    st.info("Nessun dato per il periodo selezionato")

# Distribuzione eventi per tipo
st.subheader("Distribuzione Eventi")

col1, col2 = st.columns(2)

with col1:
    event_counts = filtered_df['eventid'].value_counts()
    if not event_counts.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        event_counts.plot(kind='bar', ax=ax, color='skyblue')
        ax.set_xlabel('Tipo di Evento')
        ax.set_ylabel('Conteggio')
        ax.set_title('Eventi per Tipo')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        st.pyplot(fig)

with col2:
    ip_counts = filtered_df['src_ip'].value_counts().head(10)
    if not ip_counts.empty:
        fig, ax = plt.subplots(figsize=(10, 6))
        ip_counts.plot(kind='bar', ax=ax, color='lightcoral')
        ax.set_xlabel('IP Sorgente')
        ax.set_ylabel('Conteggio')
        ax.set_title('Top 10 IP Sorgente')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        st.pyplot(fig)

# Analisi login
st.subheader("Analisi Tentativi di Login")

login_events = filtered_df[filtered_df['eventid'].str.contains('login')]
if not login_events.empty:
    col1, col2 = st.columns(2)
    
    with col1:
        # Successi vs Fallimenti
        login_status = login_events['eventid'].value_counts()
        fig, ax = plt.subplots(figsize=(8, 6))
        login_status.plot(kind='pie', autopct='%1.1f%%', ax=ax)
        ax.set_title('Distribuzione Successi/Fallimenti Login')
        st.pyplot(fig)
    
    with col2:
        # Top username/password
        if 'username' in login_events.columns:
            top_users = login_events['username'].value_counts().head(5)
            top_passwords = login_events['password'].value_counts().head(5)
            
            st.write("**Top Username:**")
            for user, count in top_users.items():
                st.write(f"- {user}: {count} tentativi")
            
            st.write("**Top Password:**")
            for pwd, count in top_passwords.items():
                st.write(f"- {pwd}: {count} tentativi")

# Analisi comandi
st.subheader("Analisi Comandi Eseguiti")

command_events = filtered_df[filtered_df['eventid'] == 'cowrie.command.input']
if not command_events.empty and 'input' in command_events.columns:
    commands = command_events['input'].dropna()
    
    # Top comandi
    top_commands = commands.value_counts().head(10)
    
    col1, col2 = st.columns(2)
    
    with col1:
        fig, ax = plt.subplots(figsize=(10, 6))
        top_commands.plot(kind='bar', ax=ax, color='lightgreen')
        ax.set_xlabel('Comando')
        ax.set_ylabel('Conteggio')
        ax.set_title('Top 10 Comandi Eseguiti')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        st.pyplot(fig)
    
    with col2:
        # Categorie comandi
        command_categories = {
            'File System': ['ls', 'cd', 'pwd', 'cat', 'more', 'less', 'find', 'grep'],
            'System Info': ['whoami', 'uname', 'ps', 'top', 'free', 'df', 'du'],
            'Network': ['ifconfig', 'ip', 'netstat', 'ping', 'curl', 'wget'],
            'Process': ['kill', 'pkill', 'killall'],
            'Other': []  # Tutti gli altri
        }
        
        category_counts = {category: 0 for category in command_categories}
        
        for cmd in commands:
            categorized = False
            for category, keywords in command_categories.items():
                if any(keyword in cmd for keyword in keywords if keyword):
                    category_counts[category] += 1
                    categorized = True
                    break
            if not categorized:
                category_counts['Other'] += 1
        
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.pie(category_counts.values(), labels=category_counts.keys(), autopct='%1.1f%%')
        ax.set_title('Categorie di Comandi')
        st.pyplot(fig)

# Dettagli sessione
st.subheader("Dettagli Sessione")

session_stats = filtered_df.groupby('session').agg({
    'timestamp': ['min', 'max', 'count'],
    'src_ip': 'first',
    'eventid': lambda x: list(x)
}).reset_index()

session_stats.columns = ['session', 'start_time', 'end_time', 'event_count', 'src_ip', 'events']
session_stats['duration'] = (session_stats['end_time'] - session_stats['start_time']).dt.total_seconds()

st.dataframe(
    session_stats[['session', 'src_ip', 'start_time', 'end_time', 'duration', 'event_count']].sort_values('start_time', ascending=False),
    use_container_width=True
)

# Log raw (ultimi 10 eventi)
st.subheader("Ultimi Eventi")
st.dataframe(
    filtered_df[['timestamp', 'eventid', 'src_ip', 'session', 'message']].tail(10),
    use_container_width=True
)

# Informazioni sistema
st.sidebar.markdown("---")
st.sidebar.subheader("Informazioni Sistema")
st.sidebar.write(f"Log caricati: {len(logs)} eventi")
st.sidebar.write(f"Periodo: {df['timestamp'].min().strftime('%Y-%m-%d')} - {df['timestamp'].max().strftime('%Y-%m-%d')}")
st.sidebar.write(f"File: honeypots/cowrie3/log/cowrie.json")

# Refresh button
if st.sidebar.button("Aggiorna Dati"):
    st.cache_data.clear()
    st.rerun()