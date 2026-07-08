import os
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.urandom(24) # A secret key for session management

USERS_FILE = 'users.json'

def load_users():
    """Loads users from the JSON file."""
    if not os.path.exists(USERS_FILE) or os.path.getsize(USERS_FILE) == 0:
        return {}
    with open(USERS_FILE, 'r') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            # Handle empty or malformed JSON file
            return {}

def save_users(users):
    """Saves users to the JSON file."""
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('index'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        users = load_users()

        if username in users and check_password_hash(users[username]['password_hash'], password):
            session['username'] = username
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'danger')
    
    return render_template('login.html')

@app.route('/signup', methods=['POST'])
def signup():
    username = request.form.get('username')
    password = request.form.get('password')
    
    if not username or not password:
        flash('Username and password are required.', 'danger')
        return redirect(url_for('login'))
    
    users = load_users()
    
    if username in users:
        flash('Username already exists.', 'danger')
        return redirect(url_for('login'))
    
    users[username] = {'password_hash': generate_password_hash(password)}
    save_users(users)
    flash('Signup successful! Please log in.', 'success')
    return redirect(url_for('login'))

@app.route('/index')
def index():
    if 'username' in session:
        return render_template('index.html', username=session['username'])
    flash('You need to log in first.', 'info')
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)