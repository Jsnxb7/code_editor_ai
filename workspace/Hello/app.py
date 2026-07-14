from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

@app.route("/")
def home():
    return render_template('login.html')

@app.route("/signup", methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # Process the signup form data
        username = request.form['username']
        password = request.form['password']
        # Here you would add code to save the user data to a database
        return redirect(url_for('home'))
    return render_template('signup.html')

@app.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Process the login form data
        username = request.form['username']
        password = request.form['password']
        # Here you would add code to verify the user data
        return redirect(url_for('home'))
    return render_template('login.html')

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8000,
        debug=True,
        use_reloader=False
    )