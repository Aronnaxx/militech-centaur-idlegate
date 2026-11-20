"""Offline stub test (lupa) of MilitechCentaur-IdleGate v1.1.

1. The patched init.lua still compiles (syntax, local-variable limit).
2. The gate block against a fake mod table: quiet state -> frames skipped, one poll per period, the
   skipped time handed to the mod clock; the state and the four event flags end the quiet state on the
   same frame; what the update itself starts is seen on the frame after the poll; anything else within
   one period; an error inside the check switches the gate off instead of raising; the console switch.
3. The patched onUpdate handler, cut out of the patched file, run with stubs: per-frame probe calls with
   the gate off vs on.
Run: python make_patched.py, then python test_stub.py (pip install lupa)
"""
import pathlib, re, lupa

HERE = pathlib.Path(__file__).parent
PATCHED = (HERE / "bin/x64/plugins/cyber_engine_tweaks/mods/MilitechCentaur/init.lua").read_text(encoding="utf-8").replace("\r\n", "\n")
BLOCK = (HERE / "idlegate_block.lua").read_text(encoding="utf-8")
L = lupa.LuaRuntime()

# 1 ------------------------------------------------------------------ compile
L.globals().src = PATCHED
ok = L.eval("(function() local f,e=load(src,'=init.lua');return f~=nil and 'ok' or e end)()")
assert ok == "ok", ok
print("1. patched init.lua compiles (%s)" % L.eval("_VERSION"))

# 2 ------------------------------------------------------------------ the gate block alone
FAKE = '''
logged={}
local function log(fmt,...) logged[#logged+1]=string.format(fmt,...) end
local function lease() return {hasLease=function(self) return self.lease~=nil end} end
function fresh()
  M={state='idle',initialized=true,recovered=true,clock=10,compSwept325=true,saveLockSent327=false,
     session={state='active'},summon306={},standIn={state='idle'},prompt={shown=false},
     pilot={},camera={},body={state='idle'},visualPilot={status='idle',state=function(self) return self.status end},
     moveLease=lease(),lookLease=lease(),weaponLease=lease(),gadgetLease=lease()}
  onPoll=nil
end
fresh()
''' + BLOCK.replace("M.idleGateTick,M.idleGateCarry,M.idleGate=", "TICK,CARRY,STATUS=") + '''
-- one frame as onUpdate does it: skipped, or the update runs (onPoll stands in for the mod's update)
function frames(n,dt) local skipped=0 for i=1,n do if TICK(dt) then skipped=skipped+1 else CARRY();if onPoll then onPoll() end end end return skipped end
'''
L.execute(FAKE)
g = L.globals()
# 100 frames of 10 ms = 1 s: a poll every 25 frames (0.25 s) -> 4 polls, 96 skipped
skipped = g.frames(100, 0.01)
assert skipped == 96, skipped
# each poll handed 24 skipped frames (0.24 s) to the clock; the poll frame's own dt is the update's
assert abs(g.M.clock - (10 + 4 * 0.24)) < 1e-9, g.M.clock
assert "full checks 4;" in g.STATUS(), g.STATUS()            # one full check per period, not per frame
print("2a. quiet: 96 of 100 frames skipped, mod clock +%.2f s, 4 full checks" % (g.M.clock - 10))

# what can change without the update running: woken on the very next frame
EVENTS = ["M.state='ready'", "M.state='waiting'", "M.keyQueue471={}", "M.phoneSummon334=1",
          "M.incapQueued688=true", "M.settingsQueued688=true"]
for w in EVENTS:
    L.execute("fresh();STATUS(true)")
    assert g.frames(10, 0.01) == 10, "quiet baseline"          # mid-window: all skipped
    L.execute(w)
    assert g.frames(10, 0.01) == 0, "not woken at once by " + w
print("2b. %d event conditions end the quiet state on the next frame" % len(EVENTS))

# everything the full check reads: (a) never quiet if set before the first check, (b) set by the update
# on a poll frame -> the frame after it is not skipped, (c) set from outside mid-window -> woken within
# one period, then full rate.
OTHERS = ["M.session.state='warming'", "M.recovered=false", "M.id=5", "M.entity={}", "M.clock=9.9",
          "M.comp325={}", "M.companionPrompt325=true", "M.wake325={}", "M.sentinelSeq324={}", "M.ghostExit340=1",
          "M.ghostBoard340=1", "M.summonTpp277={}", "M.summonTppRestore277=1", "M.refresh274={}",
          "M.wornRestoreAt664=1", "M.freeze316={}", "M.fastTravel401={}", "M.board307={}", "M.repairSeq314={}",
          "M.meltdownDrainAt323=1", "M.detonateAt340=1", "M.photo304=true", "M.summon306.phase='call'",
          "M.summon306.lingering=true", "M.summon306.fadeAlpha=.5", "M.repairFade314=.3", "M.standIn.state='spawned'",
          "M.standIn.unseen=true", "M.prompt.shown=true", "M.saveLockSent327=true", "M.saveLockSent327=nil",
          "M.saveLockUntil327=1e9", "M.compSwept325=nil", "M.pilot.owned=true", "M.camera.id=3",
          "M.body.state='hidden'", "M.visualPilot.status='stopping'", "M.moveLease.lease={}", "M.lookLease.lease={}",
          "M.weaponLease.lease={}", "M.gadgetLease.lease={}", "M.initialized=false"]
for w in OTHERS:
    assert re.match(r"M\.(\w+)", w).group(1) in BLOCK, w
    L.execute("fresh();STATUS(true);" + w)                      # (a)
    assert g.frames(30, 0.01) == 0, "quiet although " + w
    if "clock" in w:
        continue                                                 # the clock only moves forward in the mod
    L.execute("fresh();STATUS(true)")                           # (b)
    assert g.frames(10, 0.01) == 10
    g.wake = w
    L.execute("onPoll=function() load(wake)() end")
    n = g.frames(40, 0.01)                                       # 15 more skipped, poll at frame 25, then none
    assert n == 14, (w, n)
    L.execute("fresh();STATUS(true)")                           # (c)
    assert g.frames(10, 0.01) == 10
    L.execute(w)
    n = g.frames(60, 0.01)
    assert n <= 15, (w, n)                                       # at most the rest of this window
    assert g.frames(30, 0.01) == 0, w
print("2c. %d other conditions: never quiet when set; seen on the frame after the poll that set them; "
      "from outside within one period" % len(OTHERS))

# paused world while quiet: polls continue, but the clock is only fed when the caller calls CARRY
L.execute("fresh();STATUS(true)")
L.execute("for i=1,100 do TICK(0.01) end")                      # never CARRY: session gate refused (paused)
assert g.M.clock == 10, g.M.clock
L.execute("M.state='ready';TICK(0.01);CARRY()")                # busy frame drops the owed time
assert g.M.clock == 10, g.M.clock
# odd dt values never skip forever
L.execute("fresh();STATUS(true)")
assert g.frames(3, float("nan")) == 0 and g.frames(3, 5.0) == 0
L.execute("fresh();STATUS(true)")
assert g.frames(3, None) == 3                                    # a missing dt is not an error
# an error inside the check: gate off, no raise
L.execute("fresh();STATUS(true);M.visualPilot=nil")
assert g.frames(5, 0.01) == 0 and "off after an error" in g.STATUS()
# console switch + period clamp
L.execute("fresh()")
assert "IDLEGATE off" in g.STATUS(False) and g.frames(50, 0.01) == 0
assert "poll every 0.50" in g.STATUS(True, 0.5) and g.frames(100, 0.01) == 98
assert "IDLEGATE off" in g.STATUS(False) and g.frames(50, 0.01) == 0   # off also leaves the fast path
assert "poll every 2.00" in g.STATUS(True, 99) and "poll every 0.05" in g.STATUS(True, 0)
print("2d. pause / odd dt / error / console switch OK")

# 3 ------------------------------------------------------------------ the patched onUpdate handler
m = re.search(r"registerForEvent\('onUpdate',function\(dt\)\n(.*?)\nend\)\nlocal function overlay", PATCHED, re.S)
assert m, "onUpdate handler not found in the patched file"
body = m.group(1)
assert body.count("idleGateTick") == 1 and body.count("idleGateCarry") == 1
assert body.index("M.loadHold465") < body.index("idleGateTick") < body.index("depsTick548") < body.index("M.session:frame")
HANDLER = '''
probes,updates,deps=0,0,0
local LOG_ON=false
local function log() end
local function try(label,fn,...) return pcall(fn,...) end
local function update(step) updates=updates+1 end
local function player() return nil end
local Game={}
fresh()
M.depsTick548=function() deps=deps+1 end
M.session.frame=function(self,dt) probes=probes+1;return math.min(dt,.05) end
M.session.ownsWorld=function() return true end
M.session.invalidate=function() end
M.standIn.frame=function() end
''' + BLOCK + '''
HANDLER=function(dt)
''' + body + '''
end
function run(n,dt) probes,updates,deps=0,0,0;for i=1,n do HANDLER(dt) end;return probes,updates end
'''
L.execute(HANDLER)
L.execute("M.idleGate(false)")
p_off, u_off = g.run(900, 1 / 90)                                # 10 s at 90 fps
L.execute("M.idleGate(true)")
c0 = g.M.clock
p_on, u_on = g.run(900, 1 / 90)
assert (p_off, u_off) == (900, 900), (p_off, u_off)
assert p_on == u_on and 38 <= p_on <= 41, (p_on, u_on)          # ~4 polls a second
# the handler's update stub adds nothing to M.clock: the carry alone is the skipped frames' time
# (10 s minus the poll frames), short only by the still-open last window (< one period)
owed = (900 - p_on) / 90 - (g.M.clock - c0)
assert 0 <= owed < 0.25, owed
L.execute("M.loadHold465=true")
assert g.run(10, 1 / 90) == (0, 0)                               # the author's load hold still comes first
L.execute("M.loadHold465=nil;M.keyQueue471={{action='summon',at=0}}")
assert g.run(1, 1 / 90) == (1, 1)                                # a queued key runs on its own frame
print("3. onUpdate at 90 fps for 10 s: session probes %d -> %d, updates %d -> %d" % (p_off, p_on, u_off, u_on))
print("stub test OK")
