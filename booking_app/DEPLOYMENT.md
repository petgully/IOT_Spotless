# Petgully Spotless - Deployment Guide

## Overview

This guide covers deploying the Petgully Booking Web Application to production.

**Current Stack:**
- Backend: Flask (Python)
- Database: AWS RDS Aurora MySQL
- Features: User auth, pet registration, session booking, QR codes

---

## Deployment Options Comparison

| Platform | Difficulty | Cost | SSL | Custom Domain | Best For |
|----------|------------|------|-----|---------------|----------|
| **Render** | ⭐ Easy | Free tier + $7/mo | ✅ Auto | ✅ Easy | Beginners |
| **Railway** | ⭐ Easy | $5/mo | ✅ Auto | ✅ Easy | Fast deploys |
| **AWS Elastic Beanstalk** | ⭐⭐ Medium | $15-30/mo | ✅ | ✅ | AWS ecosystem |
| **DigitalOcean App** | ⭐⭐ Medium | $5/mo | ✅ Auto | ✅ Easy | Good balance |
| **AWS EC2** | ⭐⭐⭐ Advanced | $10-20/mo | Manual | Manual | Full control |

---

## RECOMMENDED: Option 1 - Render.com (Easiest)

### Why Render?
- Free SSL certificates (HTTPS)
- Automatic deploys from GitHub
- Easy custom domain setup
- Good free tier to start
- Scales automatically

### Step-by-Step Setup

#### Step 1: Prepare Your Code

1. **Create production configuration file:**

```python
# config.py
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-this'
    
    # Database
    DB_HOST = os.environ.get('DB_HOST')
    DB_PORT = int(os.environ.get('DB_PORT', 3306))
    DB_USER = os.environ.get('DB_USER')
    DB_PASSWORD = os.environ.get('DB_PASSWORD')
    DB_NAME = os.environ.get('DB_NAME', 'petgully_db')
    
    # Google OAuth (for later)
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
```

2. **Create `requirements.txt` (production):**

```
flask>=2.3.0
pymysql>=1.1.0
cryptography>=3.4.0
qrcode[pil]>=7.4.0
pillow>=9.0.0
gunicorn>=21.0.0
python-dotenv>=1.0.0
```

3. **Create `render.yaml` (Render blueprint):**

```yaml
services:
  - type: web
    name: petgully-booking
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app --bind 0.0.0.0:$PORT
    envVars:
      - key: SECRET_KEY
        generateValue: true
      - key: DB_HOST
        sync: false
      - key: DB_PORT
        value: 3306
      - key: DB_USER
        sync: false
      - key: DB_PASSWORD
        sync: false
      - key: DB_NAME
        value: petgully_db
      - key: PYTHON_VERSION
        value: 3.11.0
```

#### Step 2: Push to GitHub

```bash
# Initialize git (if not already)
cd c:\Users\deepa\Documents\Github\Project_Alpha\Project_Spotless\booking_app
git init

# Create .gitignore
echo "__pycache__/
*.pyc
.env
*.db
.DS_Store
venv/
" > .gitignore

# Add and commit
git add .
git commit -m "Initial booking app for deployment"

# Create GitHub repo and push
# Go to github.com -> New Repository -> "petgully-booking"
git remote add origin https://github.com/YOUR_USERNAME/petgully-booking.git
git branch -M main
git push -u origin main
```

#### Step 3: Deploy on Render

1. Go to [render.com](https://render.com) and sign up
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub account
4. Select your `petgully-booking` repository
5. Configure:
   - **Name:** `petgully-booking`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
6. Add Environment Variables:
   - `SECRET_KEY`: (click Generate)
   - `DB_HOST`: `petgully-dbserver.cmzwm2y64qh8.us-east-1.rds.amazonaws.com`
   - `DB_PORT`: `3306`
   - `DB_USER`: `spotless001`
   - `DB_PASSWORD`: `Batman@686`
   - `DB_NAME`: `petgully_db`
7. Click **"Create Web Service"**

#### Step 4: Connect Custom Domain

1. In Render dashboard, go to your service
2. Click **"Settings"** → **"Custom Domains"**
3. Click **"Add Custom Domain"**
4. Enter your domain (e.g., `booking.petgully.com`)
5. Render will show DNS records to add:

**Add these to your domain registrar:**

| Type | Name | Value |
|------|------|-------|
| CNAME | booking | petgully-booking.onrender.com |

Or for root domain:
| Type | Name | Value |
|------|------|-------|
| A | @ | (Render IP - shown in dashboard) |

6. Wait 10-30 minutes for DNS propagation
7. Render auto-provisions SSL certificate

---

## Option 2 - Railway.app (Also Easy)

### Step-by-Step

1. Go to [railway.app](https://railway.app)
2. Sign up with GitHub
3. Click **"New Project"** → **"Deploy from GitHub"**
4. Select your repository
5. Railway auto-detects Python
6. Add environment variables in dashboard
7. Custom domain: Settings → Domains → Add

---

## Option 3 - AWS Elastic Beanstalk (AWS Ecosystem)

### Why EB?
- Same AWS ecosystem as your RDS
- Better network performance (same region)
- More professional setup

### Step-by-Step

#### Step 1: Install EB CLI

```bash
pip install awsebcli
```

#### Step 2: Create EB Configuration

Create `.ebextensions/python.config`:

```yaml
option_settings:
  aws:elasticbeanstalk:container:python:
    WSGIPath: app:app
  aws:elasticbeanstalk:environment:proxy:staticfiles:
    /static: static
```

Create `Procfile`:

```
web: gunicorn app:app --bind 0.0.0.0:8000
```

#### Step 3: Initialize and Deploy

```bash
cd booking_app

# Initialize
eb init -p python-3.11 petgully-booking --region us-east-1

# Create environment
eb create petgully-booking-prod

# Set environment variables
eb setenv SECRET_KEY=your-secret-key \
  DB_HOST=petgully-dbserver.cmzwm2y64qh8.us-east-1.rds.amazonaws.com \
  DB_PORT=3306 \
  DB_USER=spotless001 \
  DB_PASSWORD=Batman@686 \
  DB_NAME=petgully_db

# Deploy
eb deploy
```

#### Step 4: Custom Domain with Route 53

1. Go to AWS Route 53
2. Create Hosted Zone for your domain
3. Update nameservers at your registrar
4. Add record:
   - Type: A - Alias
   - Alias Target: Your EB environment
5. Request SSL certificate via ACM
6. Configure HTTPS in EB load balancer

---

## AWS RDS Security Group Update

**IMPORTANT:** Update your RDS security group to allow connections from your hosting platform.

### For Render:
Add these IPs to your RDS security group inbound rules:
- Render IPs vary - check their docs or use 0.0.0.0/0 temporarily

### For AWS Elastic Beanstalk:
- Add security group of your EB environment to RDS inbound rules

### How to Update Security Group:

1. Go to AWS Console → RDS → Your database
2. Click on Security Group link
3. Edit Inbound Rules
4. Add rule:
   - Type: MySQL/Aurora
   - Port: 3306
   - Source: Custom (hosting platform IP or security group)

---

## Production Checklist

### Security
- [ ] Change SECRET_KEY to a strong random value
- [ ] Use environment variables for all secrets
- [ ] Enable HTTPS (automatic on Render/Railway)
- [ ] Update RDS security group
- [ ] Remove debug mode in production

### Code Updates for Production

Update `app.py`:

```python
# At the top
import os

# Change debug mode
if __name__ == '__main__':
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5001)), debug=debug_mode)
```

### Database
- [ ] Verify RDS is accessible from hosting platform
- [ ] Test database connection after deploy
- [ ] Set up database backups (AWS RDS has automatic backups)

### Domain
- [ ] Configure DNS records
- [ ] Wait for SSL certificate provisioning
- [ ] Test HTTPS access
- [ ] Set up www redirect if needed

---

## Adding Google Login (After Basic Deploy Works)

### Step 1: Create Google OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create new project: "Petgully Booking"
3. Go to APIs & Services → Credentials
4. Create OAuth 2.0 Client ID
5. Application type: Web application
6. Add Authorized redirect URIs:
   - `https://yourdomain.com/auth/google/callback`
   - `http://localhost:5001/auth/google/callback` (for testing)
7. Copy Client ID and Client Secret

### Step 2: Install OAuth Library

```bash
pip install flask-dance
```

Add to requirements.txt:
```
flask-dance>=6.0.0
```

### Step 3: Add Google OAuth Routes

```python
from flask_dance.contrib.google import make_google_blueprint, google

google_bp = make_google_blueprint(
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    scope=['profile', 'email'],
    redirect_url='/auth/google/callback'
)
app.register_blueprint(google_bp, url_prefix='/auth')

@app.route('/auth/google/callback')
def google_callback():
    if not google.authorized:
        return redirect(url_for('google.login'))
    
    resp = google.get('/oauth2/v2/userinfo')
    if resp.ok:
        user_info = resp.json()
        email = user_info['email']
        name = user_info.get('name', email.split('@')[0])
        
        # Check if user exists, create if not
        db = get_db()
        if db and db.is_connected:
            with db._connection.cursor() as cursor:
                cursor.execute("SELECT * FROM customers WHERE email = %s", (email,))
                user = cursor.fetchone()
                
                if not user:
                    # Create new user
                    cursor.execute("""
                        INSERT INTO customers (email, name, password_hash, is_admin)
                        VALUES (%s, %s, 'google_oauth', 0)
                    """, (email, name))
                    user_id = cursor.lastrowid
                else:
                    user_id = user['id']
                
                session['user_id'] = user_id
                session['user_email'] = email
                session['user_name'] = name
                
        return redirect(url_for('dashboard'))
    
    return redirect(url_for('login'))
```

### Step 4: Update Login Template

Add Google login button:

```html
<a href="{{ url_for('google.login') }}" class="btn btn-outline" style="margin-top: 15px;">
    <img src="https://developers.google.com/identity/images/g-logo.png" style="width: 20px; margin-right: 10px;">
    Continue with Google
</a>
```

---

## Quick Start Commands

### Deploy to Render (Fastest)

```bash
# 1. Create GitHub repo and push code
cd c:\Users\deepa\Documents\Github\Project_Alpha\Project_Spotless\booking_app
git init
git add .
git commit -m "Initial deploy"
# Create repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/petgully-booking.git
git push -u origin main

# 2. Go to render.com
# 3. Connect GitHub, select repo
# 4. Add env variables
# 5. Deploy!
```

---

## Troubleshooting

### "Database connection failed"
- Check RDS security group allows hosting platform IP
- Verify environment variables are set correctly
- Check DB_HOST doesn't have typos

### "502 Bad Gateway"
- Check application logs in hosting dashboard
- Verify gunicorn is starting correctly
- Check PORT environment variable

### "SSL Certificate Error"
- Wait 10-30 minutes for certificate provisioning
- Verify DNS records are correct
- Try accessing via HTTP first

### "Static files not loading"
- Check static folder is included in deployment
- Verify static file paths in templates

---

## Cost Estimate

| Component | Monthly Cost |
|-----------|--------------|
| Render/Railway (starter) | $7-15 |
| AWS RDS Aurora (existing) | ~$30 |
| Domain | ~$1 |
| **Total** | **~$40-50/month** |

---

## Next Steps After Deployment

1. ✅ Basic deployment working
2. Add Google OAuth login
3. Add payment gateway (Razorpay for India)
4. Add email notifications
5. Add admin dashboard
6. Add booking analytics
7. Mobile app (React Native)

---

## Support

If you face any issues during deployment, check:
1. Hosting platform logs
2. AWS RDS logs
3. Browser developer console

Good luck with your deployment! 🚀
