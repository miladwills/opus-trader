# Quickstart: Unified to Funding Transfer

## Setup

1. Ensure Bybit API keys in `.env` have "Asset Transfer" permissions.
2. Start the dashboard: `python app.py`.

## Verification Steps

### 1. Check Balances
- Open the dashboard in a browser.
- Verify that the "Total Assets" card now shows both Unified and Funding balances (or has a tool-tip/toggle).

### 2. Perform Transfer
- Locate the "Transfer Assets" button in the account section.
- Click to open the modal.
- Select "Unified" -> "Funding".
- Enter a small amount (e.g., 1 USDT).
- Click "Confirm".

### 3. Validate Outcome
- Confirm a success toast message appears.
- Verify the dashboard balances update automatically.
- (Optional) Verify the transfer in the Bybit website history.
