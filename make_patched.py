"""Builds MilitechCentaur-IdleGate: the Militech Centaur's CET init.lua with an idle gate in onUpdate.

Redo after the Centaur (Nexus 36716) updates:
    python make_patched.py            # staging -> original/ -> patched tree
    python make_patched.py --zip      # ... and build the zip at the repo root
    python make_patched.py --from-original   # rebuild from original/ (no staging read)

Reads the Centaur's init.lua from its Vortex staging folder (works while the mod is disabled), keeps a
copy in original/, inserts idlegate_block.lua before the onUpdate handler and two calls inside it.
Fails loudly if an anchor is gone or a field the gate reads no longer exists in the mod (a renamed
field would read as nil = "nothing running" and the gate would throttle a live sequence).
"""
import hashlib, os, pathlib, re, sys, zipfile

VERSION = "1.1"
HERE = pathlib.Path(__file__).parent
REPO = HERE
REL = "bin/x64/plugins/cyber_engine_tweaks/mods/MilitechCentaur/init.lua"
STAGING = pathlib.Path(os.environ["APPDATA"]) / "Vortex" / "cyberpunk2077" / "mods"
KNOWN = "830b30d808b4c945"  # sha256 prefix of the init.lua this patch was written against (Centaur 0.2.0)
MARK = "IDLEGATE"

# (old, new): each old must occur exactly once.
EDITS = [
    # 1. the gate's functions, defined right before the update handler
    ("registerForEvent('onUpdate',function(dt)\n",
     "{BLOCK}registerForEvent('onUpdate',function(dt)\n"),
    # 2. skip the frame right after the load hold, before the mods check and the session probe (the gate
    #    is never quiet in the first 10 s of a world, so the once-per-launch mods check has run by then)
    ("    try('depsTick548',M.depsTick548,dt)\n"
     "    local gateOK,step=pcall(function()return M.session:frame(dt)end)\n",
     "    if M.idleGateTick(dt)then return end -- IDLEGATE: nothing out, nothing queued: polled, not run every frame\n"
     "    try('depsTick548',M.depsTick548,dt)\n"
     "    local gateOK,step=pcall(function()return M.session:frame(dt)end)\n"),
    # 3. the world runs: hand the skipped time to the mod clock before the update
    ("    if step==nil then if M.input then M.input:clearQueuedInput()end;return end\n"
     "    M.gateAt507=os.clock()",
     "    if step==nil then if M.input then M.input:clearQueuedInput()end;return end\n"
     "    M.idleGateCarry() -- IDLEGATE\n"
     "    M.gateAt507=os.clock()"),
]
# Fields of the mod the gate reads. Each must still be used by the mod itself.
M_FIELDS = """state session initialized recovered id entity keyQueue471 phoneSummon334 incapQueued688
settingsQueued688 comp325 companionPrompt325 wake325 sentinelSeq324 ghostExit340 ghostBoard340 summonTpp277
summonTppRestore277 refresh274 wornRestoreAt664 freeze316 fastTravel401 board307 repairSeq314
meltdownDrainAt323 detonateAt340 photo304 summon306 repairFade314 standIn prompt saveLockSent327
saveLockUntil327 compSwept325 pilot camera body visualPilot moveLease lookLease weaponLease gadgetLease
clock""".split()
# (file under the mod folder, text that must be there): the sub-objects' fields / methods the gate reads.
SUB_FIELDS = [
    ("Core/Lifecycle/SessionLifecycle249.lua", "self.state=='active'or self.state=='paused'"),
    ("Core/World/Summon306.lua", "self.phase~=nil"),
    ("Core/World/Summon306.lua", "self.lingering=true"),
    ("Core/World/Summon306.lua", "self.fadeAlpha="),
    ("Core/Pilot/StandIn314.lua", "self.state~='idle'or self.unseen"),
    ("Core/World/NativePrompt177.lua", "self.shown=true"),
    ("Core/Pilot/PlayerMovementLease.lua", "function M:hasLease()"),
    ("Core/Pilot/StockPilotVisual149.lua", "function M:state()"),
    ("init.lua", "M.pilot.owned"), ("init.lua", "M.camera.id"), ("init.lua", "M.body.state=='idle'"),
    # the per-world reset keeps functions on M (the gate's three live there)
    ("init.lua", "if type(value)~='function'and not persistent249[key]then M[key]=nil end"),
    # the author's own load-crash fix (0.2.0, BUILD687): release + collect at the player's detach.
    # If this goes missing, an external load-crash guard is needed again.
    ("init.lua", "M.session:invalidate('player detached',false)"),
    ("init.lua", "collectgarbage('collect');collectgarbage('collect')"),
]


def staging_dir():
    hits = sorted(p for p in STAGING.glob("MilitechCentaur*36716*") if (p / REL).is_file())
    if len(hits) != 1:
        sys.exit(f"expected one Centaur staging folder with {REL}, found {len(hits)}: {[h.name for h in hits]}")
    return hits[0]


def main():
    mod_root = None
    orig = HERE / "original" / REL
    if "--from-original" not in sys.argv:
        mod_root = staging_dir() / pathlib.Path(REL).parent
        src_bytes = (mod_root / "init.lua").read_bytes()
        if MARK.encode() in src_bytes:
            sys.exit("staging init.lua is already patched (installed in place?); restore the mod's original first")
        orig.parent.mkdir(parents=True, exist_ok=True)
        orig.write_bytes(src_bytes)
        for rel in sorted({f for f, _ in SUB_FIELDS if f != "init.lua"}):
            dst = orig.parent / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes((mod_root / rel).read_bytes())
    src_bytes = orig.read_bytes()
    sha = hashlib.sha256(src_bytes).hexdigest()
    src = src_bytes.decode("utf-8")
    crlf = "\r\n" in src
    if crlf:
        src = src.replace("\r\n", "\n")
    block = (HERE / "idlegate_block.lua").read_text(encoding="utf-8").replace("\r\n", "\n")
    if not block.endswith("\n"):
        block += "\n"

    # every M.<field> in the block must be on the checked list, and every checked field must be in the mod
    used = set(re.findall(r"\bM\.([A-Za-z_][A-Za-z0-9_]*)", block)) - {"idleGateTick", "idleGateCarry", "idleGate"}
    unchecked = used - set(M_FIELDS)
    if unchecked:
        sys.exit(f"idlegate_block.lua reads M fields not on M_FIELDS: {sorted(unchecked)}")
    missing = [f for f in M_FIELDS if not re.search(r"\bM\." + re.escape(f) + r"\b", src)]
    if missing:
        sys.exit(f"the mod no longer uses these fields (renamed?): {missing} - re-read its update loop")
    for rel, text in SUB_FIELDS:
        body = src if rel == "init.lua" else (orig.parent / rel).read_text(encoding="utf-8").replace("\r\n", "\n")
        if text not in body:
            sys.exit(f"{rel}: expected text is gone: {text!r} - re-read the mod")
    for name in ("idleGateTick", "idleGateCarry", "idleGate"):
        if re.search(r"\b" + name + r"\b", src):
            sys.exit(f"the mod now has its own {name}: rename the patch's")

    for old, new in EDITS:
        n = src.count(old)
        if n != 1:
            sys.exit(f"anchor found {n}x, mod changed - re-read it:\n{old}")
        src = src.replace(old, new.replace("{BLOCK}", block))
    if crlf:
        src = src.replace("\n", "\r\n")
    out = HERE / REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(src.encode("utf-8"))
    print(f"patched {REL}: original sha256 {sha[:16]} ({len(src_bytes)} bytes) -> {out.stat().st_size} bytes")
    if sha[:16] != KNOWN:
        print(f"NOTE: written against init.lua sha256 {KNOWN} (Centaur 0.2.0); this one differs. Anchors and "
              f"field checks passed; run test_stub.py and re-read the diff of the mod's update loop.")
    if "--zip" in sys.argv:
        z = REPO / f"MilitechCentaur-IdleGate-v{VERSION}.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(out, REL)
        print("zip", z.name, z.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
