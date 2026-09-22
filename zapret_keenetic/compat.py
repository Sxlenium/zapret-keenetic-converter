"""Small nfqws1 compatibility functions for the zapret2 v1.0.5.2 Lua API.

The altorder=1 wire order is defined in bol-van/zapret nfq/desync.c:
before host, fake host, after host, real host (optionally split).
There is no second fake host. Stock zapret2 hostfakesplit cannot express it.
"""

HOSTFAKESPLIT_ALT1 = r'''
function zk_hostfakesplit_alt1(ctx, desync)
    if not desync.dis.tcp then
        if not desync.dis.icmp then instance_cutoff_shim(ctx, desync) end
        return
    end
    direction_cutoff_opposite(ctx, desync)
    local data = desync.reasm_data or desync.dis.payload
    if #data == 0 or not direction_check(desync) or not payload_check(desync) then return end
    if replay_first(desync) then
        local pos = resolve_range(data, desync.l7payload, "host,endhost-1", true)
        if pos then
            local orig = {rawsend=rawsend_opts_base(desync), reconstruct={}, ipfrag={},
                          ipid=desync.arg, fooling={tcp_ts_up=desync.arg.tcp_ts_up}}
            local fake = {rawsend=rawsend_opts(desync), reconstruct=reconstruct_opts(desync),
                          ipfrag={}, ipid=desync.arg, fooling=desync.arg}
            if not rawsend_payload_segmented(desync, string.sub(data,1,pos[1]-1), 0, orig) then
                return VERDICT_PASS
            end
            local host = genhost(pos[2]-pos[1]+1, desync.arg.host)
            if not rawsend_payload_segmented(desync, host, pos[1]-1, fake) then return VERDICT_PASS end
            if not rawsend_payload_segmented(desync, string.sub(data,pos[2]+1), pos[2], orig) then
                return VERDICT_PASS
            end
            local mid
            if desync.arg.midhost then
                mid = resolve_pos(data, desync.l7payload, desync.arg.midhost)
                if mid and (mid<=pos[1] or mid>pos[2]) then mid=nil end
            end
            if mid then
                if not rawsend_payload_segmented(desync, string.sub(data,pos[1],mid-1), pos[1]-1, orig) then
                    return VERDICT_PASS
                end
                if not rawsend_payload_segmented(desync, string.sub(data,mid,pos[2]), mid-1, orig) then
                    return VERDICT_PASS
                end
            elseif not rawsend_payload_segmented(desync, string.sub(data,pos[1],pos[2]), pos[1]-1, orig) then
                return VERDICT_PASS
            end
            replay_drop_set(desync)
            return VERDICT_DROP
        end
    end
    if replay_drop(desync) then return VERDICT_DROP end
end
'''

# NFQWS_BASE_ARGS is expanded by the stock init script without re-evaluating
# shell quotes. Encode the source as hex to keep a single argv item and avoid
# backslash interpretation by different shells' echo implementations.
# Decoding/compilation happens once at startup, never on the packet path.
HOSTFAKESPLIT_INIT = (
    '--lua-init=assert(load((("' + HOSTFAKESPLIT_ALT1.encode("ascii").hex()
    + '"):gsub("..",function(cc)return(string.char(tonumber(cc,16)))end))))()'
)
