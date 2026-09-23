"""Local named API profiles. Persistence is explicit and never uses browser storage."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import uuid
from urllib.parse import urlsplit
from app.paths import add_tools

add_tools()
from llm_client import LlmOCR, fingerprint

DEFAULTS = {'name':'默认配置','base_url':'','model':'','key':'','protocol':'chat_completions',
            'endpoint_mode':'auto','auth':'auto','key_header':'','api_version':'2023-06-01',
            'max_tokens':32768,'timeout':300,'stream':False,'token_field':'max_tokens',
            'headers':{},'extra_body':{},'remember_key':True}


class LlmSettings:
    def __init__(self, local):
        self.path = Path(local)/'settings.json'
        self.lock = threading.RLock()
        self.preferences = {'engine':'builtin','language':'zh'}
        saved = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        if saved.get('version') == 2:
            self.profiles = {p['id']:{**deepcopy(DEFAULTS),**p} for p in saved.get('profiles',[])}
            self.active_id = saved.get('active_id')
            self.preferences.update(saved.get('preferences',{}))
        else:
            self.profiles = {'default':{**deepcopy(DEFAULTS),**saved,'id':'default'}}
            self.active_id = 'default'
        if not self.profiles:
            self.profiles = {'default':{**deepcopy(DEFAULTS),'id':'default'}}
        if self.active_id not in self.profiles:
            self.active_id = next(iter(self.profiles))

    def _write(self):
        profiles = deepcopy(list(self.profiles.values()))
        for profile in profiles:
            if not profile['remember_key']:
                profile['key'] = ''
        data = {'version':2,'active_id':self.active_id,'preferences':self.preferences,'profiles':profiles}
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temp,self.path)

    def current(self):
        with self.lock:
            return deepcopy(self.profiles[self.active_id])

    def public(self):
        with self.lock:
            current = self.current()
            def visible(profile):
                return {**{k:v for k,v in profile.items() if k!='key'},'has_key':bool(profile['key'])}
            return {**visible(current),'profiles':[visible(p) for p in self.profiles.values()],
                    'active_id':self.active_id,'preferences':dict(self.preferences)}

    def draft(self, values):
        with self.lock:
            identifier = values.get('id') or self.active_id
            old = self.profiles.get(identifier, {})
            result = {**deepcopy(DEFAULTS),**deepcopy(old)}
            result.update({k:v for k,v in values.items() if k in DEFAULTS and k!='key'})
            for field in ('base_url','model','name'):
                result[field] = result[field].strip()
            before, after = urlsplit(old.get('base_url','')), urlsplit(result['base_url'])
            connection_changed = (before.scheme,before.netloc)!=(after.scheme,after.netloc)
            if values.get('clear_key') or connection_changed:
                result['key'] = ''
            if values.get('key'):
                result['key'] = values['key'].strip()
            result['id'] = identifier
            return result

    def save(self, values):
        with self.lock:
            profile = self.draft(values)
            if profile['base_url'] and profile['model']:
                LlmOCR.from_config(profile)
            if profile['id']=='new':
                profile['id'] = uuid.uuid4().hex
            if not profile['name']:
                profile['name'] = profile['model'] or '未命名配置'
            old = self.profiles.get(profile['id'])
            if not old or fingerprint(old)!=fingerprint(profile):
                profile.pop('verification',None)
            self.profiles[profile['id']] = profile
            self.active_id = profile['id']
            self._write()
            return self.public()

    def activate(self, identifier):
        with self.lock:
            if identifier not in self.profiles:
                raise ValueError('配置不存在')
            self.active_id = identifier
            self._write()
            return self.public()

    def delete(self, identifier):
        with self.lock:
            if identifier not in self.profiles:
                raise ValueError('配置不存在')
            del self.profiles[identifier]
            if not self.profiles:
                self.profiles['default'] = {**deepcopy(DEFAULTS),'id':'default'}
            if self.active_id == identifier:
                self.active_id = next(iter(self.profiles))
            self._write()
            return self.public()

    def remember_task(self, engine, language, auto_mode=None):
        with self.lock:
            self.preferences.update(engine=engine,language=language)
            if auto_mode is not None:
                self.preferences['auto_mode'] = auto_mode
            self._write()

    def mark_vision(self, config, result):
        with self.lock:
            current = self.profiles.get(config.get('id'))
            if current and fingerprint(current)==fingerprint(config):
                current['verification'] = {**result,'fingerprint':fingerprint(config),
                                           'checked_at':datetime.now(timezone.utc).isoformat()}
                self._write()

    def ensure_vision(self, config, persist=True):
        verification = config.get('verification',{})
        if verification.get('ok') and verification.get('fingerprint')==fingerprint(config):
            return
        result = LlmOCR.from_config(config).test_vision()
        if persist:
            self.mark_vision(config,result)

    def close(self):
        with self.lock:
            for profile in self.profiles.values():
                profile['key'] = ''
