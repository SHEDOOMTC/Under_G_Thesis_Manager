import app

client = app.app.test_client()

print('GET /login ->', client.get('/login').status_code)

admin_login = client.post(
    '/login',
    data={'username': 'admin', 'password': 'admin123', 'user_type': 'admin'},
    follow_redirects=False,
)
print('ADMIN LOGIN ->', admin_login.status_code, admin_login.headers.get('Location'))

admin_dashboard = client.get('/admin', follow_redirects=False)
print('ADMIN DASHBOARD ->', admin_dashboard.status_code, admin_dashboard.headers.get('Location'))

student_login = client.post(
    '/login',
    data={'username': 'admin', 'password': 'wrong', 'user_type': 'admin'},
    follow_redirects=False,
)
print('BAD ADMIN LOGIN ->', student_login.status_code, student_login.headers.get('Location'))
