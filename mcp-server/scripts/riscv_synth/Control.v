// RISC-V 8-bit Control Unit — opcode → control signals
// From ujjwal-2001/RISCV_8bit_pipeline Control.v
module Control(
    input wire [6:0] opcode,
    output wire branch,
    output wire mem_read,
    output wire mem_to_reg,
    output wire [1:0] alu_op,
    output wire mem_write,
    output wire alu_src,
    output wire reg_write
);
    assign branch     = (opcode == 7'b1100011) | (opcode == 7'b1101111);
    assign mem_read   = (opcode == 7'b0000011);
    assign mem_to_reg = (opcode == 7'b0000011);
    assign alu_op     = (opcode == 7'b0110011) ? 2'b10 :
                        (opcode == 7'b1100011) ? 2'b01 :
                        (opcode == 7'b1101111) ? 2'b11 : 2'b00;
    assign mem_write  = (opcode == 7'b0100011);
    assign alu_src    = (opcode == 7'b0000011) | (opcode == 7'b0100011) | (opcode == 7'b1101111);
    assign reg_write  = (opcode == 7'b0110011) | (opcode == 7'b0000011) | (opcode == 7'b1101111);
endmodule
