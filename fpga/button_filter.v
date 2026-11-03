`timescale 1ns/1ps

module button_filter #(
    parameter integer CYCLES = 1000000
) (
    input wire clk,
    input wire rst,
    input wire raw_button,
    output reg level,
    output reg pressed
);
    localparam integer COUNT_WIDTH = (CYCLES <= 1) ? 1 : $clog2(CYCLES);
    (* ASYNC_REG = "TRUE" *) reg sync_meta;
    (* ASYNC_REG = "TRUE" *) reg sync_value;
    reg [COUNT_WIDTH-1:0] count;

    always @(posedge clk) begin
        if (rst) begin
            sync_meta <= 1'b0;
            sync_value <= 1'b0;
            count <= 0;
            level <= 1'b0;
            pressed <= 1'b0;
        end else begin
            sync_meta <= raw_button;
            sync_value <= sync_meta;
            pressed <= 1'b0;
            if (sync_value == level) begin
                count <= 0;
            end else if (count == CYCLES-1) begin
                count <= 0;
                level <= sync_value;
                pressed <= sync_value;
            end else begin
                count <= count + 1'b1;
            end
        end
    end
endmodule
