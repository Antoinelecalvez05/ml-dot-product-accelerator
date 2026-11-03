`timescale 1ns/1ps

module basys3_demo #(
    parameter integer DEBOUNCE_CYCLES = 1000000
) (
    input wire clk,
    input wire btnC,
    input wire btnU,
    output wire [15:0] led
);
    reg [3:0] por_shift = 4'b1111;
    always @(posedge clk)
        por_shift <= {por_shift[2:0], 1'b0};
    wire power_on_reset = |por_shift;

    wire reset_level;
    wire unused_reset_pulse;
    wire start_level;
    wire start_pulse;
    wire rst = power_on_reset || reset_level;
    button_filter #(.CYCLES(DEBOUNCE_CYCLES)) reset_button (
        .clk(clk), .rst(power_on_reset), .raw_button(btnU),
        .level(reset_level), .pressed(unused_reset_pulse)
    );
    button_filter #(.CYCLES(DEBOUNCE_CYCLES)) start_button (
        .clk(clk), .rst(rst), .raw_button(btnC),
        .level(start_level), .pressed(start_pulse)
    );

    reg running;
    reg [4:0] source_index;
    reg serial_sent;
    reg parallel_sent;
    wire feeding = running && source_index < 16;
    wire signed [7:0] source_a = $signed({3'b000, source_index}) - 8'sd8;
    wire signed [7:0] source_b = $signed({3'b000, source_index}) + 8'sd1;
    wire serial_ready;
    wire parallel_ready;
    wire serial_valid = feeding && !serial_sent;
    wire parallel_valid = feeding && !parallel_sent;
    wire serial_out_valid;
    wire parallel_out_valid;
    wire signed [19:0] serial_result;
    wire signed [19:0] parallel_result;
    reg serial_done;
    reg parallel_done;
    reg signed [19:0] saved_serial;
    reg signed [19:0] saved_parallel;

    dot_product_serial serial_engine (
        .clk(clk), .rst(rst),
        .in_valid(serial_valid), .in_ready(serial_ready), .in_a(source_a), .in_b(source_b),
        .out_valid(serial_out_valid), .out_ready(1'b1), .result(serial_result)
    );
    dot_product_parallel parallel_engine (
        .clk(clk), .rst(rst),
        .in_valid(parallel_valid), .in_ready(parallel_ready), .in_a(source_a), .in_b(source_b),
        .out_valid(parallel_out_valid), .out_ready(1'b1), .result(parallel_result)
    );

    always @(posedge clk) begin
        if (rst) begin
            running <= 1'b0;
            source_index <= 0;
            serial_sent <= 1'b0;
            parallel_sent <= 1'b0;
            serial_done <= 1'b0;
            parallel_done <= 1'b0;
            saved_serial <= 0;
            saved_parallel <= 0;
        end else if (!running && start_pulse) begin
            running <= 1'b1;
            source_index <= 0;
            serial_sent <= 1'b0;
            parallel_sent <= 1'b0;
            serial_done <= 1'b0;
            parallel_done <= 1'b0;
            saved_serial <= 0;
            saved_parallel <= 0;
        end else if (running) begin
            if (feeding) begin
                if (serial_valid && serial_ready)
                    serial_sent <= 1'b1;
                if (parallel_valid && parallel_ready)
                    parallel_sent <= 1'b1;
                if ((serial_sent || serial_ready) && (parallel_sent || parallel_ready)) begin
                    source_index <= source_index + 1'b1;
                    serial_sent <= 1'b0;
                    parallel_sent <= 1'b0;
                end
            end
            if (serial_out_valid) begin
                saved_serial <= serial_result;
                serial_done <= 1'b1;
            end
            if (parallel_out_valid) begin
                saved_parallel <= parallel_result;
                parallel_done <= 1'b1;
            end
            if ((serial_done || serial_out_valid) && (parallel_done || parallel_out_valid))
                running <= 1'b0;
        end
    end

    wire both_done = serial_done && parallel_done;
    wire results_match = both_done && (saved_serial == saved_parallel);
    wire result_error = (serial_done && saved_serial != 20'sd272)
                     || (parallel_done && saved_parallel != 20'sd272);
    assign led = {saved_serial[11:0], result_error, results_match, parallel_done, serial_done};
endmodule
