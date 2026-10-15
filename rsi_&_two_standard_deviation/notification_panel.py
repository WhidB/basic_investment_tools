import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
import notifications as alerts

def open_manager(parent):
    win=tk.Toplevel(parent)
    win.title('로그인 종가 알림 관리')
    win.geometry('850x430')
    win.columnconfigure(0,weight=1)
    win.rowconfigure(1,weight=1)
    state=tk.StringVar()
    ttk.Label(win,textvariable=state,wraplength=800).grid(row=0,padx=12,pady=10,sticky='w')
    listing=tk.Listbox(win,font=('맑은 고딕',11),exportselection=False)
    listing.grid(row=1,column=0,padx=12,sticky='nsew')
    scroll=ttk.Scrollbar(win,command=listing.yview)
    scroll.grid(row=1,column=1,sticky='ns')
    listing.configure(yscrollcommand=scroll.set)
    items=[]
    def refresh():
        nonlocal items
        items=alerts.rules()
        listing.delete(0,'end')
        for r in items:
            listing.insert('end', f"#{r['id']} {alerts.rule_label(r)} · {r['name']}")
        state.set(f"자동 시작: {'켜짐' if alerts.startup_enabled() else '꺼짐'} · 등록 {len(items)}개\n인터넷: 기존 방식으로 조회·재시도 / VPN: 주가 서버 연결 성공까지 조용히 대기합니다.")
        parent.refresh_alert_status()
    def selected():
        indices=listing.curselection()
        if not indices:
            raise ValueError('알림 목록에서 항목을 선택하세요.')
        return items[indices[0]]
    def action(fn):
        try:
            fn()
            refresh()
        except Exception as exc:
            messagebox.showerror('알림 관리',str(exc),parent=win)
    def load():
        r=selected()
        if r['config']['kind']!=parent.kind:
            raise ValueError('이 항목은 해당 지표의 전용 프로그램에서 수정하세요.')
        parent.load_alert(r)
        win.destroy()
    def remove():
        r=selected()
        alerts.unregister(r['id'])
        if parent.alert_id==r['id']:
            parent.alert_id=None
    def enable():
        if not alerts.rules():
            raise ValueError('먼저 알림받기 버튼으로 조건을 등록하세요.')
        alerts.set_startup(True)
    def history():
        view=tk.Toplevel(win)
        view.title('마지막 알림 결과')
        view.geometry('760x600')
        text=ScrolledText(view,wrap='word',font=('맑은 고딕',11))
        text.pack(fill='both',expand=True)
        text.insert('1.0',alerts.last_report())
        text.configure(state='disabled')
    def safely(fn):
        try:
            fn()
        except Exception as exc:
            messagebox.showerror('알림 관리',str(exc),parent=win)
    buttons=ttk.Frame(win)
    buttons.grid(row=2,padx=12,pady=12,sticky='ew')
    for label,fn in [('설정 불러와 수정',load),('선택 알림 해제',lambda:action(remove)),
                     ('지금 알림 확인',lambda:action(alerts.launch_now)),('마지막 결과',history)]:
        ttk.Button(buttons,text=label,command=(lambda f=fn: safely(f))).pack(side='left',padx=3)
    bottom=ttk.Frame(win)
    bottom.grid(row=3,padx=12,pady=6,sticky='w')
    ttk.Button(bottom,text='전체 자동 알림 일시정지',command=lambda:action(lambda:alerts.set_startup(False))).pack(side='left',padx=3)
    ttk.Button(bottom,text='전체 자동 알림 다시 켜기',command=lambda:action(enable)).pack(side='left',padx=3)
    ttk.Label(win,text='설정한 표준편차 값을 그대로 사용합니다. 원하는 알림받기(인터넷/VPN) 버튼으로 수정합니다.\n저장 데이터와 알림 등록은 별도이며, 마지막 알림 해제 시 자동 시작도 해제합니다.',wraplength=800).grid(row=4,padx=12,pady=8,sticky='w')
    refresh()

