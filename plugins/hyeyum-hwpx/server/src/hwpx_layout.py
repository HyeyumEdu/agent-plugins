"""HWPX 서식 읽기: 원본 XML에서 레이아웃 명세를 뽑는다(쪽·단·미주 설정, 표 구조, 문단 모양·테두리, 번호 모양, 특수 글자).
명령줄: hwpx_layout.py FILE.hwpx > spec.json (전체). 도구용 부분 보기는 read_layout().
"""
import sys, json, zipfile, re, copy
from pathlib import Path
from collections import Counter
from lxml import etree
NS={'hp':'http://www.hancom.co.kr/hwpml/2011/paragraph','hh':'http://www.hancom.co.kr/hwpml/2011/head','hc':'http://www.hancom.co.kr/hwpml/2011/core'}
q=lambda p,t:'{%s}%s'%(NS[p],t)
ln=lambda e:etree.QName(e).localname
def txt(e,n=40): return re.sub(r'\s+',' ',''.join(e.xpath('string()'))).strip()[:n]
ATOM={'tab':'⇥','lineBreak':'↵','nbSpace':'\u00a0','fwSpace':'\u3000','hyphen':'\u00ad'}  # 글자 세기(hwpx_runs, _paragraph_length)처럼 1글자. 미리보기는 탭 ⇥, 줄바꿈 ↵, 나머지는 그 문자 그대로
def t_text(t):
    """hp:t 하나의 글: 라이브러리 run.text와 같은 규칙(탭·줄바꿈·특수 공백 1글자, 다른 자식은 그 안의 글)."""
    out=[t.text or '']
    for c in t:
        name=c.tag.rsplit('}',1)[-1] if isinstance(c.tag,str) else ''
        out.append(ATOM[name] if name in ATOM else ''.join(c.itertext())); out.append(c.tail or '')
    return ''.join(out)
def ptext(p):
    """문단 자신의 글(run 직속 hp:t만; 표 칸·각주 안의 글은 빼고): 글자 위치(position)를 세는 것과 같은 글."""
    return ''.join(t_text(t) for ru in p.findall(q('hp','run')) for t in ru.findall(q('hp','t')))
def ptexts(e,n):
    """e 안 모든 문단의 글(ptext)을 이어 앞 n글자: 개체 설명 글(shapeComment 등)은 빼고 읽히는 글만."""
    return ''.join(ptext(x) for x in e.iter(q('hp','p')))[:n]
FORMS={'checkBtn':'check_box','radioBtn':'radio_button','comboBox':'combo_box','edit':'edit','btn':'button','scrollBar':'scroll_bar'}
SHAPES={'line','rect','ellipse','arc','polyline','polygon','curve','connectLine','container','ole','chart','video','textart','shape','drawingObject'}
def _geom(c):
    """개체의 크기(hp:sz, HWPUNIT)와 놓임(hp:pos, textWrap)."""
    sz=c.find(q('hp','sz')); pos=c.find(q('hp','pos')); g={}
    if sz is not None: g.update(width=int(sz.get('width') or 0),height=int(sz.get('height') or 0))
    if pos is not None: g.update(treat_as_char=pos.get('treatAsChar')=='1',horz_rel_to=pos.get('horzRelTo'),vert_rel_to=pos.get('vertRelTo'))
    if c.get('textWrap'): g['text_wrap']=c.get('textWrap')
    return g
def _run_object(c,tbl_no,n):
    """run의 직접 자식 개체(수식·그림·도형·표·양식 개체·덧말·글자 겹침) 하나의 요약. n = 미리보기 글자 수."""
    k=ln(c)
    if k=='equation': return dict(kind='equation',script=(c.findtext(q('hp','script')) or '')[:200],base_unit=int(c.get('baseUnit') or 0),font=c.get('font'),**_geom(c))
    if k in ('pic','picture'): i=next(c.iter(q('hc','img')),None); return dict(kind='picture',binary_id=i.get('binaryItemIDRef') if i is not None else None,**_geom(c))
    if k=='tbl': return dict(kind='table',table_index=tbl_no[c],rows=int(c.get('rowCnt') or 0),cols=int(c.get('colCnt') or 0))
    if k in FORMS: return dict(kind=FORMS[k],name=c.get('name'),caption=c.get('caption'),**({'checked':c.get('value')=='CHECKED'} if k in ('checkBtn','radioBtn') else {}))
    if k=='dutmal': return dict(kind='ruby',base=c.findtext(q('hp','mainText')),text=c.findtext(q('hp','subText')),pos_type=c.get('posType'))
    if k=='compose': return dict(kind='composed',text=c.get('composeText'),circle_type=c.get('circleType'))
    if k in SHAPES:
        box=c.find('.//'+q('hp','drawText')); text=ptexts(box,n) if box is not None else ''
        return dict(kind='shape',name=k,**_geom(c),**({'text':text} if text else {}))
    return dict(kind=k)
def _ctrl_object(c,in_first_paragraph,n):
    """hp:ctrl 안의 개체(하이퍼링크·필드·책갈피·각주/미주·번호·쪽 제어·머리말/꼬리말·단 나누기) 하나의 요약. 없으면 None."""
    k=ln(c)
    if k=='fieldBegin':
        ps={s_.get('name'):s_.text for s_ in c.iter(q('hp','stringParam'))}
        if c.get('type')=='HYPERLINK': return dict(kind='hyperlink',url=ps.get('Path') or (ps.get('Command') or '').split(';')[0].replace('\\:',':'))  # Path가 없으면 Command("주소;1;0;0;", 콜론은 백슬래시로 이스케이프)에서
        return dict(kind='field',field_type=c.get('type'),name=c.get('name'))
    if k=='bookmark': return dict(kind='bookmark',name=c.get('name'))
    if k in ('footNote','endNote'): return dict(kind='footnote' if k=='footNote' else 'endnote',number=int(c.get('number') or 0),text=ptexts(c,n))
    if k=='autoNum' and c.get('numType') in ('FOOTNOTE','ENDNOTE'): return None  # 각주/미주 본문 첫머리의 자동 번호 표시: 노트마다 하나라서 목록에서 뺀다
    if k in ('autoNum','newNum'): return dict(kind='auto_number' if k=='autoNum' else 'new_number',number_type=c.get('numType'),number=int(c.get('num') or 0))
    if k=='colPr': return None if in_first_paragraph else dict(kind='columns',count=int(c.get('colCount') or 1),column_type=c.get('type'),same_gap=c.get('sameGap'))  # 구역 첫 문단의 단 설정은 overview에 있다
    if k in ('header','footer'): return dict(kind=k,apply_page_type=c.get('applyPageType'),text=ptexts(c,n))
    if k=='pageHiding': return dict(kind='page_hiding',hide=[a[4].lower()+a[5:] for a,v in c.attrib.items() if a.startswith('hide') and v in ('1','true')])
    if k=='pageNum': return dict(kind='page_number',pos=c.get('pos'),format_type=c.get('formatType'))
    return dict(kind=k)
def objects_of(p,tbl_no,n):
    """문단 하나의 인라인 개체를 문서 순서로. at = 그 개체 앞의 글자 수(탭·줄바꿈·특수 공백 1글자, 개체 0글자: insert_inline_ext의 position과 같은 셈).
    하이퍼링크·필드는 fieldBegin~fieldEnd 사이의 글을 text로(같은 문단 안일 때)."""
    out=[]; buf=''; opened={}
    for ru in p.findall(q('hp','run')):
        first=ru.find(q('hp','secPr')) is not None
        for c in ru:
            if not isinstance(c.tag,str): continue
            k=ln(c)
            if k=='t': buf+=t_text(c); continue
            if k in ('secPr','tab'): continue
            for cc in (list(c) if k=='ctrl' else [c]):
                if not isinstance(cc.tag,str): continue  # 주석
                if ln(cc)=='fieldEnd':
                    o=opened.pop(cc.get('beginIDRef'),None)
                    if o is not None: o['text']=buf[o['at']:][:n]
                    continue
                o=_ctrl_object(cc,first,n) if k=='ctrl' else _run_object(cc,tbl_no,n)
                if o is None: continue
                o={'kind':o.pop('kind'),'at':len(buf),**o}; out.append(o)
                if ln(cc)=='fieldBegin': opened[cc.get('id')]=o
    return out
def _num(v): return int(v) if str(v).lstrip('-').isdigit() else v
def secpr_view(sp,z,names,n):
    """구역 정의(secPr)의 줄 번호·격자·감추기·시작 번호·바탕쪽. 이름은 쓰기 도구(set_page_options_ext)의 인수와 같다. 불리언은 0/1(골든 표기; true/false로 쓴 파일도 같은 값)."""
    f=lambda tag:sp.find(q('hp',tag)); a=lambda e,k,d=None:e.get(k,d) if e is not None else d
    ln_,vis,grid,sn=f('lineNumberShape'),f('visibility'),f('grid'),f('startNum'); onoff=lambda v:int(v in ('1','true'))
    masters=[]
    for m in sp.findall(q('hp','masterPage')):
        part=names.get('contents/%s.xml'%(m.get('idRef') or '').lower()); root=etree.fromstring(z.read(part)) if part else None
        sub=root.find(q('hp','subList')) if root is not None else None
        masters.append(dict(id=m.get('idRef'),type=root.get('type') if root is not None else None,paragraphs=len(sub.findall(q('hp','p'))) if sub is not None else 0,text=txt(root,n) if root is not None else ''))
    return dict(line_numbers=dict(restart_type=_num(a(ln_,'restartType',0)),count_by=_num(a(ln_,'countBy',0)),distance=_num(a(ln_,'distance',0)),start_number=_num(a(ln_,'startNumber',0)),show=onoff(a(vis,'showLineNumber'))),
        grid=dict(line=_num(a(grid,'lineGrid',0)),char=_num(a(grid,'charGrid',0)),wongoji=onoff(a(grid,'wonggojiFormat'))),
        visibility=dict(hide_first_header=onoff(a(vis,'hideFirstHeader')),hide_first_footer=onoff(a(vis,'hideFirstFooter')),hide_first_master_page=onoff(a(vis,'hideFirstMasterPage')),
            hide_first_page_num=onoff(a(vis,'hideFirstPageNum')),hide_first_empty_line=onoff(a(vis,'hideFirstEmptyLine')),border=a(vis,'border'),fill=a(vis,'fill')),
        start_numbering=dict(page_starts_on=a(sn,'pageStartsOn'),page=_num(a(sn,'page',0)),picture=_num(a(sn,'pic',0)),table=_num(a(sn,'tbl',0)),equation=_num(a(sn,'equation',0))),
        master_pages=masters)
def extract(path,text_chars=0):
    T=lambda n:text_chars or n  # 0이면 각 자리의 기본 글자 수
    z=zipfile.ZipFile(path); head=etree.fromstring(z.read('Contents/header.xml'))
    def _lang(c,tag):
        e=c.find(q('hh',tag)); return int(e.get('hangul')) if e is not None and e.get('hangul') is not None else None
    faces={(ff.get('lang'),f.get('id')):f.get('face') for ff in head.iter(q('hh','fontface')) for f in ff.findall(q('hh','font'))}
    chars={c.get('id'):dict(font=faces.get(('HANGUL',c.find(q('hh','fontRef')).get('hangul'))) if c.find(q('hh','fontRef')) is not None else None,border_fill=c.get('borderFillIDRef'),size=int(c.get('height'))/100,bold=c.find(q('hh','bold')) is not None,italic=c.find(q('hh','italic')) is not None,
        underline=(c.find(q('hh','underline')) is not None and c.find(q('hh','underline')).get('type','NONE')!='NONE'),
        script='sup' if c.find(q('hh','supscript')) is not None else ('sub' if c.find(q('hh','subscript')) is not None else None),
        ratio=_lang(c,'ratio'),offset=_lang(c,'offset'),spacing=_lang(c,'spacing'),underline_shape=(c.find(q('hh','underline')).get('shape') if c.find(q('hh','underline')) is not None and c.find(q('hh','underline')).get('type','NONE')!='NONE' else None),color=c.get('textColor'),use_font_space=c.get('useFontSpace')=='1') for c in head.iter(q('hh','charPr'))}
    bfs={}
    for b in head.iter(q('hh','borderFill')):
        sides={s_[0]:(b.find(q('hh',s_)).get('type'),b.find(q('hh',s_)).get('width'),b.find(q('hh',s_)).get('color')) for s_ in ('leftBorder','rightBorder','topBorder','bottomBorder') if b.find(q('hh',s_)) is not None}
        wb=b.find('.//'+q('hc','winBrush')); bfs[b.get('id')]=dict(sides={k:v for k,v in sides.items() if v[0]!='NONE'},fill=wb.get('faceColor') if wb is not None and wb.get('faceColor') not in (None,'none') else None)
    numberings={}
    for nb in head.iter(q('hh','numbering')):
        ph=nb.find(q('hh','paraHead')); cid=ph.get('charPrIDRef') if ph is not None else None
        numberings[nb.get('id')]=dict(format=ph.get('numFormat') if ph is not None else None,text=(ph.text or '').strip() if ph is not None else None,
            number_char=chars.get(cid) if cid not in (None,'4294967295') else None)
    tabdefs={}
    for tp in head.iter(q('hh','tabPr')):
        stops=[]
        for sw in tp.findall(q('hp','switch')):
            case=sw.find(q('hp','case')); item=(case if case is not None else sw.find(q('hp','default'))).find(q('hh','tabItem'))
            if item is not None: stops.append(dict(pos=int(item.get('pos')),type=item.get('type'),leader=item.get('leader')))
        for item in tp.findall(q('hh','tabItem')): stops.append(dict(pos=int(item.get('pos')),type=item.get('type'),leader=item.get('leader')))
        tabdefs[tp.get('id')]=dict(stops=stops,auto_left=tp.get('autoTabLeft')=='1',auto_right=tp.get('autoTabRight')=='1')
    paras={}
    for p in head.iter(q('hh','paraPr')):
        al=p.find(q('hh','align')); ls=p.find('.//'+q('hh','lineSpacing')); bs=p.find(q('hh','breakSetting'))
        m=p.find('.//'+q('hh','margin')); g=lambda n:(m.find(q('hc',n)).get('value') if m is not None and m.find(q('hc',n)) is not None else None)
        bd=p.find(q('hh','border')); border=None
        if bd is not None and bfs.get(bd.get('borderFillIDRef'),{}).get('sides'):
            sd=bfs[bd.get('borderFillIDRef')]['sides']; first=next(iter(sd.values()))
            border=dict(sides=sorted(sd),type=first[0],width=first[1],color=first[2],border_fill=bd.get('borderFillIDRef'),connect=bd.get('connect')=='1',
                        offset_mm=[round(int(bd.get(k))/283.465,2) for k in ('offsetLeft','offsetRight','offsetTop','offsetBottom')],ignore_margin=bd.get('ignoreMargin')=='1')
        hd=p.find(q('hh','heading'))
        heading=dict(type=hd.get('type'),level=hd.get('level'),numbering=numberings.get(hd.get('idRef'))) if hd is not None and hd.get('type') in ('NUMBER','BULLET','OUTLINE') else None
        paras[p.get('id')]=dict(align=al.get('horizontal') if al is not None else None,lineSpacing=(ls.get('type'),ls.get('value')) if ls is not None else None,
            breakNonLatin=bs.get('breakNonLatinWord') if bs is not None else None,keepLines=bs.get('keepLines') if bs is not None else None,
            keepWithNext=bs.get('keepWithNext') if bs is not None else None,pageBreakBefore=bs.get('pageBreakBefore') if bs is not None else None,widowOrphan=bs.get('widowOrphan') if bs is not None else None,breakLatin=bs.get('breakLatinWord') if bs is not None else None,
            indent=dict(left=g('left'),right=g('right'),first=g('intent'),before=g('prev'),after=g('next')),border=border,heading=heading,
            condense=int(p.get('condense') or 0),snap_to_grid=p.get('snapToGrid')!='0',tabs=tabdefs.get(p.get('tabPrIDRef')))
    def pshape(p):
        f=paras.get(p.get('paraPrIDRef')) or {}
        return dict(align=f.get('align'),lineSpacing=f.get('lineSpacing'),breakNonLatin=f.get('breakNonLatin'),indent=f.get('indent'),border=f.get('border'),condense=f.get('condense'),snap_to_grid=f.get('snap_to_grid'),tabs=f.get('tabs'))
    def special_of(p):
        out=[]
        for ru in p.findall(q('hp','run')):
            c=chars.get(ru.get('charPrIDRef'),{}); t=''.join(t_.xpath('string()') for t_ in ru.findall(q('hp','t')))
            if t and (c.get('script') or c.get('use_font_space') or (c.get('ratio') not in (None,100)) or (c.get('offset') not in (None,0)) or (c.get('spacing') not in (None,0)) or (c.get('underline_shape') not in (None,'SOLID'))):
                out.append(dict(text=t[:8],size=c.get('size'),script=c.get('script'),ratio=c.get('ratio'),offset=c.get('offset'),spacing=c.get('spacing'),underline_shape=c.get('underline_shape'),bold=c.get('bold'),use_font_space=c.get('use_font_space')))
        return out[:6]
    def own_paras(container):
        out=[]
        for p in container.iter(q('hp','p')):
            if next((a for a in p.iterancestors() if ln(a) in ('tc','endNote','footNote')),None) is container:
                out.append(dict(shape=pshape(p),text=ptext(p)[:T(16)],special_runs=special_of(p)))
        return out
    styles={st.get('id'):dict(name=st.get('name'),paraPr=st.get('paraPrIDRef'),charPr=st.get('charPrIDRef'),next=st.get('nextStyleIDRef'),type=st.get('type')) for st in head.iter(q('hh','style'))}
    spec=dict(file=Path(path).name,sections=[],header=dict(paraPr=paras,charPr=chars,borderFill=bfs,numbering=numberings,tabPr=tabdefs,style=styles))
    names={n_.lower():n_ for n_ in z.namelist()}; tbl_base=0  # tbl_base: 앞 구역들의 표 수(표 번호는 문서 전체에서 센다: format_table_ext의 table_index)
    for sn in sorted((n for n in z.namelist() if re.match(r'Contents/section\d+\.xml$',n)),key=lambda n:int(re.findall(r'\d+',n)[-1])):  # 숫자 순(section10이 section2 앞에 오지 않게)
        r=etree.fromstring(z.read(sn)); sec=dict(xml=sn)
        pp=next(r.iter(q('hp','pagePr'))); mg=next(r.iter(q('hp','margin'))); cp=next(r.iter(q('hp','colPr')),None)
        sec['page']=dict(width=pp.get('width'),height=pp.get('height'),landscape=pp.get('landscape'),**{k:mg.get(k) for k in ('left','right','top','bottom','header','footer','gutter')})
        sp=next(r.iter(q('hp','secPr')),None)
        if sp is not None: sec.update(secpr_view(sp,z,names,T(40)))
        if cp is not None:
            cl=cp.find(q('hp','colLine')); sec['columns']=dict(count=cp.get('colCount'),gap=cp.get('sameGap'),type=cp.get('type'),line=dict(cl.attrib) if cl is not None else None)
        for t in ('footNotePr','endNotePr'):
            e=next(r.iter(q('hp',t)),None)
            if e is not None: sec[t]={ln(c):dict(c.attrib) for c in e}
        not_mirror=lambda e: not any(ln(a)=='secPr' for a in e.iterancestors())
        sec['pageNum']=[dict(p.attrib) for p in r.iter(q('hp','pageNum'))]
        sec['header']=[txt(h,T(80)) for h in r.iter(q('hp','header')) if not_mirror(h)]; sec['footer']=[txt(h,T(80)) for h in r.iter(q('hp','footer')) if not_mirror(h)]
        sec['endnotes']=[dict(text=txt(e,T(20)),paragraphs=own_paras(e)) for e in r.iter(q('hp','endNote'))]; sec['footnotes']=[dict(text=txt(e,T(20)),paragraphs=own_paras(e)) for e in r.iter(q('hp','footNote'))]
        sec['pictures']=[dict(ref=i.get('binaryItemIDRef')) for i in r.iter(q('hc','img'))]
        sc=Counter(c.tag.rsplit('}',1)[-1] for t_ in r.iter(q('hp','t')) for c in t_ if isinstance(c.tag,str)); sec['special_chars']={k:sc[k] for k in ATOM if sc[k]}  # 구역 전체의 탭·줄바꿈·특수 공백 수
        tbl_no={t_:tbl_base+i for i,t_ in enumerate(t_ for t_ in r.iter(q('hp','tbl')) if not_mirror(t_))}; tbl_base+=len(tbl_no)  # 머리말·꼬리말의 secPr 거울 복사본 안 표는 센 번호에서 뺀다(저장 때 원본 쪽으로 덮어써진다)
        # 인라인 개체: 모든 문단(본문, 표 칸, 각주/미주, 머리말/꼬리말, 글상자 안). 자리는 쓰기 도구의 인수와 같은 이름
        story={}  # 문단 묶음 이름: 각주/미주는 notes 부분의 번호 n(1부터), 머리말/꼬리말은 overview 목록의 순서(0부터)
        for tag,name in (('endNote','endnote'),('footNote','footnote')): story.update({e:(name+'_number',name,i+1) for i,e in enumerate(r.iter(q('hp',tag)))})
        for tag in ('header','footer'): story.update({e:(tag+'_index',tag,i) for i,e in enumerate(h for h in r.iter(q('hp',tag)) if not_mirror(h))})
        sec['objects']=[]; body_objs=[]; locs={}
        for p in r.iter(q('hp','p')):
            if not not_mirror(p): continue
            par=p.getparent(); box=par.getparent() if ln(par)=='subList' else None
            if par is r: loc=dict(paragraph_index=len(body_objs))
            elif box is not None and ln(box)=='tc':
                ad=box.find(q('hp','cellAddr')); loc=dict(table_index=tbl_no[box.getparent().getparent()],row=int(ad.get('rowAddr')),col=int(ad.get('colAddr')),cell_paragraph_index=par.findall(q('hp','p')).index(p))
            elif box in story: key,name,i=story[box]; loc={key:i,name+'_paragraph_index':par.findall(q('hp','p')).index(p)}
            elif box is not None:  # 글상자 등: 그것을 품은 문단의 자리를 빌린다(글자 위치는 글상자 안 문단 기준)
                host=locs.get(next((a for a in p.iterancestors() if ln(a)=='p'),None)); loc=dict(host,in_shape=True) if host else None
            else: loc=None
            if loc is None: continue
            locs[p]=loc; found=objects_of(p,tbl_no,T(40))
            if par is r: body_objs.append(found)
            sec['objects']+=[{'kind':o['kind'],**loc,**o} for o in found]
        # 표
        tabs=[]
        for t in (t_ for t_ in r.iter(q('hp','tbl')) if not_mirror(t_)):
            depth=sum(1 for a in t.iterancestors() if ln(a)=='tbl')
            pos=t.find(q('hp','pos')); sz=t.find(q('hp','sz')); om=t.find(q('hp','outMargin')); im=t.find(q('hp','inMargin'))
            trs=t.findall(q('hp','tr')); cells=[]
            for tr in trs:
                for tc in tr.findall(q('hp','tc')):
                    a=tc.find(q('hp','cellAddr')); s=tc.find(q('hp','cellSpan')); z_=tc.find(q('hp','cellSz')); cm=tc.find(q('hp','cellMargin')); sub=tc.find(q('hp','subList'))
                    bf=bfs.get(tc.get('borderFillIDRef'),{})
                    cells.append(dict(r=int(a.get('rowAddr')),c=int(a.get('colAddr')),rs=int(s.get('rowSpan')),cs=int(s.get('colSpan')),w=int(z_.get('width')),h=int(z_.get('height')),
                        vAlign=sub.get('vertAlign'),margin=[cm.get(k) for k in ('left','right','top','bottom')] if cm is not None else None,hasMargin=tc.get('hasMargin'),
                        borders=bf.get('sides'),fill=bf.get('fill'),text=txt(tc,T(24)),paragraphs=own_paras(tc)))
            tabs.append(dict(index=tbl_no[t],depth=depth,rows=int(t.get('rowCnt')),cols=int(t.get('colCnt')),repeatHeader=t.get('repeatHeader'),pageBreak=t.get('pageBreak'),
                size=dict(sz.attrib) if sz is not None else None,treatAsChar=pos.get('treatAsChar') if pos is not None else None,horzRelTo=pos.get('horzRelTo') if pos is not None else None,
                horzOffset=int(pos.get('horzOffset')) if pos is not None else None,vertOffset=int(pos.get('vertOffset')) if pos is not None else None,
                outMargin=[om.get(k) for k in ('left','right','top','bottom')],inMargin=[im.get(k) for k in ('left','right','top','bottom')],
                tableBorders=bfs.get(t.get('borderFillIDRef'),{}).get('sides'),cells=cells))
        sec['tables']=tabs
        # 본문 최상위 문단 뼈대
        skel=[]
        for i,p in enumerate(r.findall(q('hp','p'))):
            runs=p.findall(q('hp','run')); cs=Counter()
            for ru in runs:
                n=len(''.join(t_.xpath('string()') for t_ in ru.findall(q('hp','t'))))
                if n: c=chars.get(ru.get('charPrIDRef'),{}); cs[(c.get('size'),c.get('bold'),c.get('underline'))]+=n
            skel.append(dict(i=i,special_runs=special_of(p),paraPr=paras.get(p.get('paraPrIDRef')),columnBreak=p.get('columnBreak'),pageBreak=p.get('pageBreak'),
                tables=len(p.findall('.//'+q('hp','tbl'))),endnotes=len(p.findall('.//'+q('hp','endNote'))),pics=len(p.findall('.//'+q('hp','pic'))),
                chars=[dict(size=k[0],bold=k[1],underline=k[2],n=v) for k,v in cs.most_common(4)],text=ptext(p)[:T(40)],
                style=styles.get(p.get('styleIDRef'),{}).get('name'),objects=body_objs[i]))
        sec['body_paragraphs']=skel; sec['body_paragraph_count']=len(skel)
        spec['sections'].append(sec)
    return spec
PARTS=('overview','body','tables','notes','header','objects')
HEADER_KINDS=('paraPr','charPr','borderFill','numbering','tabPr','style')
UNITS='indent/margin/size/offset = HWPUNIT (7200 per inch, 283.465 = 1 mm); char size = pt; border offset_mm = mm; border keys l/r/t/b = left/right/top/bottom'
def _intern(items,tabs):
    """반복되는 문단 모양·칸 테두리 dict를 번호로 바꾸고 tabs{shapes|borders: {키: 번호}}에 모은다(수백 번 반복되므로)."""
    which={'shape':'shapes','paraPr':'shapes','borders':'borders'}
    def walk(x):
        if isinstance(x,dict):
            for k,tab in which.items():
                if isinstance(x.get(k),dict):
                    d=tabs[tab]; x[k]=d.setdefault(json.dumps(x[k],sort_keys=True,ensure_ascii=False),len(d)+1)
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(items)
def read_layout(path,part='overview',section=0,offset=0,limit=0,text_chars=0,max_chars=10000,kind=None):
    """서식 부분 보기. part: overview(쪽·단·미주 설정, 줄 번호·격자·감추기·시작 번호, 바탕쪽, 구역 목록, 머리말·꼬리말, 개수) | body(본문 문단 뼈대: 스타일 이름, 글(탭 ⇥ 줄바꿈 ↵), 개체 요약) |
    tables(표 구조와 칸 안 문단 모양) | notes(미주·각주 전문과 문단 모양) | objects(본문과 표 칸 문단의 인라인 개체: 수식·그림·도형·하이퍼링크·책갈피·각주/미주·체크박스 ...) |
    header(헤더에 정의된 문단 모양 paraPr·글자 모양 charPr·테두리 borderFill·번호 numbering·탭 tabPr·스타일 style을 id와 함께 나열; kind로 한 종류만). 항목 목록은 offset/limit으로 쪽을 나누되
    objects 항목: kind(equation·picture·shape·table·hyperlink·field·bookmark·footnote·endnote·check_box·ruby·composed·auto_number·new_number·page_number·page_hiding·header·footer·columns ...)와 자리 + at + 종류별 속성.
    자리는 쓰기 도구의 인수 이름과 같다: 본문 paragraph_index | 표 칸 table_index(문서 전체에서 센 번호; tables 항목의 index)·row·col·cell_paragraph_index | 미주/각주 endnote_number·footnote_number(notes의 n)와 endnote_paragraph_index ... | header_index·footer_index와 header_paragraph_index ... ;
    글상자 안이면 in_shape=true(그것을 품은 문단의 자리). at = 그 문단에서 개체 앞의 글자 수(탭·줄바꿈·특수 공백 1글자, 개체 0글자, 하이퍼링크 표시 글은 글자). 글 미리보기도 같은 셈: 탭 ⇥, 줄바꿈 ↵, 나머지 특수 공백은 그 문자 그대로.
    응답이 max_chars(JSON 글자 수)를 넘지 않게 항목 수를 줄이고 nextOffset을 준다(항목 하나가 넘으면 그 하나만 준다).
    text_chars는 문단 글 미리보기 길이(0 = 기본). 문단 모양은 shapes{번호: 모양}, 칸 테두리는 cell_borders{번호: 테두리}로 한 번만 싣고 항목에서는 번호로 가리킨다."""
    if part not in PARTS: raise ValueError('part must be one of %s, got %r'%(', '.join(PARTS),part))
    spec=extract(path,text_chars or (100000 if part=='notes' else 0)); secs=spec['sections']
    if not 0<=section<len(secs): raise ValueError('section %d out of range (the file has %d)'%(section,len(secs)))
    sec=secs[section]; out=dict(file=spec['file'],part=part,section=section,section_count=len(secs),units=UNITS)
    if kind is not None and (part!='header' or kind not in HEADER_KINDS): raise ValueError('kind applies to part=header only and must be one of %s, got %r'%(', '.join(HEADER_KINDS),kind))
    if part=='overview':
        out.update({k:v for k,v in sec.items() if k not in ('endnotes','footnotes','pictures','tables','body_paragraphs','objects')},
                   counts=dict(body_paragraphs=sec['body_paragraph_count'],tables=len(sec['tables']),endnotes=len(sec['endnotes']),
                               footnotes=len(sec['footnotes']),pictures=len(sec['pictures']),objects=len(sec['objects'])),
                   sections=[dict(index=i,xml=x['xml'],body_paragraphs=x['body_paragraph_count'],tables=len(x['tables']),objects=len(x['objects']),endnotes=len(x['endnotes']),
                                  footnotes=len(x['footnotes']),landscape=x['page']['landscape'],columns=x.get('columns',{}).get('count')) for i,x in enumerate(secs)])
        return out
    header_items=[dict(kind=k,id=i,**v) for k in HEADER_KINDS if kind in (None,k) for i,v in sorted(spec['header'][k].items(),key=lambda kv:int(kv[0]) if str(kv[0]).isdigit() else -1)]
    items={'header':header_items,'body':sec['body_paragraphs'],'tables':sec['tables'],'objects':sec['objects'],
        'notes':[dict(kind='endnote',n=i+1,**e) for i,e in enumerate(sec['endnotes'])]+[dict(kind='footnote',n=i+1,**e) for i,e in enumerate(sec['footnotes'])]}[part]
    if part=='notes':
        for it in items: it.pop('text',None)  # 전문은 문단별로 이미 들어 있다
    offset=max(0,offset); take=items[offset:offset+(limit or len(items))]
    while True:
        page=copy.deepcopy(take); tabs=dict(shapes={},borders={}); _intern(page,tabs)
        used=len(json.dumps(dict(tabs=tabs,items=page),ensure_ascii=False))
        if used<=max_chars or len(take)<=1: break
        take=take[:max(1,min(len(take)-1,len(take)*max_chars//used))]
    end=offset+len(page)
    out.update(total=len(items),offset=offset,returned=len(page),nextOffset=end if end<len(items) else None,
               shapes={v:json.loads(k) for k,v in tabs['shapes'].items()},
               cell_borders={v:json.loads(k) for k,v in tabs['borders'].items()},items=page)
    return out
if __name__=='__main__':
    json.dump(extract(sys.argv[1]),sys.stdout,ensure_ascii=False,indent=1)
