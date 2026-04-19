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


@app.route("/webapps")
def webapps():
    return render_template("webapps.html")


@app.route("/aboutme")
def aboutme():
    return render_template("aboutme.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.route('/sitemap.xml')
def sitemap():
    return app.send_static_file('sitemap.xml')

@app.route('/robots.txt')
def robots():
    return app.send_static_file('robots.txt')

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True, use_reloader=False)
