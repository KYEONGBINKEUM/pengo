"""Local file-selection UI; source files never leave the computer."""
import datetime, json, os, queue, subprocess, sys, threading, tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

ROOT=Path(__file__).resolve().parent

def main():
    win=tk.Tk(); win.title('PSD 퍼블리셔 · 회사 전용 MVP'); win.geometry('820x670')
    frame=ttk.Frame(win,padding=24); frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='PSD → PHP · HTML · CSS · JS',font=('Malgun Gothic',20,'bold')).pack(anchor='w')
    ttk.Label(frame,text='새 PSD를 선택하면 코드와 이미지가 들어 있는 폴더 및 ZIP을 만듭니다.\n자동 초안은 검토용이며, 반복 디자인은 레시피를 연결해 재사용할 수 있습니다.').pack(anchor='w',pady=12)
    fields={}
    def row(key,title,types,directory=False):
        ttk.Label(frame,text=title).pack(anchor='w',pady=(10,3)); wrap=ttk.Frame(frame); wrap.pack(fill='x')
        value=tk.StringVar(); fields[key]=value; ttk.Entry(wrap,textvariable=value).pack(side='left',fill='x',expand=True)
        def choose():
            path=filedialog.askdirectory() if directory else filedialog.askopenfilename(filetypes=types)
            if path:value.set(path)
        ttk.Button(wrap,text='선택',command=choose).pack(side='right',padx=(8,0))
    row('psd','1. 디자인 PSD 파일',[('Photoshop','*.psd *.psb')])
    row('zip','2. 기존 소스 ZIP (선택 · 비워두면 저장된 회사 규칙 사용)',[('ZIP','*.zip')])
    row('recipe','3. 반복 구조 레시피 (선택 · 새 PSD는 비워두고 시작)',[('JSON','*.json')])
    row('out','4. 결과를 저장할 위치',[],True); fields['out'].set(str(ROOT/'generated'))
    status=tk.StringVar(value='준비됨'); ttk.Label(frame,textvariable=status).pack(anchor='w',pady=12)
    log=tk.Text(frame,height=8,wrap='word'); log.pack(fill='both',expand=True)
    events=queue.Queue(); last={'out':None}
    def worker(cmd,out):
        try:
            env=dict(os.environ,PYTHONIOENCODING='utf-8')
            p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace',env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for line in p.stdout:events.put(('log',line))
            events.put(('done',p.wait(),out))
        except Exception as e:events.put(('error',str(e)))
    def start():
        psd=Path(fields['psd'].get())
        if not psd.is_file():messagebox.showerror('파일 선택','PSD 파일을 선택해 주세요.'); return
        out=Path(fields['out'].get())/(psd.stem+'-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        cmd=[sys.executable,str(ROOT/'publisher.py'),'build',str(psd),'--out',str(out)]
        for key,flag in [('zip','--source-zip'),('recipe','--recipe')]:
            if fields[key].get():cmd += [flag,fields[key].get()]
        run.config(state='disabled'); status.set('변환 중 · PSD 크기에 따라 몇 분 걸릴 수 있습니다.'); log.delete('1.0','end')
        threading.Thread(target=worker,args=(cmd,out),daemon=True).start()
    def poll():
        while not events.empty():
            event=events.get()
            if event[0]=='log':log.insert('end',event[1]);log.see('end')
            else:
                run.config(state='normal')
                if event[0]=='done' and event[1]==0:status.set('완료 · 결과 열기에서 preview.html을 확인하세요.');last['out']=event[2]
                else:status.set('변환 실패 · 아래 기록을 확인해 주세요.');log.insert('end',str(event))
        win.after(150,poll)
    buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=(15,0))
    run=ttk.Button(buttons,text='코드 생성하기',command=start);run.pack(side='left')
    ttk.Button(buttons,text='결과 폴더 열기',command=lambda:os.startfile(last['out']) if last['out'] else None).pack(side='left',padx=10)
    poll();win.mainloop()

if __name__=='__main__':main()
