"""Replace variable content in user-supplied game UI templates.

All template, font and artwork IO stays in zfile. Source screenshots are never
returned with their example statistics: each variable region is cleared first.
"""
from math import cos, sin, pi

from PIL import Image, ImageDraw, ImageOps, ImageFilter, ImageEnhance
import cv2
import numpy as np

from ..zfile import pil_image_from_bytes, player_client_reference_image

WHITE, INK, DIM, CYAN = '#d1e6f2', '#9ebcda', '#7796b8', '#70dbff'


def win_rate_color(rate, bands):
    if rate is None:
        return DIM
    for band in sorted(bands, key=lambda value: value['min_percent'], reverse=True):
        if rate >= band['min_percent']:
            return band['color']
    return DIM


class Canvas:
    def __init__(self, font, kind):
        self.image = player_client_reference_image(kind)
        self.source = self.image.copy()
        self.font, self.faces = font, {}
        self.draw = ImageDraw.Draw(self.image)

    def text(self, xy, text, size=28, color=INK, bold=False, anchor=None, max_width=None):
        key = (size,bold)
        if key not in self.faces:
            self.faces[key] = self.font(size,650 if bold else 400)
        value,face = str(text),self.faces[key]
        if max_width:
            while value and self.draw.textlength(value,font=face)>max_width:
                value = value[:-2]+'…' if len(value)>2 else ''
        self.draw.text(xy,value,font=face,fill=color,anchor=anchor or 'lt')

    def clear(self, box, sample):
        x,y,x2,y2=box
        if (x2-x)*(y2-y)<150_000:
            # Fill from the immediate texture around the variable field, avoiding
            # rectangular color patches and accidentally sampling nearby labels.
            left,top,right,bottom=max(0,x-12),max(0,y-12),min(2048,x2+12),min(952,y2+12)
            region=np.array(self.image.crop((left,top,right,bottom)))
            mask=np.zeros(region.shape[:2],dtype=np.uint8)
            mask[y-top:y2-top,x-left:x2-left]=255
            restored=Image.fromarray(cv2.inpaint(region,mask,3,cv2.INPAINT_TELEA))
            self.image.paste(restored,(left,top))
        else:
            patch=self.source.crop(sample).filter(ImageFilter.GaussianBlur(5))
            patch=patch.resize((x2-x,y2-y),Image.Resampling.BICUBIC)
            self.image.paste(patch,(x,y))

    def panel(self, box, fill='#213c5c', outline=None):
        self.draw.rectangle(box,fill=fill,outline=outline)

    def art(self, content, box, center=(.45,.4), fade=False):
        if not content:
            return False
        try:
            photo = pil_image_from_bytes(content,max_pixels=8_000_000).convert('RGB')
            x,y,x2,y2=box
            photo = ImageOps.fit(photo,(x2-x,y2-y),Image.Resampling.LANCZOS,centering=center)
            if fade:
                mask=Image.new('L',photo.size)
                pen=ImageDraw.Draw(mask)
                for dx in range(photo.width):
                    pen.line((dx,0,dx,photo.height),fill=int(115*min(1,dx/(photo.width*.32))))
                self.image.paste(photo,(x,y),mask)
            else:
                self.image.paste(photo,(x,y))
            return True
        except (OSError,ValueError):
            return False


def _number(value,percent=False):
    if value is None:return '—'
    if percent:return f'{value:.1f}%'
    return str(value) if isinstance(value,int) else f'{value:.1f}'


def _radar(c,center,radius):
    cx,cy=center
    vertices=[(cx+radius*cos(-pi/2+i*2*pi/5),cy+radius*sin(-pi/2+i*2*pi/5))for i in range(5)]
    for scale in (1,.82):
        points=[(cx+(x-cx)*scale,cy+(y-cy)*scale)for x,y in vertices]
        c.draw.line(points+[points[0]],fill='#456b94',width=4 if scale==1 else 2)
    c.text((cx,cy),'—',30,DIM,anchor='mm')


def render_screen(report,font,*,artwork=None,win_rate_bands=()):
    kind=report['kind']; c=Canvas(font,kind); values=report['values']; artwork=artwork or {}
    if kind=='game':
        # Remove the transient tutorial toast and the source player's filled radar.
        c.clear((278,375,674,440),(1132,375,1230,440))
        c.clear((485,249,1013,710),(1132,249,1230,710))
        _radar(c,(774,501),244)
        c.text((497,420),'生存',25,DIM,anchor='rm')
        # Scope/mode/branch selection must match the requested server dimension.
        c.clear((310,120,1115,178),(1130,120,1210,178))
        scopes=['当前赛季','当前赛年','全部比赛']
        for i,(x,label) in enumerate(zip([430,696,963],scopes)):
            selected=label==report['scope']
            c.text((x,124),label,30,WHITE if selected else INK,anchor='mt')
            if selected:c.draw.line((x-123,172,x+123,172),fill='#57bcff',width=3)
        c.panel((1665,109,1970,153),'#162b47')
        c.text((1805,130),report['mode'],27,WHITE,anchor='mm')
        c.draw.polygon([(1946,124),(1960,124),(1953,135)],fill=WHITE)
        for y,key in [(231,'games'),(346,'win_rate_percent'),(462,'score')]:
            c.clear((1434,y-7,1595,y+49),(1392,y-7,1421,y+49))
            value=values.get(key)
            color=win_rate_color(value,win_rate_bands) if key=='win_rate_percent' else '#e3bd60' if key=='games' else CYAN
            c.text((1573,y-5),_number(value,key=='win_rate_percent'),42,color,True,anchor='rt')
        c.clear((1351,568,1550,600),(1285,568,1322,600))
        c.text((1444,573),'/'.join(_number(values['medals'][k])for k in ('top','gold','silver','bronze')),27,WHITE,True,anchor='mt')
        for i,key in enumerate(['mvp','losing_mvp','triple_kills','quadra_kills','penta_kills','legendary']):
            x,y=1280+(i%2)*170,649+(i//2)*83
            c.clear((x+13,y+1,x+151,y+35),(x+3,y+2,x+12,y+35))
            c.text((x+79,y+2),_number(values.get(key)),29,WHITE,True,anchor='mt')
        for i,key in enumerate([None,'top','jungle','mid','assist','bot']):
            box=(1704,213+i*117,1940,283+i*117)
            original=c.source.crop(box)
            # Keep the exact supplied route icons; only selection brightness varies.
            brightness=1.55 if key==report['branch'] and key is not None else .62 if key is None and report['branch'] is not None else 1
            c.image.paste(ImageEnhance.Brightness(original).enhance(brightness),box[:2])
        selected=[None,'top','jungle','mid','assist','bot'].index(report['branch'])
        c.draw.line((1666,194,1666,898),fill='#88a8c3',width=3)
        c.draw.line((1666,194+117*selected,1666,307+117*selected),fill='#70b7ff',width=4)
    else:
        if report['hero_id']!='106':
            # The supplied single-hero template is Xiao Qiao; other heroes must never inherit her art.
            c.clear((1110,0,2048,952),(282,0,315,952))
            c.art(artwork.get(report['hero_id']),(1110,0,2048,952),center=(.62,.4),fade=True)
        c.clear((289,20,650,79),(300,81,386,115))
        c.text((295,28),report['title'],41,WHITE,max_width=300)
        question_x=295+int(c.draw.textlength(report['title'],font=c.faces[(41,False)]))+22
        c.image.paste(c.source.crop((391,25,437,77)),(question_x,25))
        c.clear((519,116,778,176),(521,187,778,224))
        c.text((527,125),'—',38,WHITE)
        c.clear((1004,123,1150,177),(1010,213,1150,239))
        c.text((1010,130),_number(values['highest_fight_value']),42,'#85b5ef')
        c.panel((1707,16,1880,63),'#162b47')
        c.text((1790,39),report['scope'],26,WHITE,anchor='mm')
        for i in range(3):
            x=553+i*144
            c.panel((x,458,x+129,489),'#47788f','#668e9e')
            c.text((x+64,470),'—',22,WHITE,anchor='mm')
        positions=[(416,522,'games','场次'),(572,522,'win_rate_percent','胜率'),(722,522,'score','综合得分'),
                   (416,626,'top','顶级'),(572,626,'gold','金牌'),(722,626,'silver','银牌'),
                   (416,726,'bronze','铜牌'),(572,726,'mvp','MVP')]
        for x,y,key,label in positions:
            c.clear((x-3,y-4,x+132,y+28),(295,y-4,393,y+28))
            value=values['medals'].get(key) if key in values['medals'] else values.get(key)
            color=win_rate_color(value,win_rate_bands) if key=='win_rate_percent' else INK
            c.text((x,y),_number(value,key=='win_rate_percent'),29,color)
        c.draw.polygon([(1017,520),(1110,580),(1085,684),(950,684),(929,580)],fill='#243f66')
        _radar(c,(1017,607),83)
        if report['hero_id']!='106':
            c.clear((166,786,274,892),(280,786,387,892))
            c.art(artwork.get('portrait'),(166,786,274,892))
        # Badge-stage counts and year tags were absent from the available display contract.
        for x in [441,594,748,901,1058]:
            c.clear((x-15,357,x+15,383),(x-38,357,x-17,383))
            c.text((x,364),'—',23,DIM,anchor='mt')
    return c.image


def render_hero_report(report,font,*,avatar_bytes=None,artwork=None,win_rate_bands):
    c=Canvas(font,'heroes'); artwork=artwork or {}; avatar_bytes=avatar_bytes or {}
    rows=report['rows'][:5]
    # Clear every source card, including the partially visible second row.
    c.clear((284,202,1611,952),(1623,202,1654,952))
    card_boxes=[(284,531),(554,800),(824,1070),(1094,1341),(1364,1610)]
    for row,(x,right) in zip(rows,card_boxes):
        width=right-x
        # Retain the exact card frame from the supplied screenshot.
        frame=c.source.crop((284,202,531,765))
        c.image.paste(frame.resize((width,563),Image.Resampling.LANCZOS),(x,202))
        c.panel((x,203,right,588),'#203b58')
        content=artwork.get(row['hero_id']) or avatar_bytes.get(row['hero_id'])
        if not c.art(content,(x,203,right,588),center=tuple(row.get('artwork_focus',(.5,.4)))):
            c.text(((x+right)/2,352),'—',25,WHITE,anchor='mm')
        shade=Image.new('RGBA',(width,138)); pen=ImageDraw.Draw(shade)
        for dy in range(138):pen.line((0,dy,width,dy),fill=(5,21,35,int(200*dy/137)))
        c.image.paste(shade,(x,450),shade)
        c.text((x+10,505),row['name'],30,WHITE,max_width=226)
        c.text((x+10,548),'—',22,WHITE)
        # The original badge contains the sample player's rank; cover the entire emblem.
        c.draw.polygon([(x+97,596),(x+151,596),(x+144,625),(x+124,643),(x+104,625)],fill='#213954',outline='#b1a17f',width=2)
        c.text((x+124,613),'—',25,'#cbb785',anchor='mm')
        for y,key,label in [(668,'highest_fight_value','最高战力'),(701,'games','英雄场次'),(734,'win_rate_percent','英雄胜率')]:
            c.clear((x+138,y-3,x+241,y+28),(1615,y-3,1648,y+28))
            value=row[key]
            color=win_rate_color(value,win_rate_bands) if key=='win_rate_percent' else '#ac9dcb' if key=='highest_fight_value' else INK
            c.text((x+143,y),_number(value,key=='win_rate_percent'),24,color,max_width=100)
    # Source labels and numeric branch levels are variable as well.
    for box in [(1766,389,1946,427),(1766,716,1946,759)]:
        c.clear(box,(1668,box[1],1712,box[3]))
        c.text(((box[0]+box[2])/2,box[1]),'—',23,DIM,anchor='mt')
    return c.image
