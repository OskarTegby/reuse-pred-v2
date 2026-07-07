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

// DoA insertion modes (LRU_LIVE_DOA_INS env var):
//   "2n3"    (default): insert DoA at 2N/3 from MRU — current behaviour
//   "lru"            : insert DoA at rank 0 (LRU position, evicted on next fill)
//   "bypass"         : insert DoA at rank 0 AND mark as bypass-priority, so
//                      find_victim always returns bypass slots before any other
//
// Set dueling (DUEL_N_SAMPLERS=N):
//   Partition LLC sets into sampler-A, sampler-B, and follower sets.
//   Sampler A always uses the cfgA insertion mode (LRU_LIVE_DOA_INS).
//   Sampler B always uses the cfgB insertion mode (LRU_LIVE_DOA_INS_B).
//   Follower sets adopt whichever sampler accumulates more demand hits (PSEL).
//   LRU_LIVE_DOA_INS_B defaults to "bypass" when dueling is on.

namespace
{

// DoA insertion mode constants
enum class DoAIns { Pos2N3, LRUpos, Bypass };

static bool bypass_allowed()
{
    const char* e = std::getenv("LRU_LIVE_ALLOW_BYPASS");
    // Default: bypass allowed. Set LRU_LIVE_ALLOW_BYPASS=0 to disable globally.
    return !(e && e[0] == '0');
}

static DoAIns parse_ins_mode(const char* env, const char* dflt_str)
{
    const char* v = std::getenv(env);
    if (!v || !v[0]) v = dflt_str;
    if (std::string(v) == "lru")    return DoAIns::LRUpos;
    if (std::string(v) == "bypass") return bypass_allowed() ? DoAIns::Bypass : DoAIns::LRUpos;
    return DoAIns::Pos2N3;
}

static DoAIns g_ins_a = DoAIns::Pos2N3;  // cfgA (default: 2n3)
static DoAIns g_ins_b = DoAIns::Bypass;  // cfgB (default: bypass when dueling)
static int    g_n_samplers = -1;
static int64_t g_hyst = 0;  // cfgB must beat cfgA by this margin to win followers

static int g_ll_duel_metric = -1;

// MD_SIGNAL_RECENCY=1: swap the mostly-dead/mostly-alive eviction signal (fed
// to the history table via CACHE::update_eviction_counters in cache.cc) from
// the default wall-clock halflife criterion to a recency-stack-rank signal.
// MD_SIGNAL_END selects which end of the recency stack, if it was where the
// block's LAST hit landed, counts as "mostly dead": "mru" (default) or "lru".
// BLOCK::eviction_state (2 bits) is repurposed here: bit0=accessed (one-way,
// set on first hit), bit1=last hit was in the MRU end (rank >= N/2),
// reversible on every subsequent hit. Read back in cache.cc.
static bool recency_md_enabled()
{
    static const bool e = [] {
        const char* v = std::getenv("MD_SIGNAL_RECENCY");
        return v && v[0] && v[0] != '0';
    }();
    return e;
}

static void ensure_parsed()
{
    if (g_n_samplers >= 0) return;
    const char* e = std::getenv("DUEL_N_SAMPLERS");
    g_n_samplers = (e && *e) ? std::atoi(e) : 0;
    const char* h = std::getenv("DUEL_HYST");
    g_hyst = (h && *h) ? static_cast<int64_t>(std::atoll(h)) : 0;
    g_ins_a = parse_ins_mode("LRU_LIVE_DOA_INS",   "2n3");
    g_ins_b = parse_ins_mode("LRU_LIVE_DOA_INS_B", "bypass");
    const char* dm = std::getenv("DUEL_METRIC");
    g_ll_duel_metric = (dm && (std::string(dm) == "latency" || std::string(dm) == "1")) ? 1 : 0;
}

std::unordered_map<CACHE*, std::vector<uint32_t>> lru_rank;
// 0=unguided  1=doa  2=mostly_dead  3=mostly_alive
std::unordered_map<CACHE*, std::vector<int8_t>>   slot_class;
// true if slot was inserted in bypass mode (always evicted first)
std::unordered_map<CACHE*, std::vector<bool>>      bypassed;
// which config (A=false, B=true) was used at insertion for this slot
std::unordered_map<CACHE*, std::vector<bool>>      slot_cfg_b;

// PSEL counter and per-cache hit counts for dueling (hit-count mode)
constexpr int PSEL_BITS = 10;
constexpr int PSEL_MAX  = (1 << PSEL_BITS) - 1;
constexpr int PSEL_MID  = 1 << (PSEL_BITS - 1);
std::unordered_map<CACHE*, int>      psel;
std::unordered_map<CACHE*, uint64_t> sampler_a_hits;
std::unordered_map<CACHE*, uint64_t> sampler_b_hits;
// Latency accumulators for dueling (latency mode)
std::unordered_map<CACHE*, int64_t>  miss_lat_a;
std::unordered_map<CACHE*, int64_t>  miss_lat_b;

// Residency instrumentation. Time is measured in per-set "ticks": one tick per
// update_replacement_state call for that set (every access touching the set).
// Residency of a block = ticks survived between its fill and its eviction.
std::unordered_map<CACHE*, std::vector<uint64_t>> fill_time;
std::unordered_map<CACHE*, std::vector<uint64_t>> last_hit_time;
std::unordered_map<CACHE*, std::vector<uint32_t>> hit_cnt;
std::unordered_map<CACHE*, std::vector<uint64_t>> set_clock;

struct Stats {
    uint64_t ins_unguided = 0, ins_doa = 0, ins_dead = 0, ins_alive = 0;
    uint64_t ins_doa_bypass = 0;   // DoA fills inserted in bypass mode
    uint64_t hit_unguided = 0, hit_doa = 0, hit_dead = 0, hit_alive = 0;
    uint64_t hit_doa_bypass = 0;   // hits on bypass-mode DoA slots (before eviction)
    uint64_t evict_doa = 0, evict_dead = 0, evict_alive = 0, evict_unguided = 0;
    uint64_t evict_doa_bypass = 0; // bypass-mode DoA evictions
    double   res_sum[4][2] = {};
    uint64_t res_cnt[4][2] = {};
    double   afterhit_sum[4] = {};
    uint64_t afterhit_cnt[4] = {};
};
std::unordered_map<CACHE*, Stats> stats;

} // namespace

void CACHE::initialize_replacement()
{
    ensure_parsed();
    const std::size_t n = NUM_SET * NUM_WAY;
    auto& ranks = ::lru_rank[this];
    ranks.resize(n);
    for (uint32_t set = 0; set < NUM_SET; ++set)
        for (uint32_t way = 0; way < NUM_WAY; ++way)
            ranks[set * NUM_WAY + way] = way;
    ::slot_class[this]   = std::vector<int8_t>(n, 0);
    ::bypassed[this]     = std::vector<bool>(n, false);
    ::slot_cfg_b[this]   = std::vector<bool>(n, false);
    ::fill_time[this]     = std::vector<uint64_t>(n, 0);
    ::last_hit_time[this] = std::vector<uint64_t>(n, 0);
    ::hit_cnt[this]       = std::vector<uint32_t>(n, 0);
    ::set_clock[this]     = std::vector<uint64_t>(NUM_SET, 0);
    ::psel[this]           = PSEL_MID;
    ::sampler_a_hits[this] = 0;
    ::sampler_b_hits[this] = 0;
    ::miss_lat_a[this]     = 0;
    ::miss_lat_b[this]     = 0;
    ::stats[this] = Stats{};
}

uint32_t CACHE::find_victim(uint32_t triggering_cpu, uint64_t instr_id, uint32_t set,
                             const BLOCK* current_set, uint64_t ip, uint64_t full_addr,
                             uint32_t type)
{
    const auto* ranks   = ::lru_rank[this].data() + set * NUM_WAY;
    const auto& bypass_ = ::bypassed[this];

    // Bypass-priority: always evict a bypass-flagged slot before any regular slot.
    for (uint32_t w = 0; w < NUM_WAY; ++w) {
        if (bypass_[set * NUM_WAY + w]) {
            uint32_t victim = w;
            // among multiple bypass slots pick the one with lowest rank
            for (uint32_t w2 = w + 1; w2 < NUM_WAY; ++w2)
                if (bypass_[set * NUM_WAY + w2] && ranks[w2] < ranks[victim])
                    victim = w2;
                ::stats[this].evict_doa_bypass++;
            return victim;
        }
    }

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

            if (::recency_md_enabled()) {
                const bool mru_end = old_r >= N / 2;
                block[slot].eviction_state = 1 | (mru_end ? 2 : 0);  // bit0=accessed bit1=mru_end
            }

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
            // Duel signal update on demand hits (sampler sets only).
            const int ns   = ::g_n_samplers;
            const int step = ns > 0 ? static_cast<int>(NUM_SET) / ns : 0;
            if (type != WRITE && step > 0) {
                const bool is_a = static_cast<int>(set) % step == 0;
                const bool is_b = static_cast<int>(set) % step == step / 2;
                if (::g_ll_duel_metric == 0) {
                    if (is_a) { ::psel[this] = std::max(0,        ::psel[this] - 1); ::sampler_a_hits[this]++; }
                    if (is_b) { ::psel[this] = std::min(PSEL_MAX, ::psel[this] + 1); ::sampler_b_hits[this]++; }
                }
            }
            // A bypass-flagged DoA slot that gets a hit proved itself: demote the
            // bypass flag so it is no longer eviction-priority and can age normally.
            if (cls == 1 && ::bypassed[this][slot]) {
                ::bypassed[this][slot] = false;
                st.hit_doa_bypass++;
            }
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
        ::bypassed[this][slot] = false;
        if (use_liveness) {
            // Determine which config to use for this set.
            const int ns   = ::g_n_samplers;
            const int step = ns > 0 ? static_cast<int>(NUM_SET) / ns : 0;
            const bool is_a = step > 0 && static_cast<int>(set) % step == 0;
            const bool is_b = step > 0 && static_cast<int>(set) % step == step / 2;
            const bool b_wins = (::g_ll_duel_metric == 1)
                ? (::miss_lat_a[this] - ::miss_lat_b[this] > ::g_hyst)
                : (::psel[this] > PSEL_MID);
            const bool use_b = is_b || (!is_a && step > 0 && b_wins);
            ::slot_cfg_b[this][slot] = use_b;
            const DoAIns ins_mode = use_b ? ::g_ins_b : ::g_ins_a;

            // Latency duel: accumulate fill latency per sampler config.
            if (::g_ll_duel_metric == 1 && type != WRITE) {
                if (is_a) ::miss_lat_a[this] += static_cast<int64_t>(this->last_fill_latency);
                if (is_b) ::miss_lat_b[this] += static_cast<int64_t>(this->last_fill_latency);
            }

            const liveness_class lc = classify_block_liveness(full_addr, ip);
            if (lc == liveness_class::doa) {
                cls = 1;
                switch (ins_mode) {
                    case DoAIns::LRUpos:
                        R = 0;
                        st.ins_doa++;
                        break;
                    case DoAIns::Bypass:
                        R = 0;
                        ::bypassed[this][slot] = true;
                        st.ins_doa++;
                        st.ins_doa_bypass++;
                        break;
                    default:  // Pos2N3
                        R = N - 1 - (2 * N / 3);
                        st.ins_doa++;
                        break;
                }
            } else if (lc == liveness_class::mostly_dead) {
                R = N - 1 - (N / 3);
                cls = 2; st.ins_dead++;
            } else {
                R = N - 1;
                cls = 3; st.ins_alive++;
            }
        } else {
            R = N - 1;
            cls = 0; st.ins_unguided++;
            ::slot_cfg_b[this][slot] = false;
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

        ::fill_time[this][slot]     = clk;
        ::last_hit_time[this][slot] = clk;
        ::hit_cnt[this][slot]       = 0;
        if (::recency_md_enabled()) block[slot].eviction_state = 0;  // reset: not yet accessed
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

    auto ins_str = [](DoAIns m) -> const char* {
        switch (m) {
            case DoAIns::LRUpos: return "lru (rank 0)";
            case DoAIns::Bypass: return "bypass (rank 0, priority eviction)";
            default:             return "2n3 (default)";
        }
    };

    printf("%s LRU-Live STATS:\n", NAME.c_str());
    if (::g_n_samplers > 0) {
        const bool lat = (::g_ll_duel_metric == 1);
        const bool b_wins = lat ? (::miss_lat_a[this] - ::miss_lat_b[this] > ::g_hyst)
                                : (::psel[this] > PSEL_MID);
        if (lat) {
            printf("  Set dueling      : metric=latency  hyst=%ld  winner=%s"
                   "  lat_a=%ld  lat_b=%ld\n",
                   ::g_hyst, b_wins ? "cfgB" : "cfgA",
                   ::miss_lat_a[this], ::miss_lat_b[this]);
        } else {
            const int p = ::psel[this];
            printf("  Set dueling      : metric=hits  PSEL=%d/%d  winner=%s"
                   "  sampler_a_hits=%lu  sampler_b_hits=%lu\n",
                   p, PSEL_MAX, b_wins ? "cfgB" : "cfgA",
                   ::sampler_a_hits[this], ::sampler_b_hits[this]);
        }
        printf("  cfgA DoA ins     : %s\n", ins_str(::g_ins_a));
        printf("  cfgB DoA ins     : %s\n", ins_str(::g_ins_b));
    } else {
        printf("  DoA ins mode     : %s  (LRU_LIVE_DOA_INS)\n", ins_str(::g_ins_a));
    }
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
