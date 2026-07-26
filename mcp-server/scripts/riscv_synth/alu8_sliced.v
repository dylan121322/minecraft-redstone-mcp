// 8-bit ALU built structurally from 8× alu1 slices with a carry chain.
// SUB uses two's complement: A - B = A + ~B + 1, so bit0's cin = is_sub.
module alu1(input a, input b, input cin, input [3:0] op, output y, output cout);
    wire is_add=(op==4'd2), is_sub=(op==4'd6), is_and=(op==4'd0),
         is_or=(op==4'd1), is_xor=(op==4'd3);
    wire bb = is_sub ? ~b : b;
    wire sum = a ^ bb ^ cin;
    assign cout = (a & bb) | (cin & (a ^ bb));
    assign y = is_add ? sum : is_sub ? sum : is_and ? (a&b) :
               is_or ? (a|b) : is_xor ? (a^b) : 1'b0;
endmodule

module alu8_sliced(input [7:0] data1, input [7:0] data2,
                   input [3:0] ALU_control, output [7:0] ALU_result);
    wire [8:0] carry;
    wire is_sub = (ALU_control == 4'd6);
    assign carry[0] = is_sub;              // two's complement +1 for subtract
    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin : slice
            alu1 u(.a(data1[i]), .b(data2[i]), .cin(carry[i]),
                   .op(ALU_control), .y(ALU_result[i]), .cout(carry[i+1]));
        end
    endgenerate
endmodule
