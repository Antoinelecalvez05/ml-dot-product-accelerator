`timescale 1ns/1ps

module tb_basys3_demo;
    reg clk = 1'b0;
    always #5 clk = !clk;
    reg btnC = 1'b0;
    reg btnU = 1'b0;
    wire [15:0] led;
    basys3_demo #(.DEBOUNCE_CYCLES(3)) dut (.clk(clk), .btnC(btnC), .btnU(btnU), .led(led));
    integer timeout;
    integer input_count;
    integer frame_count = 0;

    task cycles;
        input integer n;
        integer i;
        begin
            for (i = 0; i < n; i = i + 1) begin
                @(posedge clk);
                #1;
            end
        end
    endtask

    always @(posedge clk)
        if (dut.serial_valid && dut.serial_ready) begin
            input_count = input_count + 1;
            if (input_count % 16 == 0)
                frame_count = frame_count + 1;
        end

    initial begin
        input_count = 0;
        cycles(12);
        if (led !== 16'h0000) $fatal(1, "Power-on reset failed");
        @(negedge clk); btnC = 1;
        @(negedge clk); btnC = 0;
        cycles(12);
        if (dut.running !== 1'b0) $fatal(1, "Button debounce failed");
        @(negedge clk); btnC = 1;
        timeout = 0;
        while (led[1] !== 1'b1 && timeout < 100) begin cycles(1); timeout = timeout + 1; end
        if (timeout == 100) $fatal(1, "Parallel result timed out");
        if (led[0] !== 1'b0) $fatal(1, "Parallel engine did not finish before serial engine");
        timeout = 0;
        while (led[0] !== 1'b1 && timeout < 100) begin cycles(1); timeout = timeout + 1; end
        if (led !== 16'h1107) $fatal(1, "Wrong completed LED value %h", led);
        cycles(100);
        if (frame_count != 1) $fatal(1, "Held button retriggered a calculation");
        @(negedge clk); btnC = 0; btnU = 1;
        cycles(12);
        if (led !== 0) $fatal(1, "Reset did not clear results");
        @(negedge clk); btnU = 0;
        cycles(12);
        @(negedge clk); btnC = 1;
        cycles(80);
        if (led !== 16'h1107) $fatal(1, "Restart failed");
        if (frame_count != 2) $fatal(1, "Unexpected frame count after restart");
        $display("PASS: Basys 3 demo reset, debounce, parallel-first completion, result=272, held button, restart");
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "Global board test timeout");
    end
endmodule
