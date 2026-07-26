// RISC-V Forwarding Unit — 5-bit register comparators
// From ujjwal-2001/RISCV_8bit_pipeline Forwarding_Unit.v
module Forwarding_Unit(
    input wire [4:0] reg_RS1,
    input wire [4:0] reg_RS2,
    input wire [4:0] ex_mem_reg_RD,
    input wire [4:0] mem_wb_reg_RD,
    input wire ex_mem_regwrite,
    input wire mem_wb_regwrite,
    output reg [1:0] fwd_A,
    output reg [1:0] fwd_B
);
    always @* begin
        // Forward A
        if (ex_mem_regwrite && ex_mem_reg_RD != 0 && ex_mem_reg_RD == reg_RS1)
            fwd_A = 2'b10;
        else if (mem_wb_regwrite && mem_wb_reg_RD != 0 && mem_wb_reg_RD == reg_RS1)
            fwd_A = 2'b01;
        else
            fwd_A = 2'b00;
        // Forward B
        if (ex_mem_regwrite && ex_mem_reg_RD != 0 && ex_mem_reg_RD == reg_RS2)
            fwd_B = 2'b10;
        else if (mem_wb_regwrite && mem_wb_reg_RD != 0 && mem_wb_reg_RD == reg_RS2)
            fwd_B = 2'b01;
        else
            fwd_B = 2'b00;
    end
endmodule
