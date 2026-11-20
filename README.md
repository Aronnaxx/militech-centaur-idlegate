# Militech Centaur: idle gate for the CET update loop

A small patch and profiling notes for [MILITECH CENTAUR - Combat Exoskeleton](https://www.nexusmods.com/cyberpunk2077/mods/36716) (Cyberpunk 2077 2.5), written against **0.2.0**.

With no Centaur out, the mod's CET `onUpdate` handler still costs about 90-100 µs on every frame. This patch makes it run 4 times a second in that state instead of every frame, without delaying a summon. It is one inserted block and two call lines in `init.lua`.

Measured in game: **0.104 → 0.015 ms per frame** for the CET mod while the Centaur is not in use (86 % less; the `onUpdate` handler alone 99.9 → 9.7 µs per call).

This repo holds only the patch. It does not contain the mod's files; `make_patched.py` applies the change to your own installed copy.

The mod's author is welcome to take any of this, changed or not, with no credit needed.

## Measured

RedProfiler, 60 s captures on 2026-11-19, standing in a busy street (Golden Pacific), no Centaur summoned, 3440x1440, about 83 fps under the profiler. The three runs were made one after another on the same mod set and save. Rows are in [`measurements/`](measurements/).

| Build | `onUpdate` per call | `onUpdate` max | `onDraw` per call | CET mod total per frame |
|---|---|---|---|---|
| Stock 0.2.0 | 99.9 µs | 1.86 ms | 4.4 µs | **0.104 ms** |
| Idle gate v1.0 (full check every frame) | 19.3 µs | 0.64 ms | 4.4 µs | 0.024 ms |
| Idle gate v1.1 (this repo) | 9.7 µs | 0.86 ms | 4.9 µs | **0.015 ms** |

- Frame rate did not change measurably (81.6 / 81.9 / 82.1 fps average without the profiler). 0.09 ms is under 1 % of a 12 ms frame; the gain is main-thread script time, not visible fps.
- In the v1.1 session the gate's own counters read: 13,448 frames skipped, 652 polls, 4,177 frames at full rate (loading, the first 10 s of the world, the teleport).
- Two earlier stock captures the same day, on a different mod set, gave 87.1 and 88.2 µs per `onUpdate` call (0.090 / 0.091 ms per frame).
- The redscript side (`CentaurMech`) is 0.007-0.009 ms per frame in all captures.
- What is left in v1.1 is about one third each: the 4 polls a second, the cost of entering a CET callback on the skipped frames, and the unchanged `onDraw`.

### Where the stock 100 µs goes

In the idle state (`M.state=='idle'`, no `M.id`) every frame still runs:

1. The session probe (`M.session:frame` → `probe`): `Game.GetPlayer`, `IsDefined`, `IsAttached`, `GetSystemRequestsHandler`, `IsPreGame`, `GetSimTime`, `EngineTime.ToDouble`, `GetEntityID().hash` + `tostring`, `IsGamePaused`. That is 9 game calls, plus a new table, a string, a closure and 4 userdata per frame.
2. `U.inputWorld`: a second `Game.GetPlayer`, then 5 script-field reads on the player (`centaur356ScreenOpen`, `centaur360HackPending` and `centaur360HackOpen` twice each).
3. `U.ticks`: the save-lock check, once a second the quest and vehicle-list calls, every 0.5 s the parked-place check.

About 17 game calls at roughly 5 µs each. The cost is the Lua-to-game call boundary, and plain Lua is not free either: v1.0 ran a 45-field check through a `pcall` on every skipped frame and that alone measured about 15 µs per frame. In the same captures the mod's own redscript methods (`CentaurQ341MechWanted`, `CentaurQ341RepairLocked`) average 1.1 µs per call, body included.

## The patch

`idlegate_block.lua` defines three functions on `M` (functions survive the per-world reset; the state lives in a closure, so no new top-level local is added):

- `M.idleGateTick(dt)` is called in `onUpdate` right after the load hold (`M.loadHold465`), before `depsTick548` and the session probe. It returns `true` to skip the frame.
- `M.idleGateCarry()` is called once the session gate has passed. It adds the time of the skipped frames to `M.clock`, so the 0.5 s and 1 s timers keep real time.
- `M.idleGate([on],[period])` is a console switch and status line.

There are two checks, both plain Lua with no game call.

**Full check**, once per period, on the frame after each poll (so right after the update that could have started something). The state is quiet only while all of this holds:

- state `idle`, session `active` or `paused`, `M.recovered`, no `M.id`, no `M.entity`, at least 10 s into the world
- nothing queued: `keyQueue471`, `phoneSummon334`, `incapQueued688`, `settingsQueued688`
- no companion or its prompt, no Sentinel or Ghost Link sequence
- no summon, boarding, refresh, freeze, fast-travel, repair, meltdown, detonation or photo-mode state
- `summon306` not busy, not lingering, no fade
- stand-in idle and V not unseen, prompt hidden
- save lock sent and settled
- pilot, camera, body, visual pilot and the four leases idle

**Fast check**, on every skipped frame: only what can change without the update running, which is `M.state` and the four event flags set by observers (queued key, phone or vehicle-list call, incapacitation, settings change).

What this means for timing:

- A key press, a phone or vehicle-list call, or a state change (a load, for example) ends the quiet state on the same frame, as in the stock mod.
- Anything the update itself starts (a quest placement, the parked-mech restore after a load) is seen on the next frame.
- A change made from outside between two polls, such as `GetMod('MilitechCentaur').summon()` typed in the console, is seen at the next poll, at most 0.25 s later.
- If the check ever raises an error, the gate switches itself off and the mod runs as stock.

Not changed: piloting, a parked mech, the companion, `onDraw`, the `OnAction` observer, the redscript, and the load handling (the gate sits after `loadHold465`).

### Apply it

```
python make_patched.py          # reads init.lua from the Vortex staging folder, writes bin/.../init.lua here
python make_patched.py --zip    # also builds an installable zip
python test_stub.py             # offline test (needs: pip install lupa)
```

`make_patched.py` keeps a copy of the original under `original/`, and stops if an anchor has moved or if a field the gate reads no longer exists in the mod. That second check matters: a renamed field would read as `nil`, which the gate would take as "nothing running".

[`idlegate.patch`](idlegate.patch) is the same change as a unified diff against 0.2.0, for reading.

In game, from the CET console:

```
GetMod('MilitechCentaur').idleGate()           -- status: frames skipped, polls, full-rate frames, why it last ran at full rate
GetMod('MilitechCentaur').idleGate(false)      -- off: stock behaviour
GetMod('MilitechCentaur').idleGate(true, 0.5)  -- on, poll every 0.5 s (0.05 to 2)
```

### Tested

In game: the three captures above, with the gate engaged for the whole measured minute. That covers the idle path only.

Offline (`test_stub.py`, lupa):

- the patched `init.lua` compiles
- 96 of 100 quiet frames are skipped and the mod clock receives the 0.96 s
- 6 event conditions end the quiet state on the next frame
- 42 other conditions: never quiet when set; seen on the frame after the poll that set them; seen within one period when set from outside
- a paused world, a NaN, missing or very long `dt`, and an error inside the check
- the patched `onUpdate` handler, cut out of the file and run with stubs at 90 fps for 10 s: 900 → 39 session probes

**Not tested in game yet:** a play session with the patch that summons, boards, uses the companion and loads a save. The gate is off in all of those states, but that is by reading the code and the offline test, not by play.

## Beyond the patch: moving the per-frame work off CET

The gate removes most of the idle cost, but it is a workaround for the price of a game call from Lua. The same price applies while piloting, where far more calls run per frame. That piloting cost is not measured here.

Two things suggest a larger win is available:

- In these captures a redscript method of this mod costs about 1 µs per call, against about 5 µs for each game call made from Lua. Even an empty CET callback costs 4-5 µs per frame under the profiler.
- Frosthaven did this for [Overclocked Lynx Paws](https://www.nexusmods.com/cyberpunk2077/mods/27692) (2.0.0 beta, a movement mod with per-frame logic): a rewrite "from CET to reds where possible", RedProfiler main thread 0.178 ms → 0.005 ms.

The Centaur is well placed for it. It already has about 18,000 lines of redscript with 245 `Centaur*` methods that the Lua calls, and it already ships two RED4ext plugins, so the build setup for native code exists. Summon keys already arrive from redscript as an event rather than by polling.

A staged path, smallest step first:

1. **Idle with no Lua at all.** The player attach / detach observers already exist. If redscript raises an event for the few things that start work (key, phone call, vehicle-list call, quest placement, parked-place restore after a load), `onUpdate` can return on its first line while idle and the session probe is not needed until something is out.
2. **Move the slow polls to redscript.** The quest stage, the vehicle-list entry for the Spinal Sync shard, the save lock and the parked-place store are all redscript calls made from Lua on a timer. A redscript `DelayCallback`, or the quest fact and equipment change callbacks, would do the same without crossing into Lua.
3. **Move the piloting loop.** Drive, terrain probes, camera and animation-graph inputs are the calls that run every frame while piloting. A redscript per-frame callback would cut the per-call cost; a tick in one of the existing RED4ext plugins would cut it further and gives exact control over where in the frame it runs, which matters for the camera.
4. **Keep CET optional.** What is left needs CET only for the debug log, the console commands and three ImGui draws (the fade rectangle, the crosshair and the flight notice), which could move to the ink HUD the mod already has. With no `onUpdate` and `onDraw` registered while idle, the per-callback floor goes too.

Steps 1 and 2 are small and would bring the idle cost to about zero. Step 3 is the large one and is where a port would have to be tested carefully.

## Load crash (0.1.5)

0.2.0 fixes it in the mod itself (BUILD687: world references released and collected at the player's `OnDetach`). A separate guard mod is no longer needed, and an older external guard that calls `M.session:invalidate` itself should not be installed next to 0.2.0: it would run without the release flag and send the old references to `graveyard687` on every load.
