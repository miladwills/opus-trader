"""Dashboard route for Trading Watchdog."""

from flask import Blueprint, render_template

dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    template_folder="../templates",
    static_folder="../static",
    static_url_path="/static/tw",
)


@dashboard_bp.route("/")
def index():
    return render_template("dashboard.html")
