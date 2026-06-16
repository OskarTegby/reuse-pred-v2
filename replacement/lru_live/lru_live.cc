// lru_live — LRU with liveness-informed insertion position.
//
// Policy rules (three liveness classes)
// --------------------------------------
//   DoA fill:         position floor(2N/3) from MRU — near eviction end
//   Mostly-dead fill: position floor(N/3)  from MRU — one grace band
//   Mostly-alive fill:position 0 (MRU)              — standard LRU
//   All hits:         full promotion to MRU
//
// Capped-promotion variants (env LRU_LIVE_HIT_INIT)
// -------------------------------------------------
//   On a (read) hit, instead of promoting every block to MRU, a guided block is
//   moved to a capped position. Two modes:
//   =1  both DoA and MD to their CLASS initial insertion position:
//         DoA hit -> 2N/3 from MRU,  MD hit -> N/3 from MRU,  MA -> MRU
//   =2  like =1 but MD restricted more: DoA hit -> 2N/3 (unchanged),
//         MD hit -> N/2 from MRU (deeper than =1's N/3),  MA -> MRU
//   =3  like =1 but DoA cap relaxed: DoA hit -> N/3 from MRU (milder than =1's
//         2N/3),  MD hit -> N/3 (as =1),  MA -> MRU
//   =4  cap only DoA: DoA hit -> 2N/3 (as =1),  MD hit -> MRU (no cap),  MA -> MRU
//   Default off (=0): full MRU promotion. All variants share one binary.
//
// Internal representation: per-slot rank, 0=LRU, N-1=MRU.
// All N ranks in a set are always a permutation of [0, N-1].
//
// On fill at rank R (0=LRU, N-1=MRU), after eviction of the rank-0 slot:
//   Remaining ways had ranks 1..N-1.
//   Ways with old rank in [1, R]:   new rank = old rank - 1   (shift down)
//   Ways with old rank in [R+1, N-1]: new rank = old rank     (stay)
//   New way: rank = R
//
// On hit (promote to MRU = rank N-1):
//   Ways with rank > old rank of hit way: new rank = old rank - 1
//   Hit way: rank = N-1

#include <cassert>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "cache.h"

namespace
{

std::unordered_map<CACHE*, std::vector<uint32_t>> lru_rank;
// 0=unguided  1=doa  2=mostly_dead  3=mostly_alive
std::unordered_map<CACHE*, std::vector<int8_t>>   slot_class;

// Residency instrumentation. Time is measured in per-set "ticks": one tick per
// update_replacement_state call for that set (every access touching the set).
// Residency of a block = ticks survived between its fill and its eviction.
std::unordered_map<CACHE*, std::vector<uint64_t>> fill_time;      // per slot
std::unordered_map<CACHE*, std::vector<uint64_t>> last_hit_time;  // per slot
std::unordered_map<CACHE*, std::vector<uint32_t>> hit_cnt;        // per slot
std::unordered_map<CACHE*, std::vector<uint64_t>> set_clock;      // per set

struct Stats {
    uint64_t ins_unguided = 0, ins_doa = 0, ins_dead = 0, ins_alive = 0;
    uint64_t hit_unguided = 0, hit_doa = 0, hit_dead = 0, hit_alive = 0;
    uint64_t evict_doa = 0, evict_dead = 0, evict_alive = 0, evict_unguided = 0;
    // Residency at eviction, indexed [class 0..3][reuse 0=no-hit,1=>=1 hit].
    double   res_sum[4][2] = {};
    uint64_t res_cnt[4][2] = {};
    // For evicted blocks that were hit >=1 time: ticks between last hit and eviction.
    double   afterhit_sum[4] = {};
    uint64_t afterhit_cnt[4] = {};
};
std::unordered_map<CACHE*, Stats> stats;

} // namespace

void CACHE::initialize_replacement()
{
    const std::size_t n = NUM_SET * NUM_WAY;
    auto& ranks = ::lru_rank[this];
    ranks.resize(n);
    for (uint32_t set = 0; set < NUM_SET; ++set)
        for (uint32_t way = 0; way < NUM_WAY; ++way)
            ranks[set * NUM_WAY + way] = way;  // initial: way 0 = LRU, way N-1 = MRU
    ::slot_class[this] = std::vector<int8_t>(n, 0);
    ::fill_time[this]     = std::vector<uint64_t>(n, 0);
    ::last_hit_time[this] = std::vector<uint64_t>(n, 0);
    ::hit_cnt[this]       = std::vector<uint32_t>(n, 0);
    ::set_clock[this]     = std::vector<uint64_t>(NUM_SET, 0);
    ::stats[this] = Stats{};
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set,
                             const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
    const auto* ranks = ::lru_rank[this].data() + set * NUM_WAY;
    uint32_t victim = 0;
    for (uint32_t w = 1; w < NUM_WAY; ++w)
        if (ranks[w] < ranks[victim])
            victim = w;

    const std::size_t vi = set * NUM_WAY + victim;
    const int8_t cls = ::slot_class[this][vi];
    auto& st = ::stats[this];
    switch (cls) {
        case 1:  st.evict_doa++;      break;
        case 2:  st.evict_dead++;     break;
        case 3:  st.evict_alive++;    break;
        default: st.evict_unguided++; break;
    }

    // Residency: ticks the victim survived. set_clock is the count of set accesses
    // so far; the imminent fill (update with hit=0) will advance it.
    const uint64_t now = ::set_clock[this][set];
    const uint32_t hc  = ::hit_cnt[this][vi];
    const int c  = (cls >= 0 && cls < 4) ? cls : 0;
    const int hb = hc > 0 ? 1 : 0;
    st.res_sum[c][hb] += static_cast<double>(now - ::fill_time[this][vi]);
    st.res_cnt[c][hb] += 1;
    if (hc > 0) {
        st.afterhit_sum[c] += static_cast<double>(now - ::last_hit_time[this][vi]);
        st.afterhit_cnt[c] += 1;
    }
    return victim;
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way,
                                      uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
    // No write-hit special-case: keep the no-liveness default path identical to
    // baseline LRU so any speedup is attributable to liveness alone (matches the
    // fix applied to srrip_live/ipv_live).
    const std::size_t base = set * NUM_WAY;
    const std::size_t slot = base + way;
    auto* ranks = ::lru_rank[this].data() + base;
    auto& cls   = ::slot_class[this][slot];
    auto& st    = ::stats[this];

    // One tick per set access (hit or fill) — the residency clock.
    const uint64_t clk = ++::set_clock[this][set];

    bool use_liveness = false;
    const char* target_env = std::getenv("SRRIP_LIVE_TARGET");
    if (target_env && target_env[0] != '\0') {
        std::string t(target_env);
        if      (t == "llc"  && NAME == "LLC")        use_liveness = true;
        else if (t == "stlb" && NAME == "cpu0_STLB")  use_liveness = true;
        else if (t == "both" && (NAME == "LLC" || NAME == "cpu0_STLB")) use_liveness = true;
    } else {
        if (NAME == "LLC") use_liveness = true;
    }

    const uint32_t N = NUM_WAY;

    if (hit) {
        // Promote unless this is a writeback hit (matches the baseline LRU
        // convention of not promoting on writebacks). Standard behaviour promotes
        // to MRU; with LRU_LIVE_HIT_INIT a guided block is instead moved to its
        // class's initial insertion position (capped promotion).
        if (type != WRITE) {
            // 0=off (MRU), 1=both DoA/MD to init positions, 2=only MD to stack middle
            static const int hit_mode = []{
                const char* e = std::getenv("LRU_LIVE_HIT_INIT");
                if (!e || e[0] == '\0' || e[0] == '0') return 0;
                if (e[0] == '2') return 2;
                if (e[0] == '3') return 3;
                if (e[0] == '4') return 4;
                return 1;
            }();

            uint32_t target = N - 1;  // default: full promotion to MRU
            if (use_liveness) {
                if (hit_mode == 1) {
                    if      (cls == 1) target = N - 1 - (2 * N / 3);  // DoA initial pos
                    else if (cls == 2) target = N - 1 - (N / 3);      // MD initial pos
                    // cls == 3 (MA) and cls == 0 (unguided) keep MRU
                } else if (hit_mode == 2) {
                    // Same as mode 1 but MD restricted more (N/2 instead of N/3);
                    // DoA behaviour unchanged from mode 1.
                    if      (cls == 1) target = N - 1 - (2 * N / 3);  // DoA -> 2N/3 (as mode 1)
                    else if (cls == 2) target = N - 1 - (N / 2);      // MD -> stack middle (deeper)
                    // cls == 3 (MA) and cls == 0 (unguided) keep MRU
                } else if (hit_mode == 3) {
                    // Same as mode 1 but DoA cap relaxed to N/3 (a third from MRU);
                    // MD unchanged from mode 1. Isolates DoA cap depth (2N/3 -> N/3).
                    if      (cls == 1) target = N - 1 - (N / 3);  // DoA -> N/3 from MRU (milder)
                    else if (cls == 2) target = N - 1 - (N / 3);  // MD  -> N/3 (as mode 1)
                    // cls == 3 (MA) and cls == 0 (unguided) keep MRU
                } else if (hit_mode == 4) {
                    // Cap only DoA (to 2N/3 as mode 1); MD promotes to MRU (no cap).
                    if (cls == 1) target = N - 1 - (2 * N / 3);  // DoA -> 2N/3
                    // cls == 2 (MD), cls == 3 (MA), cls == 0 (unguided) keep MRU
                }
            }

            const uint32_t old_r = ranks[way];
            if (target > old_r) {           // move up toward MRU
                for (uint32_t w = 0; w < N; ++w)
                    if (w != way && ranks[w] > old_r && ranks[w] <= target)
                        --ranks[w];
                ranks[way] = target;
            } else if (target < old_r) {    // move down toward LRU
                for (uint32_t w = 0; w < N; ++w)
                    if (w != way && ranks[w] >= target && ranks[w] < old_r)
                        ++ranks[w];
                ranks[way] = target;
            }
            // target == old_r: already in place, no reshuffle

            ::last_hit_time[this][slot] = clk;   // residency: record reuse
            ++::hit_cnt[this][slot];
        }

        if (use_liveness) {
            switch (cls) {
                case 1:  st.hit_doa++;   break;
                case 2:  st.hit_dead++;  break;
                case 3:  st.hit_alive++; break;
                default: st.hit_unguided++; break;
            }
        } else {
            st.hit_unguided++;
        }
    } else {
        // Fill: evicted block had rank 0.  Remaining ways are at ranks 1..N-1.
        // Insert new block at rank R (0=LRU, N-1=MRU).
        uint32_t R;
        if (use_liveness) {
            const liveness_class lc = classify_block_liveness(full_addr, ip);
            if (lc == liveness_class::doa) {
                R = N - 1 - (2 * N / 3);  // position 2N/3 from MRU → rank N-1-2N/3
                cls = 1; st.ins_doa++;
            } else if (lc == liveness_class::mostly_dead) {
                R = N - 1 - (N / 3);      // position N/3 from MRU → rank N-1-N/3
                cls = 2; st.ins_dead++;
            } else {
                R = N - 1;                 // MRU
                cls = 3; st.ins_alive++;
            }
        } else {
            R = N - 1;  // standard LRU: always insert at MRU
            cls = 0; st.ins_unguided++;
        }

        // Adjust remaining ways: those with old rank in [1, R] shift down by 1.
        // Those with old rank in [R+1, N-1] stay.
        // (Old ranks are 1..N-1 since rank 0 was just evicted.)
        for (uint32_t w = 0; w < N; ++w) {
            if (w == way) continue;
            if (ranks[w] <= static_cast<uint32_t>(R))
                --ranks[w];
        }
        ranks[way] = R;

        ::fill_time[this][slot]     = clk;   // residency: birth tick
        ::last_hit_time[this][slot] = clk;
        ::hit_cnt[this][slot]       = 0;
    }
}

void CACHE::replacement_final_stats()
{
    const auto& st = ::stats[this];
    const uint64_t total_ins  = st.ins_unguided + st.ins_doa + st.ins_dead + st.ins_alive;
    const uint64_t guided_ins = st.ins_doa + st.ins_dead + st.ins_alive;
    const uint64_t total_evict = st.evict_doa + st.evict_dead + st.evict_alive + st.evict_unguided;

    auto pct = [](uint64_t n, uint64_t d) -> double {
        return d ? 100.0 * n / d : 0.0;
    };

    const uint32_t N = NUM_WAY;
    const uint32_t pos_doa  = 2 * N / 3;
    const uint32_t pos_dead = N / 3;

    const char* hi = std::getenv("LRU_LIVE_HIT_INIT");
    const int hit_mode = (!hi || hi[0] == '\0' || hi[0] == '0') ? 0 : (hi[0] == '2' ? 2 : 1);

    printf("%s LRU-Live STATS:\n", NAME.c_str());
    printf("  Insertion positions: DoA=%u/MRU  Dead=%u/MRU  Alive=0/MRU  (N=%u)\n",
           pos_doa, pos_dead, N);
    printf("  Hit promotion    : %s\n",
           hit_mode == 4 ? "DoA to 2N/3, MD to MRU (LRU_LIVE_HIT_INIT=4)"
           : hit_mode == 3 ? "DoA to N/3, MD to N/3 (LRU_LIVE_HIT_INIT=3)"
           : hit_mode == 2 ? "DoA to 2N/3, MD to stack middle N/2 (LRU_LIVE_HIT_INIT=2)"
           : hit_mode == 1 ? "DoA/MD capped to class initial position (LRU_LIVE_HIT_INIT=1)"
                           : "full to MRU");
    printf("  Activation rate  : %.1f%%  (%lu guided / %lu total insertions)\n",
           pct(guided_ins, total_ins), guided_ins, total_ins);
    printf("  guided_insertions=%lu\n", guided_ins);
    printf("  Insert mix       : DoA=%.1f%%  Dead=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
           pct(st.ins_doa,total_ins), pct(st.ins_dead,total_ins),
           pct(st.ins_alive,total_ins), pct(st.ins_unguided,total_ins));
    printf("  Hit rate/class   : DoA=%.1f%%  Dead=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
           pct(st.hit_doa,st.ins_doa), pct(st.hit_dead,st.ins_dead),
           pct(st.hit_alive,st.ins_alive), pct(st.hit_unguided,st.ins_unguided));
    printf("  Evict class mix  : DoA=%.1f%%  Dead=%.1f%%  Alive=%.1f%%  Unguided=%.1f%%\n",
           pct(st.evict_doa,total_evict), pct(st.evict_dead,total_evict),
           pct(st.evict_alive,total_evict), pct(st.evict_unguided,total_evict));

    // Residency (mean ticks survived) by class x reuse. Ticks = per-set accesses.
    //   Check 1: among 0-hit blocks, DoA < Dead < Alive/Unguided (insertion logic).
    //   Check 2: after-last-hit for DoA/Dead should SHRINK under LRU_LIVE_HIT_INIT.
    const char* cn[4] = {"Unguided", "DoA", "MostlyDead", "MostlyAlive"};
    auto mean = [](double s, uint64_t n) -> double { return n ? s / n : 0.0; };
    printf("  Residency (ticks) by class x reuse:\n");
    for (int c = 0; c < 4; ++c)
        printf("    %-11s  0hit: mean=%9.1f (n=%lu)   >=1hit: mean=%9.1f (n=%lu)   "
               "after-last-hit: mean=%9.1f (n=%lu)\n",
               cn[c], mean(st.res_sum[c][0], st.res_cnt[c][0]), st.res_cnt[c][0],
               mean(st.res_sum[c][1], st.res_cnt[c][1]), st.res_cnt[c][1],
               mean(st.afterhit_sum[c], st.afterhit_cnt[c]), st.afterhit_cnt[c]);

    repl_hist_pc.print_stats(NAME.c_str(), thd_doa, thd_dead);
    printf("\n");
}
