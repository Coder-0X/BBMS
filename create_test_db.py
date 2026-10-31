"""
One-time setup: create the bloodbank_test database and grant CREATEDB to bloodbank_user.
Run as: python create_test_db.py
Requires the postgres superuser password.
"""
import getpass
import sys
import psycopg2

PG_HOST = '127.0.0.1'
PG_PORT = 5432
APP_USER = 'bloodbank_user'
APP_DB   = 'bloodbank'
TEST_DB  = 'bloodbank_test'

def main():
    print('This script creates the test database and grants CREATEDB to bloodbank_user.')
    print('It needs the postgres superuser (or any superuser) password.\n')
    su_user = input('Superuser username [postgres]: ').strip() or 'postgres'
    su_pass = getpass.getpass(f'Password for {su_user}: ')

    try:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, dbname='postgres',
            user=su_user, password=su_pass,
        )
        conn.autocommit = True
        cur = conn.cursor()

        # Grant CREATEDB so Django can manage test databases itself
        cur.execute(f'ALTER USER {APP_USER} CREATEDB')
        print(f'[OK] Granted CREATEDB to {APP_USER}')

        # Pre-create the test database (Django will recreate it on each run)
        cur.execute(f"SELECT 1 FROM pg_database WHERE datname = '{TEST_DB}'")
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE {TEST_DB} OWNER {APP_USER}')
            print(f'[OK] Created database {TEST_DB}')
        else:
            print(f'[OK] Database {TEST_DB} already exists')

        cur.execute(f'GRANT ALL PRIVILEGES ON DATABASE {TEST_DB} TO {APP_USER}')
        print(f'[OK] Granted ALL on {TEST_DB} to {APP_USER}')
        conn.close()
        print('\nDone! Now run: pytest')

    except psycopg2.OperationalError as e:
        print(f'\nConnection failed: {e}')
        print('Check host/port/username/password and try again.')
        sys.exit(1)
    except Exception as e:
        print(f'\nError: {e}')
        sys.exit(1)

if __name__ == '__main__':
    main()
