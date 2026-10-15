"""Run with python app.py. All Tk calls stay on the main thread."""
from datetime import date, timedelta
from pathlib import Path
from queue import Queue, Empty
from threading import Thread
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from stock_data import validate_dates, retrieve, save_excel


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('주식 데이터 → Excel')
        self.geometry('680x480')
        self.minsize(620, 460)
        self.messages = Queue()
        self.busy = False
        self.stock = tk.StringVar(value='삼성전자')
        self.start = tk.StringVar(value=(date.today() - timedelta(days=365)).isoformat())
        self.end = tk.StringVar(value=date.today().isoformat())
        self.interval = tk.StringVar(value='일봉')
        self.status = tk.StringVar(value='종목과 기간을 입력한 뒤 저장 버튼을 눌러 주세요.')
        frame = ttk.Frame(self, padding=28)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text='주식 데이터를 Excel로', font=('맑은 고딕', 20, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))
        ttk.Label(frame, text='국내 상장 주식 · 시가 / 고가 / 저가 / 종가 / 거래량').grid(row=1, column=0, columnspan=2, sticky='w', pady=(0, 22))
        self.controls = []
        for i, (label, variable) in enumerate([('종목명 또는 코드', self.stock), ('시작일 (YYYY-MM-DD)', self.start), ('종료일 (YYYY-MM-DD)', self.end)], 2):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky='w', padx=(0, 18), pady=9)
            entry = ttk.Entry(frame, textvariable=variable, font=('맑은 고딕', 11))
            entry.grid(row=i, column=1, sticky='ew')
            self.controls.append(entry)
        ttk.Label(frame, text='데이터 주기').grid(row=5, column=0, sticky='w', pady=12)
        choices = ttk.Frame(frame)
        choices.grid(row=5, column=1, sticky='w')
        for value in ('일봉', '주봉', '월봉'):
            button = ttk.Radiobutton(choices, text=value, variable=self.interval, value=value)
            button.pack(side='left', padx=(0, 22))
            self.controls.append(button)
        ttk.Label(frame, text='예: 삼성전자, SK하이닉스, 005930\n주·월봉은 선택 기간 내 거래일만 집계합니다. 종료일도 포함합니다.', foreground='#586577').grid(row=6, column=0, columnspan=2, sticky='w', pady=10)
        self.button = ttk.Button(frame, text='데이터 가져오기 및 Excel 저장', command=self.start_job)
        self.button.grid(row=7, column=0, columnspan=2, sticky='ew', pady=12)
        self.controls.append(self.button)
        self.progress = ttk.Progressbar(frame, mode='indeterminate')
        self.progress.grid(row=8, column=0, columnspan=2, sticky='ew')
        ttk.Label(frame, textvariable=self.status, wraplength=590).grid(row=9, column=0, columnspan=2, sticky='w', pady=12)
        self.after(150, self.poll)

    def start_job(self):
        if self.busy:
            return
        try:
            start, end = validate_dates(self.start.get().strip(), self.end.get().strip())
            query = self.stock.get().strip()
            if not query:
                raise ValueError('주식 이름 또는 종목코드를 입력해 주세요.')
        except ValueError as exc:
            messagebox.showerror('입력 확인', str(exc), parent=self)
            return
        interval = self.interval.get()
        path = filedialog.asksaveasfilename(parent=self, title='Excel 저장 위치', defaultextension='.xlsx', filetypes=[('Excel 통합 문서', '*.xlsx')], initialfile=f'주가_{start}_{end}_{interval}.xlsx')
        if not path:
            return
        self.busy = True
        for control in self.controls:
            control.state(['disabled'])
        self.progress.start()
        self.status.set('종목 확인 및 데이터 조회 중입니다…')
        Thread(target=self.worker, args=(query, start, end, interval, path), daemon=True).start()

    def worker(self, query, start, end, interval, path):
        try:
            code, name, rows = retrieve(query, start, end, interval)
            save_excel(path, rows, code, name, start, end, interval)
            self.messages.put((True, f'{name} ({code}) · {len(rows):,}개 {interval} 저장 완료\n{Path(path).resolve()}'))
        except PermissionError:
            self.messages.put((False, '파일이 Excel에서 열려 있거나 쓰기 권한이 없습니다. 파일을 닫거나 다른 저장 위치를 선택해 주세요.'))
        except Exception as exc:
            self.messages.put((False, f'{exc}\n\n인터넷 연결, 종목명, 조회 기간을 확인해 주세요. 종목명 조회에 실패하면 종목코드로 시도할 수 있습니다.'))

    def poll(self):
        try:
            ok, message = self.messages.get_nowait()
        except Empty:
            pass
        else:
            self.busy = False
            self.progress.stop()
            for control in self.controls:
                control.state(['!disabled'])
            self.status.set(message if ok else '저장하지 못했습니다. 입력값 또는 연결 상태를 확인해 주세요.')
            (messagebox.showinfo if ok else messagebox.showerror)('저장 완료' if ok else '조회 / 저장 실패', message, parent=self)
        self.after(150, self.poll)


if __name__ == '__main__':
    App().mainloop()
