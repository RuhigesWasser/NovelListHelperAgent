"""Optional application account storage, separate from in-memory login cookies."""
import json
import os
from pathlib import Path
import threading


class ESJSettings:
    def __init__(self, local):
        self.path=Path(local)/'esj-settings.json'
        self.lock=threading.RLock()
        self.data=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}

    def public(self):
        with self.lock:
            return {'email':self.data.get('email',''),'has_password':bool(self.data.get('password')),
                    'remember':self.data.get('remember',False)}

    def resolve(self,email,password):
        with self.lock:
            email=email.strip() or self.data.get('email','')
            if not password and email==self.data.get('email'):
                password=self.data.get('password','')
            if not email or not password:
                raise ValueError('请填写账号和密码；更换账号时需要重新输入密码')
            return email,password

    def save(self,email,password,remember):
        email,password=self.resolve(email,password)
        with self.lock:
            if remember:
                temporary=self.path.with_suffix('.tmp')
                with temporary.open('w',encoding='utf-8') as output:
                    if os.name!='nt':os.chmod(temporary,0o600)
                    json.dump({'email':email,'password':password,'remember':True},output,ensure_ascii=False,indent=2)
                temporary.replace(self.path)
            else:
                self.path.unlink(missing_ok=True)
            self.data={'email':email,'password':password,'remember':remember}
        return self.public()

    def clear(self):
        with self.lock:
            self.data.clear()
            self.path.unlink(missing_ok=True)

    def close(self):
        with self.lock:self.data.clear()
