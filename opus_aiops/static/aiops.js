// AI Ops auto-refresh
(function() {
    const REFRESH_SEC = 15;
    let countdown = REFRESH_SEC;
    const badge = document.getElementById('auto-refresh-badge');

    setInterval(function() {
        countdown--;
        if (badge) badge.textContent = 'refresh: ' + countdown + 's';
        if (countdown <= 0) {
            location.reload();
        }
    }, 1000);
})();
