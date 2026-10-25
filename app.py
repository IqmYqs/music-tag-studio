import sys, re, io, time, pathlib, threading
from concurrent.futures import ThreadPoolExecutor
import requests
from mutagen import File
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TCON, TDRC, TRCK, APIC, ID3NoHeaderError
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.wave import WAVE
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QDesktopServices
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QFileDialog,QTableWidget,QTableWidgetItem,QHeaderView,QFormLayout,QLineEdit,QLabel,QMessageBox,QCheckBox,QSplitter,QAbstractItemView,QProgressBar,QGroupBox,QScrollArea)
from PySide6.QtCore import QUrl
from auto_batch import AutoWorker
EXTS={'.mp3','.flac','.m4a','.mp4','.ogg','.opus','.wav'}
FIELDS=['title','artist','album','albumartist','genre','date','tracknumber']
KEYS={'title':'TIT2','artist':'TPE1','album':'TALB','albumartist':'TPE2','genre':'TCON','date':'TDRC','tracknumber':'TRCK'}
MP4KEYS={'title':'\xa9nam','artist':'\xa9ART','album':'\xa9alb','albumartist':'aART','genre':'\xa9gen','date':'\xa9day','tracknumber':'trkn'}

def read_tags(path):
    audio=File(path,easy=True)
    result={k:'' for k in FIELDS}
    if audio:
        for k in FIELDS:
            v=audio.get(k,[])
            result[k]=str(v[0]) if v else ''
    return result

def save_tags(path,data,art=None):
    ext=pathlib.Path(path).suffix.lower()
    if ext in ('.mp3','.wav'):
        try: tags=ID3(path)
        except ID3NoHeaderError: tags=ID3()
        constructors={'title':TIT2,'artist':TPE1,'album':TALB,'albumartist':TPE2,'genre':TCON,'date':TDRC,'tracknumber':TRCK}
        for k,cls in constructors.items():
            tags.delall(KEYS[k])
            if data.get(k): tags.add(cls(encoding=3,text=str(data[k])))
        if art:
            tags.delall('APIC'); tags.add(APIC(encoding=3,mime='image/jpeg',type=3,desc='Cover',data=art))
        tags.save(path,v2_version=3)
    elif ext in ('.m4a','.mp4'):
        audio=MP4(path)
        for k,key in MP4KEYS.items():
            if k=='tracknumber':
                val=data.get(k,'').split('/')[0]
                if val.isdigit(): audio[key]=[(int(val),0)]
                elif key in audio: del audio[key]
            elif data.get(k): audio[key]=[str(data[k])]
            elif key in audio: del audio[key]
        if art: audio['covr']=[MP4Cover(art,imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()
    else:
        audio=File(path)
        if audio is None: raise ValueError('Unsupported format')
        for k in FIELDS:
            if data.get(k): audio[k]=[str(data[k])]
            elif k in audio: del audio[k]
        if art:
            if isinstance(audio,FLAC):
                pic=Picture(); pic.data=art; pic.type=3; pic.mime='image/jpeg'; audio.clear_pictures(); audio.add_picture(pic)
            else:
                import base64
                pic=Picture(); pic.data=art; pic.type=3; pic.mime='image/jpeg'
                audio['metadata_block_picture']=[base64.b64encode(pic.write()).decode('ascii')]
        audio.save()

class ScanWorker(QThread):
    item=Signal(str,dict); done=Signal(int); failed=Signal(str)
    def __init__(self,folder): super().__init__(); self.folder=folder
    def run(self):
        n=0
        try:
            for p in pathlib.Path(self.folder).rglob('*'):
                if self.isInterruptionRequested(): break
                if p.is_file() and p.suffix.lower() in EXTS:
                    try: self.item.emit(str(p),read_tags(str(p))); n+=1
                    except Exception: continue
        except Exception as e: self.failed.emit(str(e))
        self.done.emit(n)

class LookupWorker(QThread):
    result=Signal(dict,object,str); error=Signal(str)
    def __init__(self,query): super().__init__(); self.query=query
    def run(self):
        try:
            headers={'User-Agent':'MusicTagStudio/1.0 (personal desktop application)'}
            r=requests.get('https://musicbrainz.org/ws/2/recording/',params={'query':self.query,'fmt':'json','limit':8},headers=headers,timeout=20); r.raise_for_status()
            recordings=r.json().get('recordings',[])
            if not recordings: self.error.emit('ไม่พบข้อมูลจาก MusicBrainz'); return
            rec=recordings[0]
            artists=', '.join(x.get('name','') for x in rec.get('artist-credit',[]) if isinstance(x,dict))
            release=(rec.get('releases') or [{}])[0]
            album=release.get('title',''); release_id=release.get('id','')
            data={'title':rec.get('title',''),'artist':artists,'album':album,'albumartist':artists,'date':release.get('date',''),'genre':'','tracknumber':''}
            art=None
            if release_id:
                try:
                    cr=requests.get(f'https://coverartarchive.org/release/{release_id}/front-250',headers=headers,timeout=15)
                    if cr.ok and cr.headers.get('content-type','').startswith('image/'):
                        from PySide6.QtGui import QImage
                        img=QImage.fromData(cr.content)
                        if not img.isNull():
                            from PySide6.QtCore import QBuffer,QIODevice
                            buffer=QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly); img.save(buffer,'JPEG',90); art=bytes(buffer.data())
                except requests.RequestException: pass
            self.result.emit(data,art,f"MusicBrainz: {rec.get('title','')} — {artists} (score {rec.get('score','?')})")
        except Exception as e: self.error.emit(str(e))

class Window(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('Music Tag Studio — Windows'); self.resize(1200,760)
        self.cover=None; self.current_path=None; self.worker=None; self.lookup=None; self.auto_worker=None; self.proposals={}; self.auto_mode=None
        root=QWidget(); self.setCentralWidget(root); main=QVBoxLayout(root)
        bar=QHBoxLayout(); main.addLayout(bar)
        self.open_btn=QPushButton('📁 เลือกโฟลเดอร์เพลง'); self.open_btn.clicked.connect(self.choose); bar.addWidget(self.open_btn)
        self.filename_btn=QPushButton('แยกชื่อไฟล์ → Tags'); self.filename_btn.clicked.connect(self.from_filename); bar.addWidget(self.filename_btn)
        self.batch_btn=QPushButton('ใช้ Artist / Album กับไฟล์ที่เลือก'); self.batch_btn.clicked.connect(self.batch); bar.addWidget(self.batch_btn)
        self.preview_btn=QPushButton('🔎 Auto Match ที่ติ๊ก'); self.preview_btn.clicked.connect(self.auto_preview); bar.addWidget(self.preview_btn)
        self.apply_btn=QPushButton('✅ Apply ที่ติ๊ก'); self.apply_btn.clicked.connect(self.auto_apply); bar.addWidget(self.apply_btn)
        self.all_btn=QPushButton('เลือกทั้งหมด'); self.all_btn.clicked.connect(lambda:self.check_all(True)); bar.addWidget(self.all_btn)
        self.none_btn=QPushButton('ยกเลิกเลือก'); self.none_btn.clicked.connect(lambda:self.check_all(False)); bar.addWidget(self.none_btn)
        bar.addStretch()
        self.status=QLabel('เลือกโฟลเดอร์เพื่อเริ่มต้น'); main.addWidget(self.status)
        splitter=QSplitter(); main.addWidget(splitter,1)
        left=QWidget(); lv=QVBoxLayout(left); splitter.addWidget(left)
        self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(['เลือก','ชื่อไฟล์','นักร้อง / Artist','ชื่อเพลง / Title','อัลบั้ม / Album','Path','สถานะ Auto']); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive); self.table.setColumnWidth(0,55); self.table.setColumnWidth(1,200); self.table.setColumnWidth(2,170); self.table.setColumnWidth(3,190); self.table.setColumnWidth(4,190); self.table.setColumnWidth(5,280); self.table.setColumnWidth(6,170)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self.load_selected); lv.addWidget(self.table)
        right=QWidget(); rv=QVBoxLayout(right); splitter.addWidget(right); splitter.setSizes([750,450])
        self.path_label=QLabel('ยังไม่ได้เลือกเพลง'); self.path_label.setWordWrap(True); rv.addWidget(self.path_label)
        form=QFormLayout(); rv.addLayout(form); self.edits={}
        names={'title':'Title','artist':'Artist','album':'Album','albumartist':'Album Artist','genre':'Genre','date':'Year / Date','tracknumber':'Track #'}
        for k in FIELDS:
            e=QLineEdit(); self.edits[k]=e; form.addRow(names[k],e)
        self.art_label=QLabel('ยังไม่มีรูปปกที่ค้นหา'); self.art_label.setAlignment(Qt.AlignmentFlag.AlignCenter); self.art_label.setMinimumHeight(170); self.art_label.setStyleSheet('border: 1px solid #888;'); rv.addWidget(self.art_label)
        qbar=QHBoxLayout(); rv.addLayout(qbar); self.search=QLineEdit(); self.search.setPlaceholderText('ค้นหา เช่น Artist - Song'); qbar.addWidget(self.search)
        btn=QPushButton('ค้นหาเพลง + ปก'); btn.clicked.connect(self.find_online); qbar.addWidget(btn)
        manual=QPushButton('เลือกรูปปกจากเครื่อง'); manual.clicked.connect(self.choose_cover); rv.addWidget(manual)
        save=QPushButton('💾 บันทึก Tags + ปกลงไฟล์'); save.clicked.connect(self.save); rv.addWidget(save)
        explorer=QPushButton('เปิดตำแหน่งไฟล์'); explorer.clicked.connect(self.reveal); rv.addWidget(explorer)
        self.info=QLabel('ตรวจสอบผลการค้นหาก่อนบันทึกเสมอ'); self.info.setWordWrap(True); rv.addWidget(self.info); rv.addStretch()
        self.setStyleSheet('QPushButton{padding:8px} QLineEdit{padding:6px} QTableWidget{gridline-color:#ddd}')
    def choose(self):
        folder=QFileDialog.getExistingDirectory(self,'เลือกโฟลเดอร์เพลง')
        if not folder: return
        self.table.setRowCount(0); self.proposals.clear(); self.current_path=None; self.open_btn.setEnabled(False); self.status.setText('กำลังสแกน...')
        self.worker=ScanWorker(folder); self.worker.item.connect(self.add_item); self.worker.done.connect(self.scan_done); self.worker.failed.connect(lambda m:QMessageBox.warning(self,'Scan error',m)); self.worker.start()
    def add_item(self,path,tags):
        row=self.table.rowCount(); self.table.insertRow(row)
        vals=['',pathlib.Path(path).name,tags['artist'],tags['title'],tags['album'],path,'ยังไม่ค้นหา']
        for i,v in enumerate(vals):
            item=QTableWidgetItem(v); item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if i==0: item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable); item.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row,i,item)
    def scan_done(self,n): self.open_btn.setEnabled(True); self.status.setText(f'พบ {n} ไฟล์เพลง')
    def load_selected(self):
        rows=sorted(set(i.row() for i in self.table.selectedIndexes()))
        if not rows: return
        row=rows[0]; self.current_path=self.table.item(row,5).text(); self.path_label.setText(self.current_path)
        try: data=read_tags(self.current_path)
        except Exception as e: self.info.setText(str(e)); return
        for k in FIELDS: self.edits[k].setText(data[k])
        self.cover=None; self.art_label.setPixmap(QPixmap()); self.art_label.setText('ยังไม่ได้เลือกรูปปกใหม่')
        self.search.setText(' - '.join(x for x in [data['artist'],data['title'] or pathlib.Path(self.current_path).stem] if x))
    def from_filename(self):
        if not self.current_path: return
        stem=pathlib.Path(self.current_path).stem
        parts=re.split(r'\s+[-–—]\s+',stem,maxsplit=1)
        if len(parts)==2: self.edits['artist'].setText(parts[0]); self.edits['title'].setText(parts[1])
        else: self.edits['title'].setText(stem)
    def find_online(self):
        if not self.current_path: return
        q=self.search.text().strip()
        if not q: return
        self.info.setText('กำลังค้นหา MusicBrainz...')
        self.lookup=LookupWorker(q); self.lookup.result.connect(self.found); self.lookup.error.connect(lambda m:self.info.setText('ค้นหาไม่สำเร็จ: '+m)); self.lookup.start()
    def found(self,data,art,info):
        self.info.setText(info+'\nตรวจสอบชื่อศิลปินและอัลบั้มก่อนบันทึก')
        for k,v in data.items():
            if v: self.edits[k].setText(v)
        if art: self.set_cover(art)
        else: self.cover=None; self.art_label.setPixmap(QPixmap()); self.art_label.setText('ไม่พบปกอัลบั้ม')
    def set_cover(self,bytes_data):
        self.cover=bytes_data; pix=QPixmap(); pix.loadFromData(bytes_data); self.art_label.setPixmap(pix.scaled(190,190,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    def choose_cover(self):
        path,_=QFileDialog.getOpenFileName(self,'เลือกรูปปก','','Images (*.jpg *.jpeg *.png *.webp)')
        if not path: return
        from PySide6.QtGui import QImage
        from PySide6.QtCore import QBuffer,QIODevice
        img=QImage(path)
        if img.isNull(): QMessageBox.warning(self,'Error','อ่านรูปไม่ได้'); return
        buffer=QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly); img.save(buffer,'JPEG',90); self.set_cover(bytes(buffer.data()))
    def save(self):
        if not self.current_path: return
        data={k:e.text().strip() for k,e in self.edits.items()}
        try:
            save_tags(self.current_path,data,self.cover)
            row=self.table.currentRow()
            for i,k in [(3,'title'),(2,'artist'),(4,'album')]: self.table.item(row,i).setText(data[k])
            self.info.setText('บันทึกสำเร็จ: '+self.current_path)
        except Exception as e: QMessageBox.critical(self,'Save failed',str(e))
    def batch(self):
        rows=sorted(set(i.row() for i in self.table.selectedIndexes()))
        if not rows: return
        artist=self.edits['artist'].text().strip(); album=self.edits['album'].text().strip()
        if not artist and not album: return
        answer=QMessageBox.question(self,'Batch update',f'อัปเดต Artist / Album ให้ {len(rows)} ไฟล์?\n(ไม่เปลี่ยน Title และรูปปก)')
        if answer!=QMessageBox.StandardButton.Yes: return
        success=0; errors=[]
        for row in rows:
            path=self.table.item(row,5).text()
            try:
                data=read_tags(path)
                if artist: data['artist']=artist
                if album: data['album']=album
                save_tags(path,data)
                if artist: self.table.item(row,2).setText(artist)
                if album: self.table.item(row,4).setText(album)
                success+=1
            except Exception as e: errors.append(f'{path}: {e}')
        QMessageBox.information(self,'Batch result',f'สำเร็จ {success}/{len(rows)} ไฟล์'+ ('\nข้อผิดพลาด:\n'+'\n'.join(errors[:5]) if errors else ''))
    def check_all(self,checked):
        for row in range(self.table.rowCount()):
            self.table.item(row,0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    def checked_rows(self):
        return [i for i in range(self.table.rowCount()) if self.table.item(i,0).checkState()==Qt.CheckState.Checked]
    def set_busy(self,busy):
        for b in (self.open_btn,self.preview_btn,self.apply_btn,self.all_btn,self.none_btn):b.setEnabled(not busy)
    def auto_preview(self):
        if self.auto_worker and self.auto_worker.isRunning():return
        rows=self.checked_rows()
        if not rows:return QMessageBox.information(self,'Auto Match','กรุณาติ๊กเลือกเพลง')
        items=[]
        for row in rows:
            path=self.table.item(row,5).text()
            try: tags=read_tags(path)
            except Exception as e:self.table.item(row,6).setText(f'อ่านไม่ได้: {e}');continue
            items.append((row,path,tags,None));self.table.item(row,6).setText('กำลังค้นหา...')
            self.proposals.pop(path,None)
        self.start_auto(items,'preview')
    def auto_apply(self):
        if self.auto_worker and self.auto_worker.isRunning():return
        rows=self.checked_rows();items=[]
        for row in rows:
            path=self.table.item(row,5).text()
            if path in self.proposals:items.append((row,path,{},self.proposals[path]))
        if not items:return QMessageBox.information(self,'Apply','กด Auto Match ก่อน แล้วตรวจสอบข้อมูลที่พบ')
        answer=QMessageBox.question(self,'ยืนยันการบันทึก',f'จะเขียน Metadata ลงในไฟล์จริง {len(items)} เพลง และฝังปกเมื่อพบ\nควรสำรองไฟล์ก่อนดำเนินการ ยืนยันหรือไม่?')
        if answer!=QMessageBox.StandardButton.Yes:return
        self.start_auto(items,'apply')
    def start_auto(self,items,mode):
        self.auto_mode=mode;self.set_busy(True)
        self.auto_worker=AutoWorker(items,mode,save_tags)
        self.auto_worker.progress.connect(self.auto_progress)
        self.auto_worker.finished_batch.connect(self.auto_done)
        self.auto_worker.start()
    def auto_progress(self,row,path,proposal,message):
        if row>=self.table.rowCount() or self.table.item(row,5).text()!=path:return
        self.table.item(row,6).setText(message)
        if self.auto_mode=='preview' and proposal:
            self.proposals[path]=proposal
            data=proposal['data']
            self.table.item(row,2).setText(data['artist'])
            self.table.item(row,3).setText(data['title'])
            self.table.item(row,4).setText(data['album'])
        elif self.auto_mode=='apply' and message.startswith('บันทึกสำเร็จ'):
            self.proposals.pop(path,None)
        self.status.setText(f'{self.auto_mode}: {pathlib.Path(path).name} — {message}')
    def auto_done(self,ok,failed):
        self.set_busy(False)
        self.status.setText(f'{self.auto_mode} เสร็จ: ประมวลผล {ok} / ผิดพลาด {failed} (ดูสถานะรายเพลง)')
    def reveal(self):
        if self.current_path:
            import subprocess
            subprocess.Popen(['explorer.exe','/select,',str(pathlib.Path(self.current_path))])

if __name__=='__main__':
    app=QApplication(sys.argv); app.setStyle('Fusion'); w=Window(); w.show(); sys.exit(app.exec())
