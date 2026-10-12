import PcbProofs.NetName
import PcbProofs.Reexec

/-! Axiom audit: none of these may depend on `sorryAx`. -/
#print axioms NetName.netFromDesc_pad
#print axioms NetName.netFromDesc_pad_DATA0
#print axioms NetName.netFromDesc_trailing
#print axioms Reexec.terminates_within_two
#print axioms Reexec.run_stable
#print axioms Reexec.reexec_then_terminal
#print axioms Reexec.importable_proceeds
#print axioms Reexec.importable_runs
#print axioms Reexec.reexec_reaches_kicad
#print axioms Reexec.noMarker_loops
