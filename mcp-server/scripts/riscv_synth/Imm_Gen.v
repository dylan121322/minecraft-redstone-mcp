// RISC-V Immediate Generator
// From ujjwal-2001/RISCV_8bit_pipeline Imm_Gen.v
module Imm_Gen(
    input wire [31:0] instruction,
    output reg [11:0] immediate
);
    always @* begin
        casex(instruction[6:0])
            7'b000_xxxx: immediate = instruction[31:20];                           // I-type
            7'b011_xxxx: immediate = 0;                                            // R-type
            7'b010_xxxx: immediate = {instruction[31:25], instruction[11:7]};     // S-type
            7'b110_0xxx: immediate = {instruction[31:25], instruction[11:7]};     // SB-type
            7'b110_1xxx: immediate = instruction[31:20];                           // UJ-type
            default: immediate = 0;
        endcase
    end
endmodule
