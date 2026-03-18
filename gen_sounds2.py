# -*- coding: utf-8 -*-
import numpy as np, wave, pathlib
SR = 44100
OUT = pathlib.Path("C:/Users/aliin/OneDrive/Desktop/Jarvis/jarvis_lab/sound/clips")
OUT.mkdir(parents=True, exist_ok=True)
def save(name, s):
    s = np.clip(s,-1,1); d = (s*32767).astype(np.int16)
    st = np.column_stack([d,d])
    with wave.open(str(OUT/name),"w") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(st.tobytes())
    print(f"  {name}")
def t(d): return np.linspace(0,d,int(SR*d),endpoint=False)
def sine(f,d,a=1): return a*np.sin(2*np.pi*f*t(d))
def chirp(f0,f1,d,a=1):
    tt=t(d); return a*np.sin(2*np.pi*(f0*tt+(f1-f0)/(2*d)*tt**2))
def noise(d,a=1): return a*(np.random.random(int(SR*d))*2-1)
def fade(s,i=.01,o=.05):
    s=s.copy(); n=len(s)
    s[:min(int(SR*i),n)]*=np.linspace(0,1,min(int(SR*i),n))
    s[-min(int(SR*o),n):]*=np.linspace(1,0,min(int(SR*o),n))
    return s
def mix2(a,b):
    n=max(len(a),len(b)); a=np.pad(a,(0,n-len(a))); b=np.pad(b,(0,n-len(b))); return a+b
print("Generating remaining sounds...")
save("click.wav", fade(mix2(noise(.015,.5),sine(800,.015,.3))*np.exp(-t(.015)*80),.0005,.008))
save("transmit.wav", fade((chirp(880,1200,.08,.4)+sine(1100,.08,.2))*np.exp(-t(.08)*8),.002,.015))
save("tab_switch.wav", fade(mix2(chirp(200,600,.12,.35)*np.exp(-t(.12)*8),noise(.12,.06)*np.exp(-t(.12)*12)),.002,.02))
s=np.zeros(int(SR*.35))
for i,f in enumerate([440,554,659,880]):
    st=int(SR*i*.07); tone=sine(f,.08,.3)*np.exp(-t(.08)*15); s[st:st+len(tone)]+=tone
save("persona_switch.wav", fade(s,.005,.04))
save("settings_open.wav", fade(mix2(chirp(300,500,.18,.3),noise(.18,.06)*np.exp(-t(.18)*8)),.005,.03))
save("toggle_on.wav", fade(chirp(440,660,.06,.4)*np.exp(-t(.06)*8),.002,.01))
save("toggle_off.wav", fade(chirp(660,440,.06,.4)*np.exp(-t(.06)*8),.002,.01))
save("scroll.wav", noise(.006,.25)*np.exp(-t(.006)*100))
save("node_hover.wav", fade(sine(1400,.04,.2)*np.exp(-t(.04)*30),.001,.01))
save("node_click.wav", fade(mix2(sine(660,.1,.35)*np.exp(-t(.1)*18),sine(990,.1,.15)*np.exp(-t(.1)*25)),.001,.02))
tt=t(1.2); f1=2200*np.exp(-tt*2.5); f2=1800*np.exp(-tt*2.0)
p1=2*np.pi*np.cumsum(f1)/SR; p2=2*np.pi*np.cumsum(f2)/SR
save("finding_critical.wav", fade((.4*np.sin(p1)+.3*np.sin(p2)+.15*np.sin(p1*2)+noise(1.2,.08)*np.exp(-tt*3))*np.exp(-tt*.8),.005,.15))
s1=chirp(880,440,.15,.5)*np.exp(-t(.15)*5); s2=chirp(880,440,.15,.5)*np.exp(-t(.15)*5)
save("finding_high.wav", fade(np.concatenate([s1,np.zeros(int(SR*.05)),s2]),.003,.05))
s=np.zeros(int(SR*.5))
for st2,f,d in [(.0,800,.06),(.08,1200,.05),(.15,1000,.07),(.25,1400,.04),(.31,900,.08)]:
    i=int(SR*st2); tt2=t(d); wb=1+.03*np.sin(2*np.pi*15*tt2)
    ph=2*np.pi*np.cumsum(f*wb)/SR; tone=.4*np.sin(ph[:len(tt2)])*np.exp(-tt2*12); s[i:i+len(tone)]+=tone
save("finding_medium.wav", fade(s,.002,.05))
save("finding_low.wav", fade(mix2(sine(880,.3,.3)*np.exp(-t(.3)*6),sine(1320,.3,.15)*np.exp(-t(.3)*8)),.002,.04))
save("finding_confirmed.wav", fade(mix2(mix2(chirp(400,1200,.25,.5),chirp(800,2400,.25,.2)),noise(.25,.1)*np.exp(-t(.25)*10))*np.exp(-t(.25)*4),.001,.04))
s=np.zeros(int(SR*.8))
for r in range(4):
    st2=int(SR*r*.2); a1=sine(660,.08,.5)*np.exp(-t(.08)*10); a2=sine(550,.08,.5)*np.exp(-t(.08)*10)
    s[st2:st2+len(a1)]+=a1; s[st2+int(SR*.1):st2+int(SR*.1)+len(a2)]+=a2
save("cve_match.wav", fade(s,.005,.06))
s=np.zeros(int(SR*.6))
for r in range(3):
    st2=int(SR*r*.18); k=mix2(sine(440,.12,.6),sine(466,.12,.4))*np.exp(-t(.12)*5); s[st2:st2+len(k)]+=k
save("scope_violation.wav", fade(s,.003,.05))
save("proposal_ready.wav", fade(np.concatenate([chirp(440,880,.12,.4),np.zeros(int(SR*.06)),sine(880,.1,.35)*np.exp(-t(.1)*10)]),.003,.04))
save("scan_start.wav", fade(mix2(mix2(chirp(100,2000,.4,.5),chirp(150,3000,.4,.25)),noise(.4,.1)*np.linspace(0,1,int(SR*.4)))*np.linspace(0,1,int(SR*.4)),.01,.03))
s=mix2(chirp(2000,200,.35,.5),chirp(3000,300,.35,.25)); thump=sine(80,.2,.7)*np.exp(-t(.2)*8)
full=np.zeros(int(SR*.5)); full[:len(s)]+=s*np.linspace(1,.2,len(s)); full[:len(thump)]+=thump
save("scan_complete.wav", fade(full,.003,.06))
save("tool_execute.wav", fade(sine(660,.04,.35)*np.exp(-t(.04)*20),.001,.008))
s=np.zeros(int(SR*.25))
for st2,f,d in [(.0,1000,.05),(.07,1400,.04),(.13,1200,.05)]:
    i=int(SR*st2); tone=sine(f,d,.35)*np.exp(-t(d)*15); s[i:i+len(tone)]+=tone
save("tool_complete.wav", fade(s,.001,.03))
s=mix2(chirp(55,220,.6,.5),sine(110,.6,.3)*np.linspace(0,1,int(SR*.6))); s*=np.linspace(0,1,int(SR*.6))**.5
save("recon_loop_start.wav", fade(s,.02,.08))
save("recon_loop_stop.wav", fade(chirp(220,55,.5,.5)*np.linspace(1,0,int(SR*.5)),.01,.1))
save("approve.wav", fade(np.concatenate([sine(440,.06,.5)*np.exp(-t(.06)*15),np.zeros(int(SR*.04)),sine(660,.06,.5)*np.exp(-t(.06)*15),np.zeros(int(SR*.04)),sine(880,.12,.6)*np.exp(-t(.12)*10)]),.002,.03))
save("skip.wav", fade(chirp(440,330,.08,.3)*np.exp(-t(.08)*10),.001,.015))
save("report_draft.wav", fade(mix2(chirp(330,550,.2,.3),noise(.2,.08)*np.exp(-t(.2)*5)),.005,.03))
save("memory_save.wav", fade(np.concatenate([sine(880,.03,.3)*np.exp(-t(.03)*25),np.zeros(int(SR*.02)),sine(1100,.03,.2)*np.exp(-t(.03)*25)]),.001,.008))
save("memory_recall.wav", fade(np.concatenate([sine(1100,.03,.2)*np.exp(-t(.03)*25),np.zeros(int(SR*.02)),sine(880,.03,.3)*np.exp(-t(.03)*25)]),.001,.008))
save("memory_pin.wav", fade(mix2(noise(.012,.5)*np.exp(-t(.012)*80),sine(600,.04,.3)*np.exp(-t(.04)*20)),.0005,.01))
save("tts_start.wav", fade(chirp(200,400,.06,.25)*np.exp(-t(.06)*8),.003,.01))
save("tts_end.wav", fade(chirp(400,200,.06,.25)*np.exp(-t(.06)*8),.003,.01))
s=np.zeros(int(SR*.3))
for st2,f,d in [(.0,1000,.04),(.06,1400,.03),(.11,1800,.03),(.16,1400,.05)]:
    i=int(SR*st2); tt2=t(d); wb=1+.04*np.sin(2*np.pi*18*tt2)
    ph=2*np.pi*np.cumsum(f*wb)/SR; tone=.4*np.sin(ph[:len(tt2)])*np.exp(-tt2*12); s[i:i+len(tone)]+=tone
save("wake_word.wav", fade(s,.002,.04))
tt4=t(4.0)
hum=(0.35*np.sin(2*np.pi*55*tt4)+0.20*np.sin(2*np.pi*110*tt4)+0.10*np.sin(2*np.pi*165*tt4)+0.06*np.sin(2*np.pi*220*tt4))
hum*=1+0.015*np.sin(2*np.pi*.3*tt4)+0.008*np.sin(2*np.pi*.7*tt4); hum+=noise(4.0,.018)
cross=int(SR*.1); hum[:cross]*=np.linspace(0,1,cross); hum[-cross:]*=np.linspace(1,0,cross)
save("ambient_hum.wav", hum)
print(f"\nDone -- {len(list(OUT.glob('*.wav')))} files in {OUT}")