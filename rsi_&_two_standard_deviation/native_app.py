import json
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from native_core import MODES, analyze, prepare, describe
from storage import list_records as _list, save as _save, delete as _delete
from functools import partial
from pathlib import Path
DB = Path(__file__).parent / 'data' / 'desktop.sqlite3'
list_records = partial(_list, path=DB)
save = partial(_save, path=DB)
delete = partial(_delete, path=DB)

class App(tk.Tk):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.title('RSI 전용 프로그램' if kind == 'RSI' else 'Z-score 전용 프로그램')
        self.geometry('900x900')
        self.minsize(740, 700)
        self.snapshot = None
        self.active_id = None
        self.jobs = queue.Queue()
        self.vars = {}
        self.columnconfigure(0, weight=1)
        frame = ttk.Frame(self, padding=18)
        frame.grid(sticky='nsew')
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text=self.title(), font=('맑은 고딕', 18, 'bold')).grid(row=0, columnspan=2, sticky='w', pady=10)
        self.field(frame, 1, '주식 이름 (미국 티커)', 'symbol', 'TQQQ')
        self.field(frame, 2, 'RSI 기간 (거래일)' if kind == 'RSI' else '표준편차 n (Z-score 기준)', 'number', '14' if kind == 'RSI' else '2')
        self.range_frame = ttk.Frame(frame)
        self.range_frame.grid(row=4, columnspan=2, sticky='ew', pady=8)
        self.mode = tk.StringVar(value=MODES['dates'])
        if kind == 'Z-score':
            ttk.Label(frame, text='종가 데이터 기간').grid(row=3, column=0, sticky='w')
            combo = ttk.Combobox(frame, textvariable=self.mode, values=list(MODES.values()), state='readonly', width=46)
            combo.grid(row=3, column=1, sticky='ew')
            combo.bind('<<ComboboxSelected>>', lambda e: self.show_range())
        self.show_range()
        self.run_button = ttk.Button(frame, text='조회 / 계산', command=self.run)
        self.run_button.grid(row=5, columnspan=2, sticky='ew', pady=8)
        self.status = tk.StringVar(value='종목과 조건을 입력하고 조회하세요. 주말·휴장일·미완료 당일 종가는 제외합니다.')
        ttk.Label(frame, textvariable=self.status, wraplength=820).grid(row=6, columnspan=2, sticky='w')
        self.output = tk.Text(frame, height=14, wrap='word', font=('맑은 고딕', 11), state='disabled')
        self.output.grid(row=7, columnspan=2, sticky='ew', pady=10)
        self.canvas = tk.Canvas(frame, height=170, bg='#162536', highlightthickness=0)
        self.canvas.grid(row=8, columnspan=2, sticky='ew')
        self.canvas.bind('<Configure>', lambda e: self.draw())
        self.field(frame, 9, '저장 이름', 'name', kind + ' 분석')
        self.saved = ttk.Combobox(frame, state='readonly')
        self.saved.grid(row=10, columnspan=2, sticky='ew', pady=6)
        buttons = ttk.Frame(frame)
        buttons.grid(row=11, columnspan=2, sticky='ew')
        for title, command in [('새로 저장', lambda: self.persist(False)), ('불러오기', self.load),
                               ('업데이트', lambda: self.persist(True)), ('삭제', self.remove)]:
            ttk.Button(buttons, text=title, command=command).pack(side='left', padx=4)
        self.refresh()
        self._poll_id = self.after(100, self.poll)

    def destroy(self):
        if hasattr(self, '_poll_id'):
            self.after_cancel(self._poll_id)
        super().destroy()

    def field(self, parent, row, label, key, default):
        variable = self.vars.setdefault(key, tk.StringVar(value=default))
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=4, pady=4)
        ttk.Entry(parent, textvariable=variable, width=35).grid(row=row, column=1, sticky='ew', padx=4, pady=4)

    def show_range(self):
        for widget in self.range_frame.winfo_children():
            widget.destroy()
        if self.kind == 'RSI':
            return
        mode = self.mode_key()
        if mode in ('dates', 'since'):
            self.field(self.range_frame, 0, '시작일 (YYYY-MM-DD)', 'start_date', '2018-05-09')
            if mode == 'dates':
                self.field(self.range_frame, 1, '종료일 (YYYY-MM-DD)', 'end_date', '2020-12-30')
        elif mode == 'exclude':
            self.field(self.range_frame, 0, '제외 시작일 (YYYY-MM-DD)', 'exclude_start', '2020-01-01')
            self.field(self.range_frame, 1, '제외 종료일 (YYYY-MM-DD)', 'exclude_end', '2020-12-31')
        elif mode == 'calendar':
            for row, (key, label, value) in enumerate([('years','년','1'), ('months','개월','0'), ('days','일','0')]):
                self.field(self.range_frame, row, label, key, value)

    def mode_key(self):
        return next(k for k,v in MODES.items() if v == self.mode.get())

    def config(self):
        c = dict(kind=self.kind, symbol=self.vars['symbol'].get().strip().upper(), operator='<=', threshold=30.0)
        try:
            if self.kind == 'RSI':
                c['period'] = int(self.vars['number'].get())
            else:
                c['threshold'] = float(self.vars['number'].get())
                c['period_mode'] = mode = self.mode_key()
                keys = {'dates':['start_date','end_date'], 'since':['start_date'], 'exclude':['exclude_start','exclude_end'],
                        'calendar':['years','months','days'], 'listing':[]}[mode]
                for key in keys:
                    c[key] = int(self.vars[key].get()) if mode == 'calendar' else self.vars[key].get().strip()
            prepare(c)
        except (ValueError, KeyError) as exc:
            raise ValueError('입력을 확인하세요. ' + str(exc))
        return c

    def run(self):
        try:
            config = self.config()
        except ValueError as exc:
            messagebox.showerror('입력 확인', str(exc))
            return
        self.run_button.state(['disabled'])
        self.status.set('종가를 조회하고 있습니다…')
        self.snapshot = None
        self.set_output('')
        self.draw()
        def work():
            try:
                self.jobs.put((True, analyze(config)))
            except Exception as exc:
                self.jobs.put((False, str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            ok, value = self.jobs.get_nowait()
            self.run_button.state(['!disabled'])
            if ok:
                self.snapshot = value
                self.set_output(describe(value))
                self.status.set('조회 완료. 결과는 조회 당시 조건 기준이며 저장할 수 있습니다.')
                self.draw()
            else:
                self.status.set('조회 실패')
                messagebox.showerror('조회 오류', value)
        except queue.Empty:
            pass
        self._poll_id = self.after(100, self.poll)

    def set_output(self, text):
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.insert('1.0', text)
        self.output.configure(state='disabled')

    def draw(self):
        c = self.canvas
        c.delete('all')
        if not self.snapshot:
            return
        r = self.snapshot['result']
        w = max(c.winfo_width(), 700)
        if self.kind == 'RSI':
            panels = [('종가', [x['close'] for x in r['observations']]),
                      ('RSI', [x['rsi'] for x in r.get('rsi_history', [])])]
        else:
            panels = [('분석 구간 종가 (제외 날짜는 생략)', [x['close'] for x in r['observations']])]
        for i,(title, values) in enumerate(panels):
            if not values:
                continue
            left, width = 45+i*w/len(panels), w/len(panels)-70
            low, high = (0,100) if title == 'RSI' else (min(values),max(values))
            span = high-low or 1
            c.create_text(left,12,text=title,anchor='w',fill='white')
            c.create_text(left,32,text=f'{high:.2f}',anchor='w',fill='#aaaaaa')
            c.create_text(left,150,text=f'{low:.2f}',anchor='w',fill='#aaaaaa')
            points = []
            for j,value in enumerate(values):
                points.extend([left+width*j/max(1,len(values)-1), 140-(value-low)/span*95])
            if len(values)>1:
                c.create_line(*points, fill='#66bbff', width=2)
            else:
                x,y=points
                c.create_oval(x-3,y-3,x+3,y+3,fill='#66bbff')

    def refresh(self):
        self.records = [r for r in list_records() if json.loads(r['config'])['kind'] == self.kind]
        self.saved['values'] = [f"{r['name']} (#{r['id']})" for r in self.records]
        if self.records:
            self.saved.current(0)
        else:
            self.saved.set('')

    def selected(self):
        index = self.saved.current()
        if index < 0:
            raise ValueError('저장 항목을 선택하세요.')
        return self.records[index]

    def persist(self, update):
        try:
            c = self.config()
            if update and self.active_id is None:
                raise ValueError('업데이트할 항목을 먼저 불러오세요.')
            snapshot = self.snapshot if self.snapshot and self.snapshot['config']==c else None
            self.active_id = save(self.vars['name'].get(), c, snapshot, self.active_id if update else None)
            self.refresh()
            self.status.set('조건과 결과를 저장했습니다.' if snapshot else '조건을 저장했습니다. 변경한 조건의 결과는 다시 조회하세요.')
        except Exception as exc:
            messagebox.showerror('저장 오류', str(exc))

    def load(self):
        try:
            record = self.selected()
            c = json.loads(record['config'])
            if self.kind == 'Z-score' and c.get('period_mode') not in MODES:
                raise ValueError('이전 거래일 방식 항목입니다. 기존 앱에서 확인하세요.')
            if self.kind == 'Z-score':
                self.mode.set(MODES[c['period_mode']])
                self.show_range()
            for key, value in c.items():
                if key in self.vars:
                    self.vars[key].set(str(value))
            self.vars['number'].set(str(c['period'] if self.kind=='RSI' else c['threshold']))
            self.vars['name'].set(record['name'])
            self.active_id = record['id']
            self.snapshot = json.loads(record['snapshot']) if record['snapshot'] else None
            self.set_output(describe(self.snapshot) if self.snapshot else '저장된 조건입니다. 조회 버튼을 누르세요.')
            self.status.set('저장 당시 결과입니다. 현재 값은 다시 조회하세요.')
            self.draw()
        except Exception as exc:
            messagebox.showerror('불러오기 오류', str(exc))

    def remove(self):
        try:
            record = self.selected()
            delete(record['id'])
            if self.active_id == record['id']:
                self.active_id = None
            self.refresh()
            self.status.set('삭제했습니다.')
        except Exception as exc:
            messagebox.showerror('삭제 오류', str(exc))

if __name__ == '__main__':
    App('RSI' if '--rsi' in sys.argv else 'Z-score').mainloop()



