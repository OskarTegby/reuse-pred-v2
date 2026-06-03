// lru_live — LRU with liveness-informed insertion position.
//
// Policy rules (three liveness classes)
// --------------------------------------
//   DoA fill:         position floor(2N/3) from MRU — near eviction end
//   Mostly-dead fill: position floor(N/3)  from MRU — one grace band
//   Mostly-alive fill:position 0 (MRU)              — standard LRU
//   All hits:         full promotion to MRU
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

struct Stats {
    uint64_t ins_unguided = 0, ins_doa = 0, ins_dead = 0, ins_alive = 0;
    uint64_t hit_unguided = 0, hit_doa = 0, hit_dead = 0, hit_alive = 0;
    uint64_t evict_doa = 0, evict_dead = 0, evict_alive = 0, evict_unguided = 0;
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

    const int8_t cls = ::slot_class[this][set * NUM_WAY + victim];
    auto& st = ::stats[this];
    switch (cls) {
        case 1:  st.evict_doa++;      break;
        case 2:  st.evict_dead++;     break;
        case 3:  st.evict_alive++;    break;
        default: st.evict_unguided++; break;
    }
    return victim;
}

void CACHE::update_replacement_state(uint32_t triggering_cpu, uint32_t set, uint32_t way,
                                      uint64_t full_addr, uint64_t ip, uint64_t victim_addr,
                                      uint32_t type, uint8_t hit)
{
    if (hit && type == WRITE)
        return;

    const std::size_t base = set * NUM_WAY;
    auto* ranks = ::lru_rank[this].data() + base;
    auto& cls   = ::slot_class[this][base + way];
    auto& st    = ::stats[this];

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
        // Promote to MRU (rank N-1): ways above old rank shift down by 1.
        const uint32_t old_r = ranks[way];
        for (uint32_t w = 0; w < N; ++w)
            if (w != way && ranks[w] > old_r)
                --ranks[w];
        ranks[way] = N - 1;

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

    printf("%s LRU-Live STATS:\n", NAME.c_str());
    printf("  Insertion positions: DoA=%u/MRU  Dead=%u/MRU  Alive=0/MRU  (N=%u)\n",
           pos_doa, pos_dead, N);
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
    repl_hist_pc.print_stats(NAME.c_str(), mid_thd, low_thd);
    printf("\n");
}
