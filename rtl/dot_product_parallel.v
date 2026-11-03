`timescale 1ns / 1ps
`default_nettype none

module dot_product_parallel #(
    parameter integer VECTOR_LEN = 16,
    parameter integer DATA_WIDTH = 8,
    parameter integer ACC_WIDTH = 2 * DATA_WIDTH
                                + ((VECTOR_LEN > 1) ? $clog2(VECTOR_LEN) : 0)
) (
    input  wire                         clk,
    input  wire                         rst,
    input  wire                         in_valid,
    output wire                         in_ready,
    input  wire signed [DATA_WIDTH-1:0]  in_a,
    input  wire signed [DATA_WIDTH-1:0]  in_b,
    output wire                         out_valid,
    input  wire                         out_ready,
    output wire signed [ACC_WIDTH-1:0]   result
);

    dot_product_core #(
        .VECTOR_LEN(VECTOR_LEN),
        .DATA_WIDTH(DATA_WIDTH),
        .LANES(4),
        .ACC_WIDTH(ACC_WIDTH)
    ) core (
        .clk(clk),
        .rst(rst),
        .in_valid(in_valid),
        .in_ready(in_ready),
        .in_a(in_a),
        .in_b(in_b),
        .out_valid(out_valid),
        .out_ready(out_ready),
        .result(result)
    );

endmodule

`default_nettype wire
