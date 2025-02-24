from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from parser import run_parser, STOP_EVENT
import threading

app = Flask(__name__)
parser_thread = None
SYSTEM_ADDRESS = '03ee3c8ccb1a84b0b28ff099c8b12f79e4cdb416b5fe00afa156559cf941b13eda'

def get_db_connection():
    conn = sqlite3.connect('kismi_ledger.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/', methods=['GET', 'POST'])
def explorer():
    conn = get_db_connection()
    
    per_page = 20
    page = int(request.args.get('page', 1))
    offset = (page - 1) * per_page
    
    query = "SELECT * FROM transactions WHERE 1=1"
    count_query = "SELECT COUNT(*) as total FROM transactions WHERE 1=1"
    params = []
    
    if request.method == 'POST' and 'filter' in request.form:
        tx_hash = request.form.get('tx_hash')
        from_addr = request.form.get('from_addr')
        to_addr = request.form.get('to_addr')
        date_start = request.form.get('date_start')
        
        if tx_hash:
            query += " AND tx_hash = ?"
            count_query += " AND tx_hash = ?"
            params.append(tx_hash)
        if from_addr:
            query += " AND from_addr = ?"
            count_query += " AND from_addr = ?"
            params.append(from_addr)
        if to_addr:
            query += " AND to_addr = ?"
            count_query += " AND to_addr = ?"
            params.append(to_addr)
        if date_start:
            query += " AND date_utc >= ?"
            count_query += " AND date_utc >= ?"
            params.append(date_start)
    
    total = conn.execute(count_query, params).fetchone()['total']
    transactions = conn.execute(query + f" ORDER BY date_utc DESC LIMIT {per_page} OFFSET {offset}", params).fetchall()
    total_pages = (total + per_page - 1) // per_page
    
    # Графики
    chart_data = conn.execute("""
        SELECT strftime('%Y-%m-%d', 
               substr(date_utc, 7, 4) || '-' || 
               substr(date_utc, 4, 2) || '-' || 
               substr(date_utc, 1, 2)) as day, 
               COUNT(*) as count 
        FROM transactions 
        GROUP BY day
    """).fetchall()
    labels = [row['day'] for row in chart_data]
    values = [row['count'] for row in chart_data]
    
    amount_data = conn.execute("""
        SELECT strftime('%Y-%m-%d', 
               substr(date_utc, 7, 4) || '-' || 
               substr(date_utc, 4, 2) || '-' || 
               substr(date_utc, 1, 2)) as day, 
               SUM(amount) as total 
        FROM transactions 
        GROUP BY day
    """).fetchall()
    amount_labels = [row['day'] for row in amount_data]
    amount_values = [row['total'] for row in amount_data]
    
    blocks = conn.execute("SELECT block_id, start_time, end_time FROM blocks ORDER BY block_id DESC LIMIT 5").fetchall()
    
    # Балансы пользователей (KISS-ы, топ-15)
    user_balances = {}
    cursor = conn.execute("SELECT from_addr, to_addr, amount FROM transactions")
    for row in cursor.fetchall():
        from_addr, to_addr, amount = row['from_addr'], row['to_addr'], row['amount']
        if from_addr == SYSTEM_ADDRESS:
            user_balances[to_addr] = user_balances.get(to_addr, 0) + amount
        elif to_addr != SYSTEM_ADDRESS:
            user_balances[from_addr] = user_balances.get(from_addr, 0) - amount
    
    sorted_user_balances = sorted(
        [(addr, bal) for addr, bal in user_balances.items() if addr != SYSTEM_ADDRESS and bal > 0],
        key=lambda x: x[1], reverse=True
    )[:15]  # Ограничиваем до 15 записей
    
    # Балансы заявок (топ-15)
    claim_balances = conn.execute("""
        SELECT to_addr, SUM(amount) as total 
        FROM transactions 
        WHERE from_addr != ? 
        GROUP BY to_addr 
        ORDER BY total DESC 
        LIMIT 15
    """, (SYSTEM_ADDRESS,)).fetchall()
    
    # Статистика по типам транзакций
    tx_types = conn.execute("""
        SELECT type, COUNT(*) as count 
        FROM transactions 
        GROUP BY type
    """).fetchall()
    tx_type_stats = {row['type']: row['count'] for row in tx_types}
    
    conn.close()
    return render_template('index.html', transactions=transactions, labels=labels, values=values, 
                          amount_labels=amount_labels, amount_values=amount_values, blocks=blocks, 
                          parsing=not STOP_EVENT.is_set(), page=page, total_pages=total_pages,
                          user_balances=sorted_user_balances, claim_balances=claim_balances,
                          tx_type_stats=tx_type_stats, total=total)

@app.route('/parse', methods=['POST'])
def parse():
    global parser_thread
    if STOP_EVENT.is_set():
        parser_thread = threading.Thread(target=run_parser)
        parser_thread.start()
    return redirect(url_for('explorer'))

@app.route('/stop_parse', methods=['POST'])
def stop_parse():
    global STOP_EVENT
    STOP_EVENT.set()
    if parser_thread:
        parser_thread.join()
    return redirect(url_for('explorer'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
