# Feature: Bugfix - Transfer Unified to Funding Dashboard Exposure

## Overview
The backend functionality for internal transfers between UNIFIED and FUND account types is implemented in `app.py` and `BybitClient`, but the feature is not accessible from the dashboard UI. This task involves exposing this functionality to the user.

## User Story
**As a** Trader  
**I want to** be able to initiate a transfer from my Unified Trading Account to my Funding Account directly from the dashboard  
**So that** I can manage my funds without leaving the control center.

## Current State Analysis
- **Backend (Implemented)**: 
    - `BybitClient.create_internal_transfer` communicates with `/v5/asset/transfer/inter-transfer`.
    - `app.py` has an `@app.route("/api/transfer", methods=["POST"])` endpoint.
- **Frontend (Missing)**:
    - No UI elements in `dashboard.html` for triggering the transfer.
    - No Javascript logic in `app.js` to collect input (amount) and call `/api/transfer`.

## Acceptance Criteria

### 1. Dashboard UI
- [ ] Add a "Transfer Funds" section or button to the Account Summary area.
- [ ] Provide an input field for `Amount`.
- [ ] Provide a "Transfer to Funding" button.
- [ ] (Optional) Provide a dropdown or toggle for `Coin` (default to USDT).

### 2. Frontend Logic
- [ ] Implement a `transferFunds()` function in `app.js`.
- [ ] Show a confirmation dialog before proceeding.
- [ ] Show success/error notifications using the existing dashboard notification system.
- [ ] Refresh the "Account Overview" after a successful transfer.

### 3. Safety Checks
- [ ] Validate that the amount is greater than 0.
- [ ] Disable the button while the request is in progress.

## Verification Plan

### Manual Verification
1. Enter an amount in the new transfer field.
2. Click "Transfer to Funding".
3. Confirm the dialog.
4. Verify that a success message appears.
5. Verify that the "Unified Balance" updates (decreases).
6. Verify in Bybit (manually) that funds moved to Funding.
