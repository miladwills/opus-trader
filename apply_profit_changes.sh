#!/bin/bash
# Apply small profit target changes to strategy_config.py
CFG="/var/www/config/strategy_config.py"

# 1. Scalp PnL thresholds
sed -i 's/SCALP_PNL_MIN_PROFIT = 0.05/SCALP_PNL_MIN_PROFIT = 0.03/' "$CFG"
sed -i 's/SCALP_PNL_QUICK_PROFIT = 0.30/SCALP_PNL_QUICK_PROFIT = 0.10/' "$CFG"
sed -i 's/SCALP_PNL_TARGET_PROFIT = 0.60/SCALP_PNL_TARGET_PROFIT = 0.15/' "$CFG"
sed -i 's/SCALP_PNL_MAX_TARGET = 1.00/SCALP_PNL_MAX_TARGET = 0.25/' "$CFG"

# 2. Partial TP min profit
sed -i 's/PARTIAL_TP_MIN_PROFIT_PCT = 0.0035/PARTIAL_TP_MIN_PROFIT_PCT = 0.002/' "$CFG"

# 3. Profit lock
sed -i 's/PROFIT_LOCK_ARM_PCT = 0.008/PROFIT_LOCK_ARM_PCT = 0.004/' "$CFG"
sed -i 's/PROFIT_LOCK_GIVEBACK_PCT = 0.0035/PROFIT_LOCK_GIVEBACK_PCT = 0.002/' "$CFG"

# 4. Partial TP levels - replace matching lines
sed -i 's/(0.005, 0.30)/(0.003, 0.40)/' "$CFG"
sed -i 's/(0.010, 0.40)/(0.006, 0.35)/' "$CFG"
sed -i 's/(0.020, 0.30)/(0.010, 0.25)/' "$CFG"

# 5. Restart services
systemctl restart opus_trader
systemctl restart opus_runner
sleep 3
systemctl is-active opus_trader
systemctl is-active opus_runner
echo "DONE"
