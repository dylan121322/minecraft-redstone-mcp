// N-bit 2-to-1 MUX (parameterized)
// From ujjwal-2001/RISCV_8bit_pipeline Mux_2to1.v
module Mux_2to1 #(parameter N=8)(
    input wire [N-1:0] D0,
    input wire [N-1:0] D1,
    input wire S0,
    output wire [N-1:0] Y
);
    assign Y = S0 ? D1 : D0;
endmodule
