-- IDLEGATE v1.0 (MilitechCentaur-IdleGate, a local patch; not the mod author's code).
-- With no Centaur out, nothing queued and no sequence running, the update below still ran the
-- session probe (about 9 game calls, 4 new objects) and the input / tick stages (about 8 more game
-- calls) on every frame: 0.09-0.13 ms per frame at Golden Pacific (RedProfiler 2026-11-19).
-- While that quiet state holds, the whole update now runs once per G.period seconds of frame time
-- instead of every frame. The check itself is plain Lua (no game call). Anything that starts work
-- (a queued key, a phone / vehicle-list call, a queued settings change, a summon, the companion,
-- a prompt, a save lock that is not settled) ends the quiet state on the same frame, so nothing is
-- delayed by the gate; what the gate does not know about is seen at the next poll (<= G.period).
-- The skipped time is added to the mod clock on the next update that passes the session gate, so
-- the mod's 0.5 s / 1 s timers (parked place, quest, vehicle list) keep real time.
-- Console: GetMod('MilitechCentaur').idleGate()           status line
--          GetMod('MilitechCentaur').idleGate(false)      off (stock behaviour), (true) on again
--          GetMod('MilitechCentaur').idleGate(true,0.5)   on, poll every 0.5 s (0.05 .. 2)
-- Functions on M survive the per-world reset (it clears only non-function fields); the state lives
-- in this closure, so no new top-level local is added to this file.
M.idleGateTick,M.idleGateCarry,M.idleGate=(function()
    local G={on=true,period=.25,acc=0,carry=0,skipped=0,polls=0,busy=0,why='not run yet'}
    local function quiet()
        if M.state~='idle'then return false,'state '..tostring(M.state)end
        local s=M.session
        if not s or(s.state~='active'and s.state~='paused')then return false,'session not owned'end
        if not M.initialized or not M.recovered or M.id or M.entity then return false,'mech out or recovery pending'end
        if M.keyQueue471 or M.phoneSummon334 or M.incapQueued688 or M.settingsQueued688 then return false,'queued event'end
        if M.comp325 or M.companionPrompt325 or M.wake325 or M.sentinelSeq324 or M.ghostExit340 or M.ghostBoard340 then return false,'companion'end
        if M.summonTpp277 or M.summonTppRestore277 or M.refresh274 or M.wornRestoreAt664 or M.freeze316
            or M.fastTravel401 or M.board307 then return false,'summon / boarding'end
        if M.repairSeq314 or M.meltdownDrainAt323 or M.detonateAt340 or M.photo304 then return false,'sequence'end
        local sm=M.summon306
        if sm and(sm.phase~=nil or sm.lingering or(sm.fadeAlpha or 0)>0)then return false,'summon sequence'end
        if(M.repairFade314 or 0)>0 then return false,'fade'end
        local st=M.standIn
        if st and(st.state~='idle'or st.unseen)then return false,'stand-in'end
        if M.prompt and M.prompt.shown then return false,'prompt'end
        if M.saveLockSent327~=false or M.clock<(M.saveLockUntil327 or 0)then return false,'save lock not settled'end
        if not M.compSwept325 then return false,'first frames of the world'end
        if M.pilot.owned or M.camera.id or M.body.state~='idle'or M.visualPilot:state()~='idle'
            or M.moveLease:hasLease()or M.lookLease:hasLease()or M.weaponLease:hasLease()or M.gadgetLease:hasLease()then
            return false,'pilot clean-up'
        end
        return true
    end
    -- true = skip this frame's update.
    local function tick(dt)
        if not G.on then return false end
        local ok,q,why=pcall(quiet)
        if not ok then
            G.on=false;G.why='off after an error: '..tostring(q)
            log('IDLEGATE %s',G.why)
            return false
        end
        if not q then G.acc=0;G.carry=0;G.why=why;G.busy=G.busy+1;return false end
        dt=tonumber(dt)or 0
        G.acc=G.acc+dt
        if G.acc<G.period then G.skipped=G.skipped+1;return true end
        -- a poll: the time of the skipped frames (not this frame's own dt) is owed to the mod clock
        G.carry=math.max(0,math.min(1,G.acc-dt));G.acc=0;G.polls=G.polls+1;G.why='quiet'
        return false
    end
    -- Called once the session gate passed (the world runs): the owed time goes to the mod clock.
    local function carry()
        local c=G.carry
        if c>0 then G.carry=0;M.clock=(M.clock or 0)+c end
    end
    local function status(on,period)
        if on~=nil then G.on=on==true;G.acc=0;G.carry=0 end
        if tonumber(period)then G.period=math.max(.05,math.min(2,tonumber(period)))end
        local text=string.format('IDLEGATE %s, poll every %.2f s; frames skipped %d, polls %d, full-rate frames %d; last: %s',
            G.on and'on'or'off',G.period,G.skipped,G.polls,G.busy,tostring(G.why))
        log('%s',text)
        return text
    end
    return tick,carry,status
end)()
