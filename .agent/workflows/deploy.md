---
description: Deploy changes to VPS with minimal approvals
---

# Turbo Deploy Workflow
// turbo-all

This workflow uploads all modified files and restarts the service in a single batch.

## Steps

1. Upload backend files
```
pscp -pw aA0109587045 -r services/*.py root@178.18.245.6:/var/www/opus_trader/services/
```

2. Upload frontend files
```
pscp -pw aA0109587045 -r static/js/*.js root@178.18.245.6:/var/www/opus_trader/static/js/
```

3. Upload templates
```
pscp -pw aA0109587045 templates/dashboard.html root@178.18.245.6:/var/www/opus_trader/templates/
```

4. Upload Systemd Service (Config Update)
```
pscp -pw aA0109587045 opus_trader.service root@178.18.245.6:/etc/systemd/system/opus_trader.service
plink -pw aA0109587045 root@178.18.245.6 "systemctl daemon-reload"
```

5. Restart the service
```
plink -pw aA0109587045 root@178.18.245.6 "systemctl restart opus_trader"
```

5. Verify service is running
```
plink -pw aA0109587045 root@178.18.245.6 "systemctl status opus_trader | head -n 5"
```
