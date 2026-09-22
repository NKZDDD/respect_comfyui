import base64
import io
from pathlib import Path

from PIL import Image
import pytest

from core import assets, batch, distribution, release, uploader
from core.providers.aicopy import AicopyProvider, branch_of
from core.providers.base import ImageTask, VideoTask
from core.providers.chaomo import ChaomoProvider
from tools.build_release import make_profile


def test_sd25_balanced_keeps_video_references_and_sd25_duration():
    p=AicopyProvider()
    assert branch_of('sd2.5-720均衡版')=='sd25'
    _,body,_=p.build_video_body(VideoTask('test',model='sd2.5-720均衡版',duration=29,
        refs=['https://fixture.invalid/a.png'],extra={'video_refs':['https://fixture.invalid/a.mp4']}))
    assert body['seconds']==29
    assert body['extra']['reference_videos']==[{'url':'https://fixture.invalid/a.mp4'}]


@pytest.mark.parametrize('resolution',['1K','4K'])
@pytest.mark.parametrize('count',[0,11])
def test_th_resolution_and_all_multipart_references(resolution,count,monkeypatch):
    p=ChaomoProvider()
    b=io.BytesIO();Image.new('RGB',(24,24),'blue').save(b,'PNG')
    ref='data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()
    seen={}
    def request(method,path,**kwargs):
        seen.update(kwargs)
        return {'data':[{'url':'https://fixture.invalid/image.png'}]}
    monkeypatch.setattr(p.session,'request',request)
    monkeypatch.setattr(p.session,'save_item',lambda *a,**kw:None)
    monkeypatch.setattr(p,'check_meta',lambda *a,**kw:None)
    p.generate_image(ImageTask('test',model='gpt-image-2-th',size='16:9',refs=[ref]*count,
        extra={'resolution':resolution}),'unused.png',log=lambda _:None)
    if count:
        assert len([v for k,v in seen['files'] if k=='image[]'])==count
        assert dict(seen['files'])['size']==(None,resolution)
        assert dict(seen['files'])['ratio']==(None,'16:9')
    else:
        assert seen['json_body']['size']==resolution
        assert seen['json_body']['ratio']=='16:9'


def test_batch_carries_image_resolution_and_reference_video():
    common={'provider':'fixture','model':'fixture','tasks':[{'prompt':'x'}],'out_dir':'out'}
    image=batch.build_tasks({**common,'kind':'image','resolution':'4K'})[0]
    video=batch.build_tasks({**common,'kind':'video','video_refs':['video.mp4']})[0]
    assert image.extra['resolution']=='4K'
    assert video.extra['video_refs']==['video.mp4']


def test_private_th_profile_routes_credentials_without_public_exposure(monkeypatch):
    cfg={'config':{'providers':{'ake':{'api_key':'fixture-a'},'aicopy':{'api_key':'fixture-b'},
        'chaomo':{'api_key':'fixture-c'}},'upload':{'endpoint':'https://store.invalid',
        'public_base_url':'https://cdn.invalid','bucket':'fixture','access_key':'fixture-d','secret_key':'fixture-e'}}}
    profile=make_profile(cfg)
    th=[m for m in profile['models'] if m['provider']=='chaomo']
    assert len(profile['models'])==6 and len(th)==2
    assert all(m['options']['resolutions']==['1K','4K'] for m in th)
    assert profile['config']['providers']['aicopy']['api_key']=='fixture-b'
    assert profile['config']['providers']['chaomo']['api_key']=='fixture-c'
    monkeypatch.setattr(distribution,'ENABLED',True)
    monkeypatch.setattr(distribution,'profile',lambda:profile)
    import json
    public=json.dumps(release.public_boot())
    assert not any(secret in public for secret in ('fixture-a','fixture-b','fixture-c','fixture-d','fixture-e'))


def test_video_upload_uses_raw_bytes_not_image_conversion(monkeypatch,tmp_path):
    path=tmp_path/'ref.mp4';content=b'\x00\x00\x00\x18ftypisom'+b'x'*1000;path.write_bytes(content)
    monkeypatch.setattr(uploader,'configured',lambda cfg:True)
    monkeypatch.setattr(uploader,'_cache_get',lambda *a:None)
    monkeypatch.setattr(uploader,'_cache_put',lambda *a:None)
    seen=[]
    monkeypatch.setattr(uploader,'put',lambda cfg,data,key:seen.append((data,key)) or 'https://cdn.invalid/video.mp4')
    assert uploader.video_to_url(str(path),{})=='https://cdn.invalid/video.mp4'
    assert seen[0][0]==content and seen[0][1].endswith('.mp4')
