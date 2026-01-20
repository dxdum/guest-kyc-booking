# Guest KYC & Booking System - Deployment Guide

## Recommended Platform: Render.com (Free Tier)

Render is the easiest option for deploying Flask apps with SQLite.

---

## Step-by-Step Deployment on Render

### 1. Prepare Your Code

Push your code to a GitHub repository:

```bash
cd "G:\My Drive\UNIKO\06_Uniko_Labs\06_active projects\03_Guest KYC_access_keys_Booking"
git init
git add .
git commit -m "Initial commit - Guest KYC Booking System"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/guest-kyc-booking.git
git push -u origin main
```

### 2. Create Render Account

1. Go to https://render.com
2. Sign up with GitHub (recommended for easy repo connection)

### 3. Deploy on Render

1. Click **"New +"** → **"Web Service"**
2. Connect your GitHub repository
3. Configure the service:
   - **Name:** `guest-kyc-booking`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r app/requirements.txt`
   - **Start Command:** `cd app && gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Instance Type:** `Free`

4. Add Environment Variables:
   - `SECRET_KEY` → Click "Generate" for a secure random key
   - `ADMIN_EMAIL` → `dar.duminski@gmail.com`
   - `ADMIN_PASSWORD` → `temp_pass2912!` (or your preferred password)

5. Click **"Create Web Service"**

### 4. Access Your Deployed App

Once deployed, Render will provide a URL like:
```
https://guest-kyc-booking.onrender.com
```

**Access Points:**
- **Admin Dashboard:** `https://your-app.onrender.com/admin`
- **Guest Links:** `https://your-app.onrender.com/guest?reservation=RESERVATION_NUMBER`

---

## Default Credentials

- **Email:** dar.duminski@gmail.com
- **Password:** temp_pass2912!

---

## Creating New Reservations

1. Log in to Admin Dashboard at `/admin`
2. Click **"+ New Reservation"**
3. Fill in:
   - Reservation Number (e.g., `RES-2025-001`)
   - Room Number
   - Check-in Date
   - Check-out Date
4. The system will auto-generate an apartment access code
5. Copy the **Guest Link** to send to your guest

---

## Guest Flow

1. Guest receives link: `https://your-app.onrender.com/guest?reservation=RES-2025-001`
2. Guest sees their room number, dates, and access codes
3. Guest fills in invoice details (individual or business)
4. After checkout, admin can generate and send invoices

---

## Important Notes

### SQLite Limitations on Render Free Tier
- SQLite database resets when the service restarts (free tier limitation)
- For persistent data, upgrade to a paid Render plan with a Disk
- Or switch to PostgreSQL (Render offers free PostgreSQL)

### To Add Persistent Disk (Paid):
1. Go to your Render service
2. Click "Disks" → "Add Disk"
3. Mount path: `/opt/render/project/src/app`
4. This preserves the SQLite database between deployments

---

## Local Development

```bash
cd app
pip install -r requirements.txt
python database.py --reset  # Initialize with demo data
python app.py               # Run on http://localhost:5000
```

---

## Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask session secret | `demo-secret-key-2025` |
| `ADMIN_EMAIL` | Admin login email | `dar.duminski@gmail.com` |
| `ADMIN_PASSWORD` | Admin login password | `temp_pass2912!` |

