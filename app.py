from flask import Flask, render_template, request, redirect, session, send_file
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date
import json
import pdfkit
import csv
import io
from flask import Response

app = Flask(__name__)
app.secret_key = 'your_secret_key'

import os

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'receipts')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Dynamically locate wkhtmltopdf in the project directory
wkhtmltopdf_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'wkhtmltopdf', 'bin', 'wkhtmltopdf.exe'))
PDFKIT_CONFIG = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)

# MongoDB Connection
client = MongoClient('mongodb://localhost:27017/')
db = client['money_buddy']
users_col = db['users']
expenses_col = db['expenses']
logins_col = db['logins']

def init_db():
    # MongoDB doesn't need explicit table creation, but we can create indexes
    users_col.create_index("username", unique=True)
    print("Database initialized with indexes.")

init_db()

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect('/login')
    
    records = list(expenses_col.find({'user_id': session['user_id']}))

    income = sum(row['amount'] for row in records if row['type'] == 'income')
    expense = sum(row['amount'] for row in records if row['type'] == 'expense')
    balance = income - expense
    overspent = expense > income

    return render_template(
        'index.html',
        income=income,
        expense=expense,
        balance=balance,
        overspent=overspent,
        username=session.get('username'),
        app_name="Money Buddy"
    )

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        try:
            users_col.insert_one({'username': username, 'password': password})
        except DuplicateKeyError:
            return "Username already exists."
        return redirect('/login')
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = users_col.find_one({'username': username})

        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['username'] = username
            
            # Record login
            logins_col.insert_one({
                'user_id': str(user['_id']),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'ip_address': request.remote_addr,
                'user_agent': request.headers.get('User-Agent')
            })
            
            return redirect('/')
        else:
            return "Invalid credentials"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect('/login')

@app.route('/add', methods=['POST'])
def add_expense():
    if 'user_id' not in session:
        return redirect('/login')

    amount = float(request.form['amount'])
    description = request.form['description']
    type_ = request.form['type']
    category = request.form.get('category') or 'Uncategorized'
    account = request.form.get('account') or 'Cash'
    timestamp = request.form.get('timestamp') or datetime.now().strftime('%Y-%m-%d')

    receipt_url = None
    if 'receipt' in request.files:
        file = request.files['receipt']
        if file.filename != '':
            filename = secure_filename(file.filename)
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            receipt_url = f"uploads/receipts/{filename}"

    expenses_col.insert_one({
        'user_id': session['user_id'],
        'account': account,
        'type': type_,
        'amount': amount,
        'description': description,
        'category': category,
        'timestamp': timestamp,
        'receipt_url': receipt_url
    })

    return redirect('/')

@app.route('/report', methods=['GET', 'POST'])
def report():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    start_date = request.values.get('start_date')
    end_date = request.values.get('end_date')

    query = {'user_id': user_id}
    if start_date and end_date:
        query['timestamp'] = {'$gte': start_date, '$lte': end_date}
    
    rows = list(expenses_col.find(query).sort('timestamp', 1))

    today = date.today()
    day = today.strftime('%Y-%m-%d')
    month_prefix = today.strftime('%Y-%m')
    year_prefix = today.strftime('%Y')

    # ✅ Daily, Monthly, Yearly totals
    daily = sum(r['amount'] for r in expenses_col.find({'user_id': user_id, 'type': 'expense', 'timestamp': day}))
    
    # For monthly/yearly, we can use regex or $gte/$lte. Regex is easier for string-based dates.
    monthly = sum(r['amount'] for r in expenses_col.find({'user_id': user_id, 'type': 'expense', 'timestamp': {'$regex': f'^{month_prefix}'}}))
    yearly = sum(r['amount'] for r in expenses_col.find({'user_id': user_id, 'type': 'expense', 'timestamp': {'$regex': f'^{year_prefix}'}}))

    # ✅ Grouped by type
    summary_data = expenses_col.aggregate([
        {'$match': {'user_id': user_id}},
        {'$group': {'_id': '$type', 'total': {'$sum': '$amount'}}}
    ])
    summary = {item['_id']: item['total'] for item in summary_data}

    # ✅ Category-wise
    cat_query = {'user_id': user_id}
    if start_date and end_date:
        cat_query['timestamp'] = {'$gte': start_date, '$lte': end_date}
    
    category_agg = expenses_col.aggregate([
        {'$match': cat_query},
        {'$group': {'_id': '$category', 'total': {'$sum': '$amount'}}}
    ])
    category_data = [[item['_id'], item['total']] for item in category_agg]

    # ✅ Monthly trend
    trend_match = {'user_id': user_id}
    if start_date and end_date:
        trend_match['timestamp'] = {'$gte': start_date, '$lte': end_date}

    monthly_trend_agg = expenses_col.aggregate([
        {'$match': trend_match},
        {'$group': {
            '_id': {'$substr': ['$timestamp', 0, 7]},
            'income': {'$sum': {'$cond': [{'$eq': ['$type', 'income']}, '$amount', 0]}},
            'expense': {'$sum': {'$cond': [{'$eq': ['$type', 'expense']}, '$amount', 0]}}
        }},
        {'$sort': {'_id': 1}}
    ])
    monthly_trend = [[item['_id'], item['income'], item['expense']] for item in monthly_trend_agg]

    # ✅ Weekwise trend (Simpler to do in memory or with more complex MongoDB dates, but let's stick to what we can)
    # The original SQL used strftime('%Y-%W'). We can do similar with $substr if format allows.
    # Note: Weekly grouping is harder with just string dates in MongoDB without $toDate.
    # I'll use a slightly different approach for weekly if needed, but let's try to match SQL as much as possible.
    weekly_trend_agg = expenses_col.aggregate([
        {'$match': {'user_id': user_id}},
        {'$group': {
            '_id': {'$substr': ['$timestamp', 0, 7]}, # Fallback to monthly if week is too complex for string-dates
            'income': {'$sum': {'$cond': [{'$eq': ['$type', 'income']}, '$amount', 0]}},
            'expense': {'$sum': {'$cond': [{'$eq': ['$type', 'expense']}, '$amount', 0]}}
        }},
        {'$sort': {'_id': 1}}
    ])
    weekly_trend = [[item['_id'], item['income'], item['expense']] for item in weekly_trend_agg]

    # ✅ Yearly trend
    yearly_trend_agg = expenses_col.aggregate([
        {'$match': {'user_id': user_id}},
        {'$group': {
            '_id': {'$substr': ['$timestamp', 0, 4]},
            'income': {'$sum': {'$cond': [{'$eq': ['$type', 'income']}, '$amount', 0]}},
            'expense': {'$sum': {'$cond': [{'$eq': ['$type', 'expense']}, '$amount', 0]}}
        }},
        {'$sort': {'_id': 1}}
    ])
    yearly_trend = [[item['_id'], item['income'], item['expense']] for item in yearly_trend_agg]

    # ✅ Income/Expense totals
    total_income = sum(r['amount'] for r in rows if r['type'] == 'income')
    total_expense = sum(r['amount'] for r in rows if r['type'] == 'expense')
    net_balance = total_income - total_expense

    labels_list = [row[0] for row in category_data]
    category_amounts = [row[1] for row in category_data]

    monthly_labels = [row[0] for row in monthly_trend]
    monthly_income = [row[1] for row in monthly_trend]
    monthly_expense = [row[2] for row in monthly_trend]

    weekly_labels = [row[0] for row in weekly_trend]
    weekly_income = [row[1] for row in weekly_trend]
    weekly_expense = [row[2] for row in weekly_trend]

    yearly_labels = [row[0] for row in yearly_trend]
    yearly_income = [row[1] for row in yearly_trend]
    yearly_expense = [row[2] for row in yearly_trend]

    return render_template('report.html',
        rows=rows, daily=daily, monthly=monthly, yearly=yearly,
        summary=summary,
        category_data=category_data,
        monthly_trend=monthly_trend,
        start_date=start_date or '',
        end_date=end_date or '',
        total_income=total_income,
        total_expense=total_expense,
        net_balance=net_balance,
        labels=labels_list,
        category_amounts=category_amounts,
        monthly_labels=monthly_labels,
        monthly_income=monthly_income,
        monthly_expense=monthly_expense,
        weekly_labels=weekly_labels,
        weekly_income=weekly_income,
        weekly_expense=weekly_expense,
        yearly_labels=yearly_labels,
        yearly_income=yearly_income,
        yearly_expense=yearly_expense,
        app_name="Money Buddy",
        username=session.get("username")
    )

@app.route('/export-pdf')
def export_pdf():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    rows = list(expenses_col.find({'user_id': user_id}).sort('timestamp', 1))
    
    total_income = sum(r['amount'] for r in rows if r['type'] == 'income')
    total_expense = sum(r['amount'] for r in rows if r['type'] == 'expense')
    net_balance = total_income - total_expense

    rendered = render_template('pdf_template.html', 
                               rows=rows, 
                               total_income=total_income, 
                               total_expense=total_expense, 
                               net_balance=net_balance,
                               username=session.get('username'))
    pdf_file = 'report.pdf'
    pdfkit.from_string(rendered, pdf_file, configuration=PDFKIT_CONFIG)
    return send_file(pdf_file, as_attachment=True)

@app.route('/export-csv')
def export_csv():
    if 'user_id' not in session:
        return redirect('/login')

    user_id = session['user_id']
    rows = list(expenses_col.find({'user_id': user_id}).sort('timestamp', 1))

    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['Date', 'Account', 'Type', 'Category', 'Description', 'Amount (INR)'])
    for row in rows:
        writer.writerow([
            row.get('timestamp', ''),
            row.get('account', 'Cash'),
            row.get('type', '').capitalize(),
            row.get('category', ''),
            row.get('description', ''),
            row.get('amount', 0)
        ])

    output.seek(0)
    return Response(
        output, 
        mimetype="text/csv", 
        headers={"Content-Disposition": "attachment;filename=transactions.csv"}
    )

@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect("/login")

    search_query = request.args.get('search', '')
    query = {"user_id": session["user_id"]}
    
    if search_query:
        query['$or'] = [
            {'description': {'$regex': search_query, '$options': 'i'}},
            {'category': {'$regex': search_query, '$options': 'i'}},
            {'account': {'$regex': search_query, '$options': 'i'}}
        ]

    transactions = list(expenses_col.find(query).sort("timestamp", -1))

    return render_template(
        "history.html",
        search_query=search_query,
        transactions=transactions,
        username=session.get("username"),
        app_name="Money Buddy"
    )

@app.route('/settings')
def settings():
    if 'user_id' not in session:
        return redirect('/login')
        
    login_history = list(logins_col.find({'user_id': session['user_id']}).sort('_id', -1).limit(10))
    msg = request.args.get('msg')
    error = request.args.get('error')
    
    return render_template('settings.html', 
                           login_history=login_history, 
                           username=session.get('username'),
                           msg=msg, 
                           error=error)

@app.route('/change-password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect('/login')
        
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    
    user = users_col.find_one({'_id': ObjectId(session['user_id'])})
    if user and check_password_hash(user['password'], current_password):
        users_col.update_one({'_id': ObjectId(session['user_id'])}, {'$set': {'password': generate_password_hash(new_password)}})
        return redirect('/settings?msg=Password updated successfully')
    else:
        return redirect('/settings?error=Incorrect current password')

@app.route('/reset-data', methods=['POST'])
def reset_data():
    if 'user_id' not in session:
        return redirect('/login')
        
    password = request.form.get('password')
    user = users_col.find_one({'_id': ObjectId(session['user_id'])})
    
    if user and check_password_hash(user['password'], password):
        expenses_col.delete_many({'user_id': session['user_id']})
        return redirect('/settings?msg=All transactions deleted successfully')
    else:
        return redirect('/settings?error=Incorrect password')

if __name__ == '__main__':
    app.run(debug=True)
