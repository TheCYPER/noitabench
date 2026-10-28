"""Minimal pure-python PNG decoder (8-bit RGB/RGBA/gray, non-interlaced) + palette extraction."""
import struct, zlib, sys, json, collections, os

def decode_png(data):
    assert data[:8]==b'\x89PNG\r\n\x1a\n'
    pos=8; idat=b''; w=h=0; ct=bt=0; plte=None; trns=None
    while pos<len(data):
        ln,=struct.unpack('>I',data[pos:pos+4]); typ=data[pos+4:pos+8]; body=data[pos+8:pos+8+ln]; pos+=12+ln
        if typ==b'IHDR': w,h,bt,ct,_,_,il=struct.unpack('>IIBBBBB',body); assert il==0 and bt==8, (bt,il)
        elif typ==b'PLTE': plte=[tuple(body[i:i+3]) for i in range(0,len(body),3)]
        elif typ==b'tRNS': trns=body
        elif typ==b'IDAT': idat+=body
        elif typ==b'IEND': break
    raw=zlib.decompress(idat)
    bpp={0:1,2:3,3:1,4:2,6:4}[ct]; stride=w*bpp
    out=[]; prev=bytearray(stride); p=0
    for y in range(h):
        f=raw[p]; p+=1; line=bytearray(raw[p:p+stride]); p+=stride
        for i in range(stride):
            a=line[i-bpp] if i>=bpp else 0; b=prev[i]; c=prev[i-bpp] if i>=bpp else 0
            if f==1: line[i]=(line[i]+a)&255
            elif f==2: line[i]=(line[i]+b)&255
            elif f==3: line[i]=(line[i]+(a+b)//2)&255
            elif f==4:
                pa=abs(b-c); pb=abs(a-c); pc=abs(a+b-2*c)
                pr=a if pa<=pb and pa<=pc else (b if pb<=pc else c)
                line[i]=(line[i]+pr)&255
        out.append(bytes(line)); prev=line
    px=[]
    for line in out:
        for x in range(w):
            v=line[x*bpp:(x+1)*bpp]
            if ct==6: px.append((v[0],v[1],v[2],v[3]))
            elif ct==2: px.append((v[0],v[1],v[2],255))
            elif ct==0: px.append((v[0],v[0],v[0],255))
            elif ct==4: px.append((v[0],v[0],v[0],v[1]))
            elif ct==3:
                r,g,b=plte[v[0]]; a=trns[v[0]] if trns and v[0]<len(trns) else 255; px.append((r,g,b,a))
    return w,h,px

def palette(path,n=6):
    w,h,px=decode_png(open(path,'rb').read())
    opaque=[p for p in px if p[3]>0]
    c=collections.Counter((r,g,b) for r,g,b,a in opaque)
    total=sum(c.values())
    top=[{"hex":"#%02x%02x%02x"%k,"share":round(v/total,3)} for k,v in c.most_common(n)]
    avg=tuple(round(sum(p[i] for p in opaque)/max(1,len(opaque))) for i in range(3))
    return {"size":[w,h],"unique_colors":len(c),"avg_hex":"#%02x%02x%02x"%avg,"top":top}

if __name__=='__main__':
    res={}
    for path in sys.argv[1:]:
        try: res[os.path.basename(path)]=palette(path)
        except Exception as e: res[os.path.basename(path)]={"error":str(e)}
    print(json.dumps(res,indent=1))
