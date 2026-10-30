`timescale 1ns / 1ps
`default_nettype none

// Buffered, signed dot-product engine.
//
// A frame consists of VECTOR_LEN accepted input pairs. A pair is accepted on a
// rising edge only when in_valid && in_ready. After loading, LANES independent
// multiply-accumulate paths process LANES pairs per clock. A separate REDUCE
// clock combines their partial sums, and OUTPUT holds the result until accepted.
//
// The memories deliberately have no reset: every entry is overwritten by a new
// complete frame before COMPUTE can read it. Reset discards any unfinished frame.
module dot_product_core #(
    parameter integer VECTOR_LEN = 16,
    parameter integer DATA_WIDTH = 8,
    parameter integer LANES = 1,
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
    output reg  signed [ACC_WIDTH-1:0]   result
);

    localparam integer PRODUCT_WIDTH = 2 * DATA_WIDTH;
    localparam integer MIN_ACC_WIDTH = PRODUCT_WIDTH
                                    + ((VECTOR_LEN > 1) ? $clog2(VECTOR_LEN) : 0);
    // Safe denominators permit a helpful simulation error for invalid LANES.
    localparam integer SAFE_LANES = (LANES > 0) ? LANES : 1;
    localparam integer GROUPS = VECTOR_LEN / SAFE_LANES;
    localparam integer LOAD_INDEX_WIDTH = (VECTOR_LEN > 1) ? $clog2(VECTOR_LEN) : 1;
    localparam integer GROUP_INDEX_WIDTH = (GROUPS > 1) ? $clog2(GROUPS) : 1;
    localparam integer REDUCTION_LEAVES = (LANES > 1) ? (1 << $clog2(LANES)) : 1;
    localparam integer SIGN_EXTENSION = (ACC_WIDTH >= PRODUCT_WIDTH)
                                     ? (ACC_WIDTH - PRODUCT_WIDTH) : 0;

    localparam [1:0] LOAD    = 2'd0;
    localparam [1:0] COMPUTE = 2'd1;
    localparam [1:0] REDUCE  = 2'd2;
    localparam [1:0] OUTPUT  = 2'd3;

    reg [1:0] state;
    reg [LOAD_INDEX_WIDTH-1:0] write_index;
    reg [GROUP_INDEX_WIDTH-1:0] group_index;

    reg signed [DATA_WIDTH-1:0] a_buffer [0:VECTOR_LEN-1];
    reg signed [DATA_WIDTH-1:0] b_buffer [0:VECTOR_LEN-1];
    reg signed [ACC_WIDTH-1:0] lane_accumulator [0:LANES-1];

    wire signed [PRODUCT_WIDTH-1:0] lane_product [0:LANES-1];
    wire signed [ACC_WIDTH-1:0] extended_product [0:LANES-1];
    wire signed [ACC_WIDTH-1:0] reduction_tree [0:2*REDUCTION_LEAVES-2];

    // Reset is synchronous for stored state. Gating the handshake signals also
    // makes it explicit that no transfers are accepted while rst is asserted.
    assign in_ready = (state == LOAD) && !rst;
    assign out_valid = (state == OUTPUT) && !rst;

    genvar lane;
    generate
        for (lane = 0; lane < LANES; lane = lane + 1) begin : g_mac
            // The interleaved assignment is lane 0: 0,4,8,12; lane 1: 1,5,9,13;
            // etc. for the default four-lane engine. For one lane it is 0..15.
            wire signed [DATA_WIDTH-1:0] operand_a;
            wire signed [DATA_WIDTH-1:0] operand_b;
            assign operand_a = a_buffer[group_index * LANES + lane];
            assign operand_b = b_buffer[group_index * LANES + lane];
            assign lane_product[lane] = operand_a * operand_b;

            // A signed 8x8 multiplication needs 16 bits. Repeat the product's
            // sign bit when extending it to the 20-bit default accumulator.
            assign extended_product[lane] = {
                {SIGN_EXTENSION{lane_product[lane][PRODUCT_WIDTH-1]}},
                lane_product[lane]
            };
        end

        // Leaves are accumulator registers, padded with zeros when LANES is
        // not a power of two. Node 0 is the root. Four lanes therefore form
        // (acc0 + acc1) + (acc2 + acc3), rather than a three-adder serial chain.
        for (lane = 0; lane < REDUCTION_LEAVES; lane = lane + 1) begin : g_leaf
            if (lane < LANES) begin : g_active
                assign reduction_tree[REDUCTION_LEAVES-1+lane] = lane_accumulator[lane];
            end else begin : g_padding
                assign reduction_tree[REDUCTION_LEAVES-1+lane] = {ACC_WIDTH{1'b0}};
            end
        end
        for (lane = 0; lane < REDUCTION_LEAVES-1; lane = lane + 1) begin : g_reduce
            assign reduction_tree[lane] = reduction_tree[2*lane+1]
                                        + reduction_tree[2*lane+2];
        end
    endgenerate

    integer accumulator_index;
    always @(posedge clk) begin
        // Nonblocking assignments (<=) model registers: every right-hand side
        // is evaluated using the values from before this clock edge.
        if (rst) begin
            state <= LOAD;
            write_index <= {LOAD_INDEX_WIDTH{1'b0}};
            group_index <= {GROUP_INDEX_WIDTH{1'b0}};
            result <= {ACC_WIDTH{1'b0}};
            for (accumulator_index = 0; accumulator_index < LANES;
                 accumulator_index = accumulator_index + 1) begin
                lane_accumulator[accumulator_index] <= {ACC_WIDTH{1'b0}};
            end
        end else begin
            case (state)
                LOAD: begin
                    if (in_valid && in_ready) begin
                        a_buffer[write_index] <= in_a;
                        b_buffer[write_index] <= in_b;
                        if (write_index == VECTOR_LEN - 1) begin
                            write_index <= {LOAD_INDEX_WIDTH{1'b0}};
                            group_index <= {GROUP_INDEX_WIDTH{1'b0}};
                            for (accumulator_index = 0; accumulator_index < LANES;
                                 accumulator_index = accumulator_index + 1) begin
                                lane_accumulator[accumulator_index] <= {ACC_WIDTH{1'b0}};
                            end
                            state <= COMPUTE;
                        end else begin
                            write_index <= write_index + 1'b1;
                        end
                    end
                end

                COMPUTE: begin
                    for (accumulator_index = 0; accumulator_index < LANES;
                         accumulator_index = accumulator_index + 1) begin
                        lane_accumulator[accumulator_index] <=
                            lane_accumulator[accumulator_index]
                            + extended_product[accumulator_index];
                    end
                    if (group_index == GROUPS - 1) begin
                        state <= REDUCE;
                    end else begin
                        group_index <= group_index + 1'b1;
                    end
                end

                REDUCE: begin
                    // This separate edge sees the final COMPUTE updates.
                    result <= reduction_tree[0];
                    state <= OUTPUT;
                end

                OUTPUT: begin
                    // No assignment to result here: backpressure holds both
                    // result and out_valid stable for arbitrarily many clocks.
                    if (out_valid && out_ready) begin
                        state <= LOAD;
                    end
                end

                default: begin
                    // Recovery also abandons the current frame; the next
                    // complete frame overwrites all memories and accumulators.
                    state <= LOAD;
                    write_index <= {LOAD_INDEX_WIDTH{1'b0}};
                    group_index <= {GROUP_INDEX_WIDTH{1'b0}};
                    result <= {ACC_WIDTH{1'b0}};
                end
            endcase
        end
    end

    // These checks are for simulation/elaboration; they do not create hardware.
    // synthesis translate_off
    initial begin
        if (VECTOR_LEN < 1)
            $fatal(1, "VECTOR_LEN must be at least 1");
        if (DATA_WIDTH < 2)
            $fatal(1, "DATA_WIDTH must be at least 2");
        if (LANES < 1 || LANES > VECTOR_LEN)
            $fatal(1, "LANES must be between 1 and VECTOR_LEN");
        if (VECTOR_LEN % SAFE_LANES != 0)
            $fatal(1, "VECTOR_LEN must be divisible by LANES");
        if (ACC_WIDTH < MIN_ACC_WIDTH)
            $fatal(1, "ACC_WIDTH is too small for a full-precision dot product");
    end
    // synthesis translate_on

endmodule

`default_nettype wire
