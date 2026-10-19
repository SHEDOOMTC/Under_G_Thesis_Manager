# UnderG Thesis Manager

A Flask-based thesis management system for students and admin.

## Requirements

- Python 3.10+
- Flask

## Install

```bash
pip install -r requirements.txt
```

## Run locally

```bash
python app.py
```

The app will run on:

- http://localhost:5000

## Default admin login

- Username: `admin`
- Password: `admin123`

## Railway deployment

1. Push this project to GitHub.
2. Import the repo into Railway.
3. Set the Python start command:

```bash
python app.py
```

Railway will provide the `PORT` environment variable automatically.

## Student account creation

Students can register using their registration number and email address, and the admin can also add student profiles from the admin dashboard.
