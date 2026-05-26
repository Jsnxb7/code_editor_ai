from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html", title="Bob IDE Sample")

if __name__ == "__main__":
    app.run(debug=False, use_reloader=False, port=7000)
