import requests
from bs4 import BeautifulSoup
import sqlite3
import time
from datetime import datetime, timedelta
import threading

STOP_EVENT = threading.Event()

def init_db():
    conn = sqlite3.connect('kismi_ledger.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
        tx_hash TEXT PRIMARY KEY, type TEXT, date_utc TEXT,
        amount REAL, from_addr TEXT, to_addr TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS blocks (
        block_id INTEGER PRIMARY KEY AUTOINCREMENT, start_time TEXT, end_time TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS block_transactions (
        block_id INTEGER, tx_hash TEXT,
        FOREIGN KEY (block_id) REFERENCES blocks(block_id),
        FOREIGN KEY (tx_hash) REFERENCES transactions(tx_hash))''')
    conn.commit()
    conn.close()

def get_last_page():
    try:
        with open('progress.txt', 'r') as f:
            return int(f.read().strip())
    except FileNotFoundError:
        return 0

def save_progress(page):
    with open('progress.txt', 'w') as f:
        f.write(str(page))

def parse_page(page):
    url = f'https://kismi.app/ledger/?p={page}'
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    table = soup.find('table', id='kt_profile_overview_table')
    if not table:
        return []
    
    transactions = []
    for row in table.find('tbody').find_all('tr'):
        cols = row.find_all('td')
        if len(cols) != 6:
            continue
        
        tx_hash = cols[0].find('a').find('span').text.strip()
        amount = float(cols[1].text.strip())
        type_badge = cols[2].find('div', class_='badge')
        tx_type = type_badge.text.strip() if type_badge else 'Unknown'
        date_utc = cols[3].text.strip()
        from_addr = cols[4].find('span').text.strip()
        to_addr = cols[5].find('span').text.strip()
        
        transactions.append({
            'tx_hash': tx_hash,
            'type': tx_type,
            'date_utc': date_utc,
            'amount': amount,
            'from_addr': from_addr,
            'to_addr': to_addr
        })
    
    return transactions

def run_parser():
    global STOP_EVENT
    STOP_EVENT.clear()
    init_db()
    conn = sqlite3.connect('kismi_ledger.db')
    cursor = conn.cursor()
    
    last_page = get_last_page()
    page = last_page + 1
    
    while not STOP_EVENT.is_set():
        transactions = parse_page(page)
        if not transactions:
            break
        
        for tx in transactions:
            if STOP_EVENT.is_set():
                break
            try:
                cursor.execute('''INSERT OR IGNORE INTO transactions 
                    (tx_hash, type, date_utc, amount, from_addr, to_addr)
                    VALUES (?, ?, ?, ?, ?, ?)''', 
                    (tx['tx_hash'], tx['type'], tx['date_utc'],
                     tx['amount'], tx['from_addr'], tx['to_addr']))
                conn.commit()
            except Exception as e:
                print(f"Ошибка при сохранении {tx['tx_hash']}: {e}")
        
        save_progress(page)
        print(f"Обработана страница {page}")
        page += 1
        time.sleep(0.5)
    
    # Создаём блоки даже при остановке
    group_into_blocks()
    conn.close()

def group_into_blocks():
    conn = sqlite3.connect('kismi_ledger.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT tx_hash, date_utc FROM transactions ORDER BY date_utc")
    txs = cursor.fetchall()
    
    current_block_start = None
    block_txs = []
    
    for tx_hash, date_utc in txs:
        dt = datetime.strptime(date_utc, '%d.%m.%Y %H:%M:%S')
        minute_start = dt.replace(second=0, microsecond=0)
        
        if current_block_start != minute_start:
            if block_txs:
                cursor.execute("INSERT INTO blocks (start_time, end_time) VALUES (?, ?)",
                               (current_block_start.strftime('%Y-%m-%d %H:%M:%S'),
                                (current_block_start + timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')))
                block_id = cursor.lastrowid
                for b_tx in block_txs:
                    cursor.execute("INSERT INTO block_transactions (block_id, tx_hash) VALUES (?, ?)",
                                   (block_id, b_tx))
                conn.commit()
            current_block_start = minute_start
            block_txs = []
        
        block_txs.append(tx_hash)
    
    if block_txs:
        cursor.execute("INSERT INTO blocks (start_time, end_time) VALUES (?, ?)",
                       (current_block_start.strftime('%Y-%m-%d %H:%M:%S'),
                        (current_block_start + timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')))
        block_id = cursor.lastrowid
        for b_tx in block_txs:
            cursor.execute("INSERT INTO block_transactions (block_id, tx_hash) VALUES (?, ?)",
                           (block_id, b_tx))
        conn.commit()
    
    conn.close()

if __name__ == "__main__":
    run_parser()