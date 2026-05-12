import sys
sys.path.insert(0, r'c:\Users\ASUS\OneDrive\Desktop\garage')

from app import app

with app.app_context():
    from models.db import get_db
    
    print('Running salary schema migration...')
    
    columns = {row['name'] for row in get_db().execute('PRAGMA table_info(salary_records)').fetchall()}
    print(f'Before migration - Columns: {sorted(columns)}')
    
    # Add missing columns
    alter_stmts = []
    
    if 'salary_status' not in columns:
        alter_stmts.append("ALTER TABLE salary_records ADD COLUMN salary_status TEXT NOT NULL DEFAULT 'saved'")
    
    if 'payment_status' not in columns:
        alter_stmts.append("ALTER TABLE salary_records ADD COLUMN payment_status TEXT DEFAULT 'pending'")
    
    if 'paid_at' not in columns:
        alter_stmts.append("ALTER TABLE salary_records ADD COLUMN paid_at TEXT")
    
    if 'updated_at' not in columns:
        alter_stmts.append("ALTER TABLE salary_records ADD COLUMN updated_at TEXT")
    
    if 'payment_method' not in columns:
        alter_stmts.append("ALTER TABLE salary_records ADD COLUMN payment_method TEXT")
    
    for stmt in alter_stmts:
        print(f'Executing: {stmt}')
        get_db().execute(stmt)
    
    get_db().commit()
    
    # Verify
    columns = {row['name'] for row in get_db().execute('PRAGMA table_info(salary_records)').fetchall()}
    print(f'After migration - Columns: {sorted(columns)}')
    
    if 'updated_at' in columns:
        print('SUCCESS: updated_at column now exists!')
    else:
        print('ERROR: updated_at still missing')
