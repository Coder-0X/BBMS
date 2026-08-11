# Blood Bank Management System (BBMS)

The Blood Bank Management System is a web-based application designed to automate and streamline the operations of a blood bank. Blood banks are critical components of healthcare infrastructure, and their efficient management is vital for saving lives. Manual management of blood bank operations is prone to errors, inefficiencies, and delays that can have life-threatening consequences. 

This project aims to develop a comprehensive web-based platform to automate donor registration, recipient management, blood stock tracking, eligibility verification, and blood request processing. 

## Features
- **Donor Management**: Register donors, track donations, and manage deferrals.
- **Inventory Tracking**: Real-time tracking of blood units and components with expiration alerts.
- **Patient & Transfusion**: Manage patient requests and handle the crossmatching process.
- **Lab Screening**: Screen donations for safety before component separation.
- **Role-Based Access Control**: Secure sections tailored to different staff roles (Booth, Lab, Inventory, Transfusion, Admin).
- **Dashboard & Analytics**: Real-time system counters and visual statistics.

## Technology Stack
- **Backend**: Django (Python)
- **Database**: MySQL
- **Frontend**: HTML5, CSS3, Bootstrap 5, JavaScript (Chart.js, TomSelect)

## Local Development Setup

### Prerequisites
- Python 3.10+
- MySQL Server (or XAMPP for local testing)

### Installation Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Coder-0X/BBMS.git
   cd BBMS
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration:**
   Create a `.env` file in the root directory (same folder as `manage.py`) and add your database credentials and settings:
   ```env
   DJANGO_SECRET_KEY=your-secure-secret-key
   DJANGO_DEBUG=True
   DJANGO_ALLOWED_HOSTS=*
   
   # Database Settings
   DB_NAME=blood_bank_db
   DB_USER=root
   DB_PASSWORD=
   DB_HOST=127.0.0.1
   DB_PORT=3306
   ```

5. **Database Setup:**
   Ensure your MySQL server is running and you have created a database named `blood_bank_db`. Then run the migrations:
   ```bash
   python manage.py migrate
   ```

6. **Create a Superuser (Admin Account):**
   ```bash
   python manage.py createsuperuser
   ```

7. **Run the Development Server:**
   ```bash
   python manage.py runserver
   ```
   Open your browser and navigate to `http://127.0.0.1:8000/`.
