"""
BahayCubo — main Flask application entry point.
"""

from __future__ import annotations

from flask import Flask, render_template

from apps.CuboCross.routes import cubocross_bp

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

app.register_blueprint(cubocross_bp)


@app.route("/")
def landing():
    return render_template("landing.html")


_COMING_SOON = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>BahayCubo — Coming Soon</title>
</head>
<body>
  <p>Coming soon.</p>
</body>
</html>"""


@app.route("/webapps")
def webapps():
    return _COMING_SOON


@app.route("/aboutme")
def aboutme():
    return _COMING_SOON


@app.route("/contact")
def contact():
    return _COMING_SOON


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True, use_reloader=False)
