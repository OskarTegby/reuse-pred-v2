● Once the 12 sweeps finish, for each of the 12 result directories:                                                           
                                                                                                                              
  python3 scripts/analysis/plot_mid_thd.py results/<label>/ \                                                                 
    --baseline-dir results/<label>/lru --max-n 5                                                                              
                                                                                                                              
  That gives you 12 mid_thd_ipc.png plots. From those, pick the winning key+threshold per trace set, separately for with and  
  without paper_pref — so 6 decisions total:                                                                                  
                                                                                                                              
  ┌────────┬──────────────┬─────────────────┐                                                                                 
  │ Trace  │ no-pref best │ paper-pref best │
  ├────────┼──────────────┼─────────────────┤                                                                                 
  │ dpc3   │ addr/pc, N=? │ addr/pc, N=?    │
  ├────────┼──────────────┼─────────────────┤
  │ qmm    │ addr/pc, N=? │ addr/pc, N=?    │                                                                                 
  ├────────┼──────────────┼─────────────────┤
  │ google │ addr/pc, N=? │ addr/pc, N=?    │                                                                                 
  └────────┴──────────────┴─────────────────┘                                                                                 
   
  Then launch the 6 policy sweeps:                                                                                            
                  
  # Without paper prefetchers
  ./scripts/submit/sweep_policy.sh dpc3   --mid-thd <N> --mid-key <best>
  ./scripts/submit/sweep_policy.sh qmm    --mid-thd <N> --mid-key <best>                                                      
  ./scripts/submit/sweep_policy.sh google --mid-thd <N> --mid-key <best>                                                      
                                                                                                                              
  # With paper prefetchers                                                                                                    
  ./scripts/submit/sweep_policy.sh dpc3   --paper-pref --mid-thd <N> --mid-key <best>
  ./scripts/submit/sweep_policy.sh qmm    --paper-pref --mid-thd <N> --mid-key <best>                                         
  ./scripts/submit/sweep_policy.sh google --paper-pref --mid-thd <N> --mid-key <best>                                         
   
  Once those finish, for each of the 6 policy result directories:                                                             
                  
  python3 scripts/analysis/plot_policy_comparison.py results/<label>/                                                         
                                                                                                                              
  That gives you the IPC speedup and MPKI geomean bars per policy per trace set — which is the final output you need.         
                                                                                                                              

