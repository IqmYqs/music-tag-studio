import pathlib, re, time
import requests
from PySide6.QtCore import QThread, Signal
from mutagen import File

HEADERS={'User-Agent':'MusicTagStudio/2.0 (desktop personal music tag editor; contact: music-tag-studio@example.org)'}

def candidate_query(path, tags):
    stem=pathlib.Path(path).stem
    stem=re.sub(r'(?i)\b(official|lyrics?|audio|video|hd|320kbps|mp3)\b',' ',stem)
    stem=re.sub(r'\s*[\[(].*?[\])]\s*',' ',stem).strip()
    bits=re.split(r'\s+[-–—]\s+',stem,maxsplit=1)
    artist=tags.get('artist','') or (bits[0] if len(bits)==2 else '')
    title=tags.get('title','') or (bits[1] if len(bits)==2 else stem)
    return artist.strip(),title.strip()

def lookup(session,path,tags):
    artist,title=candidate_query(path,tags)
    if not title: return None,'ไม่มีชื่อสำหรับค้นหา'
    query=f'recording:"{title.replace(chr(34), "")}"'
    if artist: query+=f' AND artist:"{artist.replace(chr(34), "")}"'
    r=session.get('https://musicbrainz.org/ws/2/recording/',params={'query':query,'fmt':'json','limit':5},timeout=22)
    r.raise_for_status()
    recordings=r.json().get('recordings',[])
    if not recordings: return None,'ไม่พบผลลัพธ์'
    rec=recordings[0]; score=int(rec.get('score',0))
    if score<90: return None,f'คะแนนตรงกันต่ำ ({score})'
    artists=', '.join(a.get('name','') for a in rec.get('artist-credit',[]) if isinstance(a,dict))
    releases=rec.get('releases') or []
    release=next((x for x in releases if x.get('id') and x.get('title')),None)
    if not release: return None,'ไม่พบอัลบั้ม'
    data=dict(tags)
    data.update(title=rec.get('title') or tags['title'],artist=artists or tags['artist'],album=release['title'],albumartist=artists or tags['albumartist'],date=release.get('date') or tags['date'])
    return {'data':data,'release_id':release['id'],'score':score,'art':None},'พร้อมใช้'

def cover(session,release_id):
    if not release_id:return None
    try:
        r=session.get(f'https://coverartarchive.org/release/{release_id}/front-500',timeout=15)
        if r.ok and r.headers.get('content-type','').startswith('image/'):
            from PySide6.QtGui import QImage
            from PySide6.QtCore import QBuffer,QIODevice
            img=QImage.fromData(r.content)
            if not img.isNull():
                buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                if img.save(buffer,'JPEG',90):return bytes(buffer.data())
    except requests.RequestException:pass
    return None

class AutoWorker(QThread):
    progress=Signal(int,str,object,str)
    finished_batch=Signal(int,int)
    def __init__(self,items,mode,save_function):
        super().__init__();self.items=items;self.mode=mode;self.save_function=save_function
    def run(self):
        ok=0; failed=0
        with requests.Session() as session:
            session.headers.update(HEADERS)
            for idx,path,tags,proposal in self.items:
                if self.isInterruptionRequested():break
                try:
                    if self.mode=='preview':
                        proposal,msg=lookup(session,path,tags)
                        self.progress.emit(idx,path,proposal,msg)
                        time.sleep(1.1) # MusicBrainz public API: max ~1 request/second
                    else:
                        if proposal is None:raise ValueError('ยังไม่มีผลการค้นหา')
                        art=cover(session,proposal['release_id'])
                        self.save_function(path,proposal['data'],art)
                        self.progress.emit(idx,path,proposal,'บันทึกสำเร็จ'+(' + ปก' if art else ' (ไม่พบปก)'))
                    ok+=1
                except Exception as e:
                    failed+=1;self.progress.emit(idx,path,None,f'ผิดพลาด: {e}')
        self.finished_batch.emit(ok,failed)
