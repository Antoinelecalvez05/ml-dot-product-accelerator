set fpga_dir [file dirname [file normalize [info script]]]
set root [file dirname $fpga_dir]
set out [file join $root build vivado]
file mkdir $out
create_project -in_memory -part xc7a35tcpg236-1
read_verilog [file join $root rtl dot_product_core.v]
read_verilog [file join $root rtl dot_product_serial.v]
read_verilog [file join $root rtl dot_product_parallel.v]
read_verilog [file join $fpga_dir button_filter.v]
read_verilog [file join $fpga_dir basys3_demo.v]
read_xdc [file join $fpga_dir basys3.xdc]
synth_design -top basys3_demo -part xc7a35tcpg236-1

set button_first_stages [get_cells -hierarchical -filter {NAME =~ *sync_meta_reg}]
if {[llength $button_first_stages] != 2} {
    error "Expected two button synchronizer first stages; inspect synthesized register names."
}
set button_first_d [get_pins -of_objects $button_first_stages -filter {REF_PIN_NAME == D}]
if {[llength $button_first_d] != 2} {
    error "Expected two first-stage D pins; asynchronous button constraints were not applied."
}
set_false_path -from [get_ports {btnC btnU}] -to $button_first_d
opt_design
place_design
phys_opt_design
route_design
report_utilization -file [file join $out utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $out timing.rpt]
report_route_status -file [file join $out route_status.rpt]
report_drc -file [file join $out drc.rpt]
report_exceptions -file [file join $out exceptions.rpt]
write_checkpoint -force [file join $out basys3_demo_routed.dcp]

set setup_paths [get_timing_paths -delay_type max -max_paths 1]
if {[llength $setup_paths] == 0} { error "No setup timing paths found; inspect timing constraints." }
if {[get_property SLACK $setup_paths] < 0} { error "100 MHz setup timing failed; inspect build/vivado/timing.rpt." }
set hold_paths [get_timing_paths -delay_type min -max_paths 1]
if {[llength $hold_paths] > 0 && [get_property SLACK $hold_paths] < 0} {
    error "Hold timing failed; inspect build/vivado/timing.rpt."
}
write_bitstream -force [file join $out basys3_demo.bit]
puts "Built [file join $out basys3_demo.bit]; no hardware was programmed."
