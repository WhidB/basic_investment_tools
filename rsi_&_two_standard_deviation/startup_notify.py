"""Windows login notification window. No browser or web server."""
import ctypes
import hashlib
import json
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from datetime import datetime
from zoneinfo import ZoneInfo

from notifications import ROOT, rules, startup_enabled, collect_cycle, check_rule, save_report

def run_checks(emit, stop, once=False, loader=None, checker=check_rule, clock=time.monotonic, persist=save_report):
    if loader is None:
        loader = lambda: rules() if once or startup_enabled() else []
    completed = {}
    started = clock()
    last_display = None
    while not stop.is_set():
        current = loader()
        if not current:
            emit('등록된 알림이 없습니다. 전용 프로그램에서 알림받기를 눌러주세요.', True, once)
            return
        before = set(completed)
        completed, failed = collect_cycle(current, completed, checker)
        latest = loader()
        valid = {(r['id'], json.dumps(r['config'],sort_keys=True)) for r in latest}
        vpn = {(r['id'], json.dumps(r['config'],sort_keys=True)) for r in latest
               if r['config'].get('alert_connection') == 'vpn'}
        completed = {k:v for k,v in completed.items() if k in valid}
        failed = {k:v for k,v in failed.items() if k in valid}
        pending_new = valid - set(completed) - set(failed)
        done = not failed and not pending_new
        internet_failed = {k:v for k,v in failed.items() if k not in vpn}
        vpn_waiting = len(vpn - set(completed))
        new_results = set(completed) - before
        # VPN-only failures never open an automatic alert. An actual successful
        # data request is the connection test; no unrelated website can prove it.
        can_show = completed or once or (internet_failed and clock()-started >= 120)
        visible_failures = failed if once else internet_failed
        signature = (tuple(completed.items()),tuple(visible_failures.items()),vpn_waiting,done)
        if can_show and signature != last_display:
            stamp = datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S')
            parts = [f'종가 알림 · {stamp} (한국 시각)',
                     '최신 확정 종가와 각 알림에 저장한 표준편차 기준으로 계산합니다.']
            parts.extend(completed.values())
            parts.extend(visible_failures.values())
            if vpn_waiting:
                parts.append(f'VPN 알림 {vpn_waiting}개는 주가 서버 연결/데이터 수신을 기다리고 있습니다.')
            if not done and not once:
                parts.append('조회되지 않은 항목은 다시 시도합니다. 창을 닫으면 이번 대기를 중지합니다.')
            text = '\n\n'.join(parts)
            persist(text)
            emit(text, done or once, True, bool(new_results) or once)
            last_display = signature
        if done or once:
            if not completed and not failed:
                emit('등록된 알림이 없습니다.', True, once)
            return
        # Check VPN readiness every 30 seconds, but respect provider rate limits.
        limited = any('제한' in v or '종가가 아직' in v for v in failed.values())
        delay = 300 if limited or (not vpn_waiting and clock()-started >= 120) else 30
        if stop.wait(delay):
            return



def acquire_instance(once):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    key = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
    handle = kernel.CreateMutexW(None,False,f'Local\\CloseAlerts_{key}_{once}')
    if not handle:
        raise OSError('알림 실행 잠금을 만들지 못했습니다.')
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        return None, kernel
    return handle, kernel

class NotificationWindow(tk.Tk):
    def __init__(self, once=False):
        super().__init__()
        self.withdraw()
        self.title('RSI · Z-score 종가 알림')
        self.geometry('780x640')
        self.minsize(600,400)
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.shown = False
        self.done = False
        self.top_id = None
        self.columnconfigure(0,weight=1)
        self.rowconfigure(1,weight=1)
        ttk.Label(self,text='로그인 후 최신 종가 분석',font=('맑은 고딕',16,'bold')).grid(row=0,padx=16,pady=12,sticky='w')
        self.body = ScrolledText(self,wrap='word',font=('맑은 고딕',11),state='disabled')
        self.body.grid(row=1,column=0,padx=16,pady=8,sticky='nsew')
        self.state_text = tk.StringVar(value='인터넷 및 종가 데이터 연결 대기')
        ttk.Label(self,textvariable=self.state_text,wraplength=730).grid(row=2,padx=16,sticky='w')
        ttk.Button(self,text='닫기',command=self.close).grid(row=3,padx=16,pady=12,sticky='e')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.poll_id = self.after(100,self.poll)
        def work():
            try:
                run_checks(lambda *args:self.events.put(args),self.stop_event,once)
            except Exception as exc:
                self.events.put((f'알림 실행 중 오류가 발생했습니다.\n{exc}',True,True))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        try:
            event = self.events.get_nowait()
            text, self.done, visible = event[:3]
            alert_now = event[3] if len(event) > 3 else not self.shown
            if not visible and self.done:
                self.close()
                return
            self.body.configure(state='normal')
            self.body.delete('1.0','end')
            self.body.insert('1.0',text)
            self.body.configure(state='disabled')
            self.state_text.set('조회 완료 · 다음 Windows 로그인 시 다시 알립니다.' if self.done else '일부 조회 대기 중 · 닫으면 이번 대기만 중지합니다.')
            if visible and (not self.shown or alert_now):
                self.shown=True
                self.deiconify()
                self.lift()
                self.attributes('-topmost',True)
                if self.top_id is not None:
                    self.after_cancel(self.top_id)
                self.top_id = self.after(2000,lambda: self.attributes('-topmost',False))
                try:
                    import winsound
                    winsound.MessageBeep()
                except RuntimeError:
                    pass
        except queue.Empty:
            pass
        self.poll_id=self.after(200,self.poll)

    def close(self):
        self.stop_event.set()
        if self.top_id is not None:
            self.after_cancel(self.top_id)
        self.after_cancel(self.poll_id)
        self.destroy()

def main():
    once = '--once' in sys.argv
    handle,kernel=acquire_instance(once)
    if handle is None:
        return
    try:
        NotificationWindow(once).mainloop()
    finally:
        kernel.CloseHandle(handle)

if __name__=='__main__':
    main()


