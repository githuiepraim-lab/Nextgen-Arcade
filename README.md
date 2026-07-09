# NextGen Arcade Management System

## 5-Minute Deploy (Railway — Free)
1. Push this folder to GitHub
2. railway.app → New Project → Deploy from GitHub
3. Add environment variables in Railway dashboard:
   AT_USERNAME  = your_africastalking_username
   AT_APIKEY    = your_africastalking_api_key
   STAFF_PHONE  = +254XXXXXXXXX
   ADMIN_PHONE  = +254XXXXXXXXX
4. Get free .railway.app domain instantly

## Files
- app.py          — Flask backend (API + SMS + integrity checks)
- static/index.html   — Landing page
- static/staff.html   — Staff dashboard (PIN: 1234)
- static/admin.html   — Admin panel (PIN: 112233)
- static/checkin.html — Customer check-in (no PIN)
- static/api.js       — Shared API client

## SMS Events
- Customer self check-in → alert to staff phone
- Staff approves → confirmation to customer
- Timer expires → SMS to customer + staff
- Staff ends session → receipt to customer
- Integrity check → random CCTV alert to admin phone

## Security
- Staff: 4-digit PIN, 5 attempts, 5min lockout
- Admin: 6-digit PIN, 4 attempts, 10min lockout
- AI integrity: 4 random spot-checks per session sent to admin

## Change PINs
Admin panel → Settings → Change PINs
