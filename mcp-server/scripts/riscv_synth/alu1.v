// 1-bit ALU slice — building block for bit-sliced 8-bit ALU.
// Carry chain (cin/cout) links slices for ADD/SUB; op broadcasts to all slices.
// ops: AND=0 OR=1 ADD=2 XOR=3 SUB=6 (matches ujjwal-2001 ALU encoding)
module alu1(
    input a,
    input b,
    input cin,
    input [3:0] op,
    output y,
    output cout
);
    wire is_add = (op == 4'd2);
    wire is_sub = (op == 4'd6);
    wire is_and = (op == 4'd0);
    wire is_or  = (op == 4'd1);
    wire is_xor = (op == 4'd3);

    wire bb   = is_sub ? ~b : b;          // subtract: invert b (cin=1 on bit0)
    wire sum  = a ^ bb ^ cin;             // full-adder sum
    wire cout_w = (a & bb) | (cin & (a ^ bb));   // full-adder carry
    assign cout = cout_w;

    assign y = is_add ? sum :
               is_sub ? sum :
               is_and ? (a & b) :
               is_or  ? (a | b) :
               is_xor ? (a ^ b) : 1'b0;
endmodule
