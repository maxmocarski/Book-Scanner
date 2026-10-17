"""Server-console fallback when an administrator has no verified email."""
import secrets
import sys
from api.main import db, digest, now


def main():
    if len(sys.argv)!=2: raise SystemExit('Usage: python -m api.recover_account USERNAME')
    with db() as c:
        row=c.execute('SELECT u.id,u.username,p.banned FROM users u JOIN profiles p ON p.user_id=u.id WHERE username=?',(sys.argv[1].lower(),)).fetchone()
        if not row or row['banned']: raise SystemExit('Active account not found.')
        code=secrets.token_urlsafe(24)
        c.execute('INSERT OR REPLACE INTO password_resets VALUES(?,?,?,?,?)',(row['id'],digest(code),now()+1800,None,'admin'))
        c.execute("DELETE FROM email_outbox WHERE user_id=? AND kind='reset'",(row['id'],))
        c.execute('INSERT INTO admin_audit(created,admin,action,target) VALUES(?,?,?,?)',(now(),'server-console','password_reset_code',row['id']))
    print('Single-use reset code for @'+row['username']+' (30 minutes): '+code)
    print('Open Forgot password in BookBridge. Share this code only with the account owner.')

if __name__=='__main__': main()
